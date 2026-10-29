// SPDX-License-Identifier: GPL-2.0
/*
 * libakuio, free replacement for the vendor library of the same name.
 *
 * Exports the functions the vendor media libraries (libmpi_venc, libplat_vi,
 * libplat_venc_cb, libmpi_osd) import, with the same names and the same
 * 32-bit ABI, on top of the ak39_venc kernel driver (/dev/uio0):
 *
 *   akuio_pmem_init / _fini         open the device, map the DMA pool
 *   akuio_alloc_pmem / _free_pmem   sub-allocate from the pool (32-byte units)
 *   akuio_vaddr2paddr               physical address of a pool pointer (or of an akuio_map_extra region)
 *   akuio_map_extra                 declare a contiguous region outside the pool (V4L2 capture buffers)
 *   akuio_map_regs / _unmap_regs    map the encoder register window
 *   akuio_wait_irq                  wait for the encoder interrupt
 *   akuio_reset_video               pulse the core reset
 *   akuio_sysreg_write              clock-gate / reset bits of the encoder
 *   akuio_clean_invalidate_dcache   no-op: the pool is write-combined
 *   akuio_lock_timewait / _unlock   no-ops, as in the vendor library
 *   akuio_get_used_pmem / _free_pmem  byte counts
 *
 * Behaviour taken from the vendor library by disassembly: allocation sizes
 * are rounded up to 32 bytes, pmem_init / pmem_fini are reference counted,
 * failures print "E/[libakuio]" lines on stderr and return 0 / -1.
 */
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/time.h>
#include <unistd.h>

#include "ak39_venc.h"

#define UNIT 32u

static int dbg = -1;
#define DBG(...) do { if (dbg < 0) dbg = getenv("AKUIO_DEBUG") != NULL; if (dbg) ERR(__VA_ARGS__); } while (0)

struct blk {			/* a free or used extent of the pool */
	uint32_t off, size;
	struct blk *next;	/* kept sorted by offset */
	int used;
};

static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static int fd = -1, refs;
static struct ak39_venc_pool_info info;
static uint8_t *pool;
static struct blk *blocks;
static uint32_t used_bytes;
static uint8_t *regs;
static size_t regs_len;

#define ERR(fmt, ...) fprintf(stderr, "E/[libakuio]: " fmt, ##__VA_ARGS__)

#ifdef AKUIO_SELFTEST
/* test hook: lets the self test run without the device */
int akuio_test_attach(void *mem, uint32_t paddr, uint32_t size)
{
	pthread_mutex_lock(&lock);
	if (refs) {
		refs++;
		pthread_mutex_unlock(&lock);
		return 0;
	}
	info.paddr = paddr;
	info.size = size;
	pool = mem;
	blocks = calloc(1, sizeof(*blocks));
	blocks->size = size;
	refs = 1;
	pthread_mutex_unlock(&lock);
	return 0;
}
#endif

int akuio_pmem_init(void)
{
	const char *dev = getenv("AKUIO_DEV");
	void *p;

	pthread_mutex_lock(&lock);
	if (refs > 0) {
		refs++;
		pthread_mutex_unlock(&lock);
		return 0;
	}
	fd = open(dev ? dev : "/dev/uio0", O_RDWR | O_CLOEXEC);
	if (fd < 0) {
		ERR("UIO0 device open failed: %s\n", strerror(errno));
		goto fail;
	}
	if (ioctl(fd, AK39_VENC_POOL_INFO, &info) < 0) {
		ERR("pool info: %s\n", strerror(errno));
		goto fail_close;
	}
	p = mmap(NULL, info.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd,
		 AK39_VENC_MMAP_POOL);
	if (p == MAP_FAILED) {
		ERR("map pool error: %s\n", strerror(errno));
		goto fail_close;
	}
	if (getenv("AKUIO_UC")) {
		/* /dev/mem maps a no-map region uncached and unbuffered */
		int mf = open("/dev/mem", O_RDWR | O_SYNC | O_CLOEXEC);
		void *u = mf < 0 ? MAP_FAILED :
			mmap(NULL, info.size, PROT_READ | PROT_WRITE, MAP_SHARED, mf, info.paddr);

		if (mf >= 0)
			close(mf);
		if (u != MAP_FAILED) {
			munmap(p, info.size);
			p = u;
			ERR("pool mapped uncached through /dev/mem\n");
		} else {
			ERR("uncached pool mapping failed: %s\n", strerror(errno));
		}
	}
	pool = p;
	blocks = calloc(1, sizeof(*blocks));
	if (!blocks) {
		munmap(p, info.size);
		goto fail_close;
	}
	blocks->size = info.size & ~(UNIT - 1);
	used_bytes = 0;
	refs = 1;
	pthread_mutex_unlock(&lock);
	return 0;
fail_close:
	close(fd);
	fd = -1;
fail:
	pthread_mutex_unlock(&lock);
	return -1;
}

