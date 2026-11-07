/*
 * venctrace.so: records what the vendor encoder library does to the hardware, for the free encoder (2026-11-07: the
 * H.264 sub stream, whose lists alone do not run on the core). The 3.0 port of the 2.x libtc100fix tracer: preloaded
 * into tc100_rtsp (LD_PRELOAD), it catches AKV_Encoder_Init (libakv_encode.so, called by libmpi_venc_ex.so with the
 * table of 22 hardware callbacks of libplat_venc_cb.so), wraps the register read / write, DMA alloc / free, reset and
 * interrupt wait entries, and keeps every call in RAM. Off unless VENC_TRACE is set; it changes nothing in the encoding.
 *
 *   VENC_TRACE=/tmp/venc   file /tmp/venc.trc, written once the buffer is full (or at VENC_TRACE_RECS records)
 *   VENC_TRACE_KB=1024     record buffer
 *
 * venc.trc: the format of src/h265enc/hwseq.py: "TC100VTR", u32 version 1, u32 16, then 16-byte records
 *   u32 time (us), u16 type, u16 aux, u32 a, u32 b: 1 read (reg, value), 2 write (reg, value), 3 alloc (size, paddr),
 *   4 free (paddr), 5 interrupt wait (aux 0 start, 1 end), 6 reset, 8 init, 9 blob (paddr, length; the next
 *   ceil(length / 16) records are that DMA memory: aux 0 = the list when its address is written to 0x8080, aux 1 =
 *   the same list after the interrupt).
 * The traces are data read from the vendor encoder: they stay on the test machine, never in git.
 * Built like libakuio (uClibc names only, stand-in libc / libdl / libpthread at link time): see the Makefile.
 * License: GPL-2.0-or-later
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <unistd.h>

#define VT_NCB 22
enum { VT_READ = 1, VT_WRITE, VT_ALLOC, VT_FREE, VT_IRQ, VT_RESET, VT_FRAME, VT_INIT, VT_BLOB };
#define VT_MAPS 64
#define VT_BLOB_MAX 0x1c0u

struct vt_rec { uint32_t t; uint16_t type, aux; uint32_t a, b; };

static void *real_cb[VT_NCB];
static struct vt_rec *recs;
static size_t n_recs, max_recs;
static int vt_state;			/* 0 off, 1 recording, 2 written */
static uint32_t last_cmd;
static int64_t t0;
static pthread_mutex_t vt_lock = PTHREAD_MUTEX_INITIALIZER;
static struct { uint32_t paddr, size; const unsigned char *vaddr; } maps[VT_MAPS];

static int64_t vt_us(void)
{
	struct timeval tv;

	gettimeofday(&tv, NULL);
	return (int64_t)tv.tv_sec * 1000000 + tv.tv_usec;
}

static void vt_write_file(void)
{
	const char *base = getenv("VENC_TRACE");
	char path[256];
	size_t l;
	int fd;
	uint32_t hdr[2] = { 1, sizeof(struct vt_rec) };

	if (!base || (l = strlen(base)) > 240) return;
	memcpy(path, base, l); memcpy(path + l, ".trc", 5);
	fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
	if (fd < 0) return;
	(void)!write(fd, "TC100VTR", 8);
	(void)!write(fd, hdr, sizeof hdr);
	(void)!write(fd, recs, n_recs * sizeof(struct vt_rec));
	close(fd);
}

static void vt_add(uint16_t type, uint16_t aux, uint32_t a, uint32_t b)
{
	if (vt_state != 1) return;
	pthread_mutex_lock(&vt_lock);
	if (vt_state == 1) {
		int64_t now = vt_us();

		if (!t0) t0 = now;
		recs[n_recs].t = (uint32_t)(now - t0);
		recs[n_recs].type = type; recs[n_recs].aux = aux;
		recs[n_recs].a = a; recs[n_recs].b = b;
		if (++n_recs >= max_recs) { vt_state = 2; vt_write_file(); }
	}
	pthread_mutex_unlock(&vt_lock);
}

static void vt_blob(uint32_t paddr, uint16_t aux)
{
	int i;

	if (vt_state != 1) return;
	pthread_mutex_lock(&vt_lock);
	for (i = 0; vt_state == 1 && i < VT_MAPS; i++) {
		if (maps[i].vaddr && paddr >= maps[i].paddr && paddr < maps[i].paddr + maps[i].size) {
			uint32_t len = maps[i].paddr + maps[i].size - paddr, nrec;

			if (len > VT_BLOB_MAX) len = VT_BLOB_MAX;
			nrec = (len + 15) / 16;
			if (n_recs + 2 + nrec >= max_recs) break;
			recs[n_recs].t = (uint32_t)(vt_us() - t0); recs[n_recs].type = VT_BLOB; recs[n_recs].aux = aux;
			recs[n_recs].a = paddr; recs[n_recs].b = len;
			n_recs++;
			memset(&recs[n_recs], 0, nrec * 16);
			memcpy(&recs[n_recs], maps[i].vaddr + (paddr - maps[i].paddr), len);
			n_recs += nrec;
			break;
		}
	}
	pthread_mutex_unlock(&vt_lock);
}