int akuio_pmem_fini(void)
{
	struct blk *b, *n;

	pthread_mutex_lock(&lock);
	if (refs > 1) {
		refs--;
		pthread_mutex_unlock(&lock);
		return 0;
	}
	for (b = blocks; b; b = n) {
		n = b->next;
		free(b);
	}
	blocks = NULL;
	if (fd >= 0) {
		munmap(pool, info.size);
		close(fd);
		fd = -1;
	}
	refs = 0;
	pthread_mutex_unlock(&lock);
	return 0;
}

unsigned long akuio_alloc_pmem(int size)
{
	struct blk *b, *rest;
	uint32_t need;

	pthread_mutex_lock(&lock);
	if (refs < 1) {
		pthread_mutex_unlock(&lock);
		ERR("akuio_alloc_pmem error: akuio not init\n");
		return 0;
	}
	need = ((uint32_t)size + UNIT - 1) & ~(UNIT - 1);
	if (size <= 0 || need == 0) {
		pthread_mutex_unlock(&lock);
		return 0;
	}
	{
		static uint32_t align = ~0u;

		if (align == ~0u) {
			const char *e = getenv("AKUIO_ALIGN");

			align = e ? (uint32_t)atoi(e) : UNIT;
			if (align < UNIT)
				align = UNIT;
		}
		for (b = blocks; b; b = b->next) {
			uint32_t a, pad;

			if (b->used)
				continue;
			a = (b->off + align - 1) & ~(align - 1);
			pad = a - b->off;
			if (b->size < pad + need)
				continue;
			if (pad) {		/* split the leading padding off */
				rest = calloc(1, sizeof(*rest));
				if (!rest)
					break;
				rest->off = a;
				rest->size = b->size - pad;
				rest->next = b->next;
				b->next = rest;
				b->size = pad;
				b = rest;
			}
			break;
		}
	}
	if (!b || b->used || b->size < need) {
		pthread_mutex_unlock(&lock);
		ERR("no space for allocating %ubytes of pmem\n", need);
		return 0;
	}
	if (b->size > need) {
		rest = calloc(1, sizeof(*rest));
		if (!rest) {
			pthread_mutex_unlock(&lock);
			ERR("malloc entry is NULL\n");
			return 0;
		}
		rest->off = b->off + need;
		rest->size = b->size - need;
		rest->next = b->next;
		b->next = rest;
		b->size = need;
	}
	b->used = 1;
	used_bytes += b->size;
	DBG("A %u @%x used %u\n", need, b->off, used_bytes);
	if (!getenv("AKUIO_NOZERO"))	/* the pool keeps the previous process' data: hand out zeroed memory */
		memset(pool + b->off, 0, need);
	pthread_mutex_unlock(&lock);
	return (unsigned long)(pool + b->off);
}

void akuio_free_pmem(unsigned long vaddr)
{
	struct blk *b, *prev = NULL;

	if (!vaddr) {
		ERR("akuio_free_pmem input arg is NULL\n");
		return;
	}
	pthread_mutex_lock(&lock);
	for (b = blocks; b; prev = b, b = b->next)
		if (b->used && (uintptr_t)(pool + b->off) == vaddr)
			break;
	if (!b) {
		pthread_mutex_unlock(&lock);
		ERR("akuio_free_pmem can't find %p in dma memory list\n",
		    (void *)vaddr);
		return;
	}
	b->used = 0;
	used_bytes -= b->size;
	DBG("F @%x size %u used %u\n", b->off, b->size, used_bytes);
	if (b->next && !b->next->used) {	/* merge with the next */
		struct blk *n = b->next;

		b->size += n->size;
		b->next = n->next;
		free(n);
	}
	if (prev && !prev->used) {		/* merge with the previous */
		prev->size += b->size;
		prev->next = b->next;
		free(b);
	}
	pthread_mutex_unlock(&lock);
}

/* Physically contiguous memory outside the pool that the encoder and the JPEG engine may read: the V4L2 capture
 * buffers, so that tc100_rtsp hands a captured picture to the encoder without copying it into the pool.
 * akuio_map_extra(vaddr, paddr, size) adds a region (size 0 removes the one at vaddr); returns 0 or -1. */
#define NEXTRA 4
static struct { uintptr_t v; uint32_t p, size; } extra[NEXTRA];

int akuio_map_extra(unsigned long vaddr, unsigned long paddr, unsigned long size)
{
	int i, ret = -1;

	pthread_mutex_lock(&lock);
	for (i = 0; i < NEXTRA; i++) {
		if (size && !extra[i].size) {
			extra[i].v = vaddr; extra[i].p = (uint32_t)paddr; extra[i].size = (uint32_t)size;
			ret = 0;
			break;
		}
		if (!size && extra[i].size && extra[i].v == vaddr) { extra[i].size = 0; ret = 0; break; }
	}
	pthread_mutex_unlock(&lock);
	DBG("akuio_map_extra(%#lx, %#lx, %lu): %d\n", vaddr, paddr, size, ret);
	return ret;
}

int akuio_vaddr2paddr(unsigned long vaddr)
{
	struct blk *b;
	int ret = 0;

	if (!vaddr) {
		ERR("akuio_vaddr2paddr input arg is NULL\n");
		return 0;
	}
	pthread_mutex_lock(&lock);
	if (refs < 1) {
		pthread_mutex_unlock(&lock);
		ERR("akuio_vaddr2paddr error: akuio not init\n");
		return 0;
	}
	for (b = blocks; b; b = b->next) {
		uintptr_t s = (uintptr_t)(pool + b->off);

		if (b->used && vaddr >= s && vaddr < s + b->size) {
			ret = info.paddr + (vaddr - (uintptr_t)pool);
			break;
		}
	}
	for (int i = 0; !ret && i < NEXTRA; i++)
		if (extra[i].size && vaddr >= extra[i].v && vaddr < extra[i].v + extra[i].size)
			ret = (int)(extra[i].p + (vaddr - extra[i].v));
	pthread_mutex_unlock(&lock);
	if (!ret)
		ERR("akuio_vaddr2paddr can't find %p in dma memory list\n",
		    (void *)vaddr);
	return ret;
}

unsigned long akuio_map_regs(unsigned long paddr, size_t len)
{
	void *p;

	pthread_mutex_lock(&lock);
	if (refs < 1 && fd < 0) {
		pthread_mutex_unlock(&lock);
		if (akuio_pmem_init())
			return 0;
		pthread_mutex_lock(&lock);
	}
	if (paddr < info.regs_paddr ||
	    paddr + len > (uint64_t)info.regs_paddr + info.regs_size) {
		pthread_mutex_unlock(&lock);
		ERR("Can't found uio mapping for 0x%08lx\n", paddr);
		return 0;
	}
	p = mmap(NULL, info.regs_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd,
		 AK39_VENC_MMAP_REGS);
	if (p == MAP_FAILED) {
		pthread_mutex_unlock(&lock);
		ERR("mmap() failed: %s\n", strerror(errno));
		return 0;
	}
	regs = p;
	regs_len = info.regs_size;
	pthread_mutex_unlock(&lock);
	return (unsigned long)(regs + (paddr - info.regs_paddr));
}

void akuio_unmap_regs(unsigned long vaddr, size_t len)
{
	(void)len;
	pthread_mutex_lock(&lock);
	if (regs) {
		munmap(regs, regs_len);
		regs = NULL;
	} else {
		fprintf(stderr, "W/[libakuio]: WARNING: akuio_unmap_regs can't find uio mapping for %p\n",
			(void *)vaddr);
	}
	pthread_mutex_unlock(&lock);
}

/*
 * The encoder library passes a pointer to an int preset to -1 and expects
 * the index of the interrupt that fired (a bit number of the status
 * register 0x20028014: 4 bits per core, 18 for the JPEG core).  The vendor
 * kernel driver returned it; ours only waits, so it is derived here from
 * the status register.
 */
#define IRQ_STATUS_REG	0x20028014u

static volatile uint32_t *sysc;