static uint32_t w_read(uint32_t reg)				/* 3 */
{
	uint32_t v = ((uint32_t (*)(uint32_t))real_cb[3])(reg);

	vt_add(VT_READ, 0, reg, v);
	return v;
}

static void w_write(uint32_t reg, uint32_t val)			/* 4 */
{
	if ((reg & 0xffffu) == 0x8080u) { vt_blob(val, 0); last_cmd = val; }
	((void (*)(uint32_t, uint32_t))real_cb[4])(reg, val);
	vt_add(VT_WRITE, 0, reg, val);
}

static void *w_alloc(uint32_t size, uint32_t arg)		/* 5: returns {vaddr, paddr, size, self} */
{
	uint32_t *d = ((uint32_t *(*)(uint32_t, uint32_t))real_cb[5])(size, arg);
	int i;

	vt_add(VT_ALLOC, 0, size, d ? d[1] : 0);
	if (d && d[0]) {
		pthread_mutex_lock(&vt_lock);
		for (i = 0; i < VT_MAPS; i++)
			if (!maps[i].vaddr) { maps[i].vaddr = (const unsigned char *)(uintptr_t)d[0]; maps[i].paddr = d[1]; maps[i].size = size; break; }
		pthread_mutex_unlock(&vt_lock);
	}
	return d;
}

static int w_free(uint32_t *d)					/* 6 */
{
	int i;

	vt_add(VT_FREE, 0, d ? d[1] : 0, 0);
	if (d) {
		pthread_mutex_lock(&vt_lock);
		for (i = 0; i < VT_MAPS; i++)
			if (maps[i].vaddr && maps[i].paddr == d[1]) maps[i].vaddr = NULL;
		pthread_mutex_unlock(&vt_lock);
	}
	return ((int (*)(uint32_t *))real_cb[6])(d);
}

static void w_reset(uint32_t arg)				/* 10 */
{
	vt_add(VT_RESET, 0, arg, 0);
	((void (*)(uint32_t))real_cb[10])(arg);
}

static void w_irq(uint32_t arg)					/* 19 */
{
	uint32_t c;

	vt_add(VT_IRQ, 0, arg, 0);
	((void (*)(uint32_t))real_cb[19])(arg);
	vt_add(VT_IRQ, 1, arg, 0);
	c = last_cmd;
	if (c) { vt_blob(c, 1); last_cmd = 0; }
}

int AKV_Encoder_Init(void *table)
{
	static int (*real)(void *);
	const char *e = getenv("VENC_TRACE"), *kb = getenv("VENC_TRACE_KB");
	void *copy[VT_NCB];
	long k = 1024;

	if (!real) real = (int (*)(void *))dlsym(RTLD_NEXT, "AKV_Encoder_Init");
	if (!real) return -1;
	if (!e || !e[0] || !table) return real(table);
	if (!recs) {
		if (kb) { k = 0; while (*kb >= '0' && *kb <= '9') k = k * 10 + (*kb++ - '0'); }
		if (k < 64 || k > 8192) k = 1024;
		max_recs = (size_t)k * 1024 / sizeof(struct vt_rec);
		if (!(recs = malloc(max_recs * sizeof(struct vt_rec)))) return real(table);
		memcpy(real_cb, table, sizeof real_cb);
		vt_state = 1;
	}
	memcpy(copy, table, sizeof copy);
	/* every call (one per channel?): the same callbacks are wrapped */
	if (copy[3] == real_cb[3]) copy[3] = (void *)w_read;
	if (copy[4] == real_cb[4]) copy[4] = (void *)w_write;
	if (copy[5] == real_cb[5]) copy[5] = (void *)w_alloc;
	if (copy[6] == real_cb[6]) copy[6] = (void *)w_free;
	if (copy[10] == real_cb[10]) copy[10] = (void *)w_reset;
	if (copy[19] == real_cb[19]) copy[19] = (void *)w_irq;
	vt_add(VT_INIT, 0, 6, 0);
	return real(copy);	/* AKV_Encoder_Init copies the table (2.x): a local copy is enough */
}