static void irqdbg(const char *tag)
{
	char b[160];
	uint32_t r10 = 0, r14 = 0, r1c = 0;
	int n;

	if (!sysc) {
		int mf = open("/dev/mem", O_RDONLY | O_SYNC | O_CLOEXEC);
		void *m = mf < 0 ? MAP_FAILED : mmap(NULL, 4096, PROT_READ, MAP_SHARED, mf, 0x08000000);

		if (mf >= 0)
			close(mf);
		if (m == MAP_FAILED)
			return;
		sysc = m;
	}
	if (regs) {
		r10 = *(volatile uint32_t *)(regs + 0x8010);
		r14 = *(volatile uint32_t *)(regs + 0x8014);
		r1c = *(volatile uint32_t *)(regs + 0x801c);
	}
	n = snprintf(b, sizeof b, "IRQDBG %s st4c=%08x mask24=%08x r10=%08x r14=%08x r1c=%08x\n", tag,
		     sysc[0x4c / 4], sysc[0x24 / 4], r10, r14, r1c);
	(void)!write(2, b, n);
	if (regs && getenv("AKUIO_REGDUMP")) {
		int i;

		n = snprintf(b, sizeof b, "REGS %s", tag);
		for (i = 0; i < 16; i++)
			n += snprintf(b + n, sizeof b - n, " %08x", *(volatile uint32_t *)(regs + 0x8000 + 4 * i));
		b[n++] = 10;
		(void)!write(2, b, n);
	}
}

/* experiment: called by the register-trace hook just before the encoder start register is written */
void akuio_fixqp(uint32_t list_paddr)
{
	uint32_t *l, qp, pp;
	uint8_t *par;

	if (!pool || list_paddr < info.paddr || list_paddr - info.paddr + 0x100 > info.size)
		return;
	l = (uint32_t *)(void *)(pool + (list_paddr - info.paddr));
	qp = (l[3] >> 16) & 0xff;
	pp = l[0x8c / 4];
	if (pp < info.paddr || pp - info.paddr + 64 > info.size)
		return;
	par = pool + (pp - info.paddr);
	if (getenv("AKUIO_DEBUG"))
		fprintf(stderr, "fixqp list=%08x qp=%u param[19]=%u\n", list_paddr, qp, par[19]);
	if (par[19] == 36 || par[19] == qp)
		par[19] = (uint8_t)qp;
}

void akuio_wait_irq(unsigned long arg)
{
	int dummy = 0;
	int *res = arg ? (int *)arg : &dummy;
	uint32_t st = 0;

	if (getenv("AKUIO_STRAY")) {	/* debug: address-looking words of the small blocks (command lists) that point outside the pool */
		static int shown;
		struct blk *bk;

		for (bk = blocks; bk && shown < 40; bk = bk->next) {
			uint32_t k;

			if (!bk->used || bk->size > 4096)
				continue;
			for (k = 0; k + 4 <= bk->size && shown < 40; k += 4) {
				uint32_t w = *(uint32_t *)(void *)(pool + bk->off + k);

				if (w >= 0x80000000u && w < 0x90000000u && (w < info.paddr || w >= info.paddr + info.size)) {
					fprintf(stderr, "STRAY word %08x in block @%x+%x (size %u)\n", w, bk->off, k, bk->size);
					shown++;
				}
			}
		}
	}
	{
		static int n;
		const char *pre = getenv("AKUIO_DUMP");

		if (pre) {	/* snapshot of the small pool blocks (command lists, tables) */
			char name[96];
			struct blk *bk;
			int of;

			snprintf(name, sizeof name, "%s.%d", pre, n++);
			of = open(name, O_WRONLY | O_CREAT | O_TRUNC, 0644);
			if (of >= 0) {
				for (bk = blocks; bk; bk = bk->next) {
					uint32_t hd[2] = { bk->off, bk->size };

					if (!bk->used || bk->size > 30000)
						continue;
					(void)!write(of, hd, sizeof hd);
					(void)!write(of, pool + bk->off, bk->size);
				}
				close(of);
			}
		}
	}
	if (regs && getenv("AKUIO_REGSCAN")) {	/* debug: DRAM-looking register values outside the pool (a DMA target the kernel does not own) */
		static uint32_t seen_o[64], seen_v[64];
		static int nseen;
		uint32_t o;

		for (o = 0; o < 0x400 && o + 4 <= regs_len - 0x8000; o += 4) {
			uint32_t w = *(volatile uint32_t *)(regs + 0x8000 + o);
			int k;

			if (w < 0x80000000u || w >= 0x84000000u || (w >= info.paddr && w < info.paddr + info.size))
				continue;
			for (k = 0; k < nseen; k++)
				if (seen_o[k] == o && seen_v[k] == w)
					break;
			if (k == nseen && nseen < 64) {
				seen_o[nseen] = o;
				seen_v[nseen++] = w;
				fprintf(stderr, "REGSCAN reg 0x%04x = %08x outside the pool (%08x..%08x)\n", 0x8000 + o, w,
					info.paddr, info.paddr + (uint32_t)info.size);
			}
		}
	}
	struct timeval t0, t1;
	if (getenv("AKUIO_IRQDBG")) irqdbg("pre ");
	gettimeofday(&t0, NULL);
	if (ioctl(fd, AKUIO_WAIT_IRQ, (unsigned long)res) < 0) {
		if (getenv("AKUIO_IRQDBG")) irqdbg("FAIL");
		ERR("akuio_wait_irq: ioctl AKUIO_WAIT_IRQ error: %s\n",
		    strerror(errno));
		return;
	}
	{
		static int dly = -1;

		if (dly < 0) {
			const char *e = getenv("AKUIO_DELAY_US");

			dly = e ? atoi(e) : 0;
		}
		if (dly)
			usleep(dly);
	}
	if (regs && IRQ_STATUS_REG >= info.regs_paddr &&
	    IRQ_STATUS_REG - info.regs_paddr < regs_len)
		st = *(volatile uint32_t *)(regs + IRQ_STATUS_REG - info.regs_paddr);
	*res = st ? __builtin_ctz(st) : 0;
	if (regs) {			/* clear the sticky status (0x20028018) so the next frame's wait blocks */
		static int clr = -1;
		volatile uint32_t *s18 = (volatile uint32_t *)(regs + 0x8018);

		if (clr < 0) {
			const char *e = getenv("AKUIO_CLR");

			clr = e ? atoi(e) : 1;	/* default: write-1-to-clear */
		}
		if (clr) {
			uint32_t b4 = *s18;

			*s18 = clr == 1 ? b4 : clr == 2 ? 0 : 0xffffffffu;
			if (getenv("AKUIO_IRQDBG"))
				fprintf(stderr, "CLR mode %d: 0x18 %08x -> %08x\n", clr, b4, *s18);
		}
	}
	if (getenv("AKUIO_IRQDBG")) {
		char tb[64];
		int tn;

		gettimeofday(&t1, NULL);
		tn = snprintf(tb, sizeof tb, "IRQDBG waited %ld us\n", (t1.tv_sec - t0.tv_sec) * 1000000L + (t1.tv_usec - t0.tv_usec));
		(void)!write(2, tb, tn);
		irqdbg("post");
	}
	if (dbg) {
		char b[] = "irq st=00000000 idx=00\n";
		for (int i = 0; i < 8; i++) b[7 + i] = "0123456789abcdef"[(st >> (28 - 4 * i)) & 15];
		b[20] = '0' + *res / 10; b[21] = '0' + *res % 10;
		(void)!write(2, b, sizeof b - 1);
	}
}

void akuio_reset_video(void)
{
	if (ioctl(fd, AKUIO_VIDEO_RESET, 0) < 0)
		ERR("akuio_reset_video: ioctl AKUIO_VIDEO_RESET error: %s\n",
		    strerror(errno));
}

void akuio_sysreg_write(unsigned int paddr, unsigned int val, unsigned int mask)
{
	struct akuio_sysreg_write_t w = { paddr, val, mask };

	if (fd < 0 || ioctl(fd, AKUIO_SYSREG_WRITE, &w) < 0)
		ERR("===akuio_sysreg_write occur error: %s========uio0_fd:%x\n",
		    strerror(errno), fd);
}

void akuio_clean_invalidate_dcache(void) { }
int akuio_lock_timewait(void) { return 0; }
int akuio_unlock(void) { return 0; }

unsigned long akuio_get_used_pmem(void)
{
	return used_bytes;
}

unsigned long akuio_get_free_pmem(void)
{
	return info.size - used_bytes;
}
