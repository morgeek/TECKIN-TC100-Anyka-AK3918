/*
 * h265enc: first run of the AK3918EV300 encoder core in H.265 WITHOUT the vendor control software (libakv_encode,
 * libmpi_venc): one IDR picture of a 1920x1080 NV12 frame, at a fixed QP. Step 2 of the free encoder (2026-11-07);
 * see README.md and capture.py.
 *
 *   h265enc [--dry] [--run] [-q QP] [--params params.bin] LISTDIR in.nv12 out.h265
 *
 *   LISTDIR   list.bin (the 64 input words of an IDR command list of the vendor encoder), tables.bin (0x4040 bytes),
 *             and optionally work.bin (0x6400) and small.bin (0x100): written by `capture.py DIR --out LISTDIR` from
 *             captures made on the camera (AKUIO_CAPTURE). Data read from the camera: never in git.
 *   --dry     (default) build the list with this program's buffers and print it; touches no hardware
 *   --run     encode on the hardware. tc100_rtsp must be stopped (it owns the encoder): ONLY on a test camera.
 *   -q QP     slice QP (default 30; the list's own otherwise)
 *   --params  the VPS/SPS/PPS NALs to put before the picture (capture.py writes the vendor's as params.bin)
 *   --head    the start code, NAL header and slice header put before the core's slice data (capture.py: slicehead.bin;
 *             IPCAM2 capture, 2026-11-07: the core writes only the slice data, from stream +0x820, and its length in
 *             list word 0x41; the header bytes depend on the QP: use the template's own QP with the vendor's head)
 *
 * What it does on the hardware, from the recorded sequence of the vendor library (hwseq.py) and the start of the JPEG
 * path that works (src/jpegenc): the init of the core, the list in DMA memory, 0x8080 = list, 0x8084 = 2, up to two
 * interrupts (the vendor waits twice per picture; the driver gives up after 2 s), the acknowledge. The stream buffer is
 * filled with 0xa5 first, so the bytes the core wrote are known without knowing yet where it gives their number; the
 * words it writes back in the list (0x40-0x6f) are printed for that question.
 * Outputs: out.h265.raw (the stream buffer up to the last byte the core wrote), out.h265.list (the 112 words after the
 * run) and out.h265 (params.bin + the NALs found in the raw buffer), for `ffprobe out.h265`.
 *
 * License: GPL-2.0-or-later
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#ifndef H265ENC_NO_DEVICE
#include "../libakuio/ak39_venc.h"
#endif

#define W 1920
#define H 1080
#define LIST_WORDS 112

/* pool layout (offsets): the stream buffer as the vendor's (0x7e900 bytes), the side buffers, the list, the source
 * (NV12, stride 1920) and one frame buffer for the reconstructed picture (0x340000: Y, UV +0x1fe000, motion-vector info
 * +0x2fd000, co-located info +0x300400, as cmdlist.FRAME_PLANE_OFFSETS) */
#define STREAM_OFF	0x000000u
#define STREAM_ALLOC	0x7e900u
#define STREAM_HEAD	0x820u
#define TABLES_OFF	0x080000u
#define TABLES_SIZE	0x4040u
#define WORK_OFF	0x088000u
#define WORK_SIZE	0x6400u
#define SMALL_OFF	0x08f000u
#define SMALL_SIZE	0x100u
#define LIST_OFF	0x08f400u
#define SRC_Y_OFF	0x100000u
#define SRC_UV_OFF	(SRC_Y_OFF + W * H)
#define REC_OFF		0x400000u
#define FRAME_SIZE	0x340000u
#define POOL_NEED	(REC_OFF + FRAME_SIZE)
#define REC_UV		0x1fe000u
#define REC_MVINFO	0x2fd000u
#define REC_COLINFO	0x300400u
#define SRC_STRIDE	1920u
#define REC_PITCH	0x1e00u

/* registers, offsets in the window at 0x20020000 (hwseq.py, src/jpegenc/jpeg_hw.h) */
#define R_IRQ_EN	0x8010
#define R_MASK		0x8014
#define R_STAT_CLR	0x8018
#define R_STAT		0x801c
#define R_ACK		0x8020
#define R_LIST		0x8080
#define R_START		0x8084
#define R_UNK		0x8300
#define R_CLK		0xc004

static volatile uint32_t *regs __attribute__((unused));
#define RD(o)	(regs[(o) / 4])
#define WR(o, v) (regs[(o) / 4] = (v))

static int load(const char *dir, const char *name, void *dst, size_t n, int need)
{
	char p[1024];
	FILE *f;
	size_t got;

	snprintf(p, sizeof p, "%s/%s", dir, name);
	f = fopen(p, "rb");
	if (!f) {
		if (need) fprintf(stderr, "cannot open %s: %s\n", p, strerror(errno));
		return need ? -1 : 0;
	}
	got = fread(dst, 1, n, f);
	fclose(f);
	if (got != n) { fprintf(stderr, "%s: %zu bytes, %zu expected\n", p, got, n); return -1; }
	return 1;
}

/* the template's input words with this program's buffers (the address words of cmdlist.build_list for an IDR) */
static void patch_list(uint32_t *l, uint32_t base, int qp)
{
	uint32_t size = STREAM_ALLOC - 0x200, rec = base + REC_OFF;
	int i;

	l[0x20] = base + SRC_Y_OFF; l[0x21] = base + SRC_UV_OFF; l[0x22] = SRC_STRIDE;
	l[0x23] = base + TABLES_OFF;
	l[0x24] = rec; l[0x25] = rec + REC_UV; l[0x26] = REC_PITCH; l[0x27] = base + WORK_OFF;
	l[0x28] = l[0x29] = l[0x2c] = l[0x38] = 0;		/* IDR: no reference */
	l[0x2e] = rec + REC_COLINFO; l[0x2f] = base + SMALL_OFF; l[0x37] = rec + REC_MVINFO;
	for (i = 0x30; i <= 0x3c; i += 0x0c) {
		l[i] = base + STREAM_OFF; l[i + 1] = size; l[i + 2] = STREAM_HEAD; l[i + 3] = size - 2 * STREAM_HEAD;
	}
	if (qp >= 0) {
		l[0x03] = (l[0x03] & ~0x00ff0000u) | ((uint32_t)qp << 16);	/* field qp */
		l[0x1c] = (l[0x1c] & ~0x007f0000u) | ((uint32_t)qp << 16);	/* field sp_38 */
	}
	for (i = 0x40; i < LIST_WORDS; i++) l[i] = 0;
}

static void print_list(const char *what, const uint32_t *l, int from, int to)
{
	int i;

	printf("%s", what);
	for (i = from; i < to; i++) printf("%s%08x", (i - from) % 8 ? " " : "\n  ", l[i]);
	printf("\n");
}

int main(int argc, char **argv)
{
	int dry = 1, a = 1, qp = 30;
	const char *params = NULL, *head = NULL, *dir, *in, *out;
	static uint32_t list[LIST_WORDS];

	while (a < argc && argv[a][0] == '-') {
		if (!strcmp(argv[a], "--run")) dry = 0;
		else if (!strcmp(argv[a], "--dry")) dry = 1;
		else if (!strcmp(argv[a], "-q") && a + 1 < argc) qp = atoi(argv[++a]);
		else if (!strcmp(argv[a], "--params") && a + 1 < argc) params = argv[++a];
		else if (!strcmp(argv[a], "--head") && a + 1 < argc) head = argv[++a];
		else break;
		a++;
	}
	if (argc - a != 3 || qp < 0 || qp > 51) {
		fprintf(stderr, "usage: %s [--dry|--run] [-q 0..51] [--params params.bin] [--head slicehead.bin] LISTDIR in.nv12 out.h265\n", argv[0]);
		return 2;
	}
	dir = argv[a]; in = argv[a + 1]; out = argv[a + 2];
	if (load(dir, "list.bin", list, 0x40 * 4, 1) < 0) return 1;
	if (((list[0x03] >> 28) & 3) != 2) { fprintf(stderr, "list.bin is not an IDR list (field sp_40 = %u)\n", (list[3] >> 28) & 3); return 1; }

	size_t insz = (size_t)W * H * 3 / 2;
	uint8_t *src = malloc(insz), *pool;
	FILE *f = fopen(in, "rb");
	uint32_t base = 0x81800000u;	/* dry run */

	if (!src || !f || fread(src, 1, insz, f) != insz) { fprintf(stderr, "cannot read %zu bytes of NV12 from %s\n", insz, in); return 1; }
	fclose(f);
#ifndef H265ENC_NO_DEVICE
	int fd = -1;
	struct ak39_venc_pool_info info;

	if (!dry) {
		const char *dev = getenv("AKUIO_DEV") ? getenv("AKUIO_DEV") : "/dev/uio0";

		fd = open(dev, O_RDWR | O_SYNC);
		if (fd < 0 || ioctl(fd, AK39_VENC_POOL_INFO, &info) < 0) { perror(dev); return 1; }
		if (info.size < POOL_NEED) { fprintf(stderr, "pool too small (%u, %u needed)\n", info.size, POOL_NEED); return 1; }
		base = info.paddr;
		pool = mmap(NULL, info.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, AK39_VENC_MMAP_POOL);
		regs = mmap(NULL, info.regs_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, AK39_VENC_MMAP_REGS);
		if (pool == MAP_FAILED || regs == (void *)MAP_FAILED) { perror("mmap"); return 1; }
	} else
#endif
	{
		pool = calloc(1, POOL_NEED);
		if (!pool) return 1;
	}
	if (load(dir, "tables.bin", pool + TABLES_OFF, TABLES_SIZE, 1) < 0) return 1;
	memset(pool + WORK_OFF, 0, WORK_SIZE);
	memset(pool + SMALL_OFF, 0, SMALL_SIZE);
	if (load(dir, "work.bin", pool + WORK_OFF, WORK_SIZE, 0) < 0) return 1;
	if (load(dir, "small.bin", pool + SMALL_OFF, SMALL_SIZE, 0) < 0) return 1;
	memcpy(pool + SRC_Y_OFF, src, (size_t)W * H);
	memcpy(pool + SRC_UV_OFF, src + (size_t)W * H, (size_t)W * H / 2);
	memset(pool + REC_OFF, 0, FRAME_SIZE);
	memset(pool + STREAM_OFF, 0xa5, STREAM_ALLOC);
	patch_list(list, base, qp);
	memcpy(pool + LIST_OFF, list, sizeof list);
	print_list("list (input words):", list, 0, 0x40);
	if (dry) { printf("dry run: list at %08x, nothing touched\n", base + LIST_OFF); return 0; }
	(void)params; (void)out; (void)head;
#ifndef H265ENC_NO_DEVICE
	{
		uint32_t st[2] = { 0, 0 }, k, last = 0, written = 0, *lr = (uint32_t *)(void *)(pool + LIST_OFF);
		int w, got = 0, r;
		char name[1024];

		/* init of the core (as the vendor's start, src/jpegenc/jpeg_hw.h), then the tail of a vendor cycle (hwseq.py) */
		WR(R_IRQ_EN, 0xffffffff); WR(R_STAT_CLR, 0xffffff);
		(void)RD(R_ACK); WR(R_ACK, 1); WR(0x822c, 0);
		(void)RD(R_ACK); WR(R_ACK, 0x10000);
		WR(0x8034, 0); WR(0x8054, 0x70);
		WR(R_IRQ_EN, 0x1000007); WR(0x822c, 0);
		/* the interrupt sources: the vendor's mask is 0x4 at the first interrupt of a picture and 0x1 at the second
		 * (IPCAM2 capture, 2026-11-07); left at 0, the core finishes (status 0x18 = 1) but raises no interrupt */
		WR(R_MASK, RD(R_MASK) | (getenv("H265_MASK") ? (uint32_t)strtoul(getenv("H265_MASK"), NULL, 0) : 0x5u));
		WR(R_CLK, RD(R_CLK) | 0x8e00);
		(void)RD(R_UNK);
		WR(R_LIST, base + LIST_OFF);
		WR(R_START, 2);
		for (w = 0; w < 2; w++) {
			r = ioctl(fd, AKUIO_WAIT_IRQ, &(int){ 0 });
			st[w] = RD(R_STAT_CLR);
			printf("wait %d: %s, status 0x18 = %08x, 0x1c = %08x, 0x20 = %08x\n", w + 1, r < 0 ? strerror(errno) : "interrupt",
			       st[w], RD(R_STAT), RD(R_ACK));
			if (r < 0) break;
			got++;
			WR(R_STAT_CLR, st[w]);				/* write-1-to-clear (libakuio, 8dc2d31) */
			WR(R_MASK, RD(R_MASK));
			if (RD(R_ACK) == 0x10001) WR(R_ACK, 0x10000);
			if (st[w] & 1) break;			/* picture done: one interrupt with mask 0x5 (IPCAM2, 2026-11-07) */
		}
		(void)RD(R_STAT); (void)RD(R_ACK); WR(R_ACK, 1);
		WR(R_IRQ_EN, 0x1000007); WR(0x822c, 0);
		print_list("list after the run (status words 0x40-0x6f):", lr, 0x40, 0x70);
		for (k = 0; k < STREAM_ALLOC; k++)
			if (pool[STREAM_OFF + k] != 0xa5) { written++; last = k; }
		printf("interrupts: %d; bytes the core wrote in the stream buffer: %u, the last at +0x%x\n", got, written, last);
		snprintf(name, sizeof name, "%s.list", out);
		f = fopen(name, "wb"); if (f) { fwrite(lr, 4, LIST_WORDS, f); fclose(f); }
		snprintf(name, sizeof name, "%s.raw", out);
		f = fopen(name, "wb"); if (f) { fwrite(pool + STREAM_OFF, 1, written ? last + 1 : 0, f); fclose(f); }
		/* the picture: from the first start code after the head the core reserves, up to the last written byte */
		f = fopen(out, "wb");
		if (!f) { perror(out); return 1; }
		if (params) {
			FILE *pf = fopen(params, "rb");
			int c;

			if (!pf) { perror(params); return 1; }
			while ((c = getc(pf)) != EOF) putc(c, f);
			fclose(pf);
		}
		if (head) {
			/* the capture's finding: slice data from +0x820, its length in word 0x41 */
			FILE *hf = fopen(head, "rb");
			int c;
			uint32_t n = lr[0x41];

			if (!hf) { perror(head); return 1; }
			while ((c = getc(hf)) != EOF) putc(c, f);
			fclose(hf);
			if (n > STREAM_ALLOC - STREAM_HEAD) n = 0;
			fwrite(pool + STREAM_OFF + STREAM_HEAD, 1, n, f);
			printf("%s: header + %u bytes of slice data (word 0x41)\n", out, n);
			fclose(f);
			return n ? 0 : 1;
		}
		for (k = 0; k + 3 <= last; k++)
			if (pool[k] == 0 && pool[k + 1] == 0 && pool[k + 2] == 1) break;
		if (k > 0 && pool[k - 1] == 0) k--;
		if (written && k + 3 <= last) {
			fwrite(pool + STREAM_OFF + k, 1, last + 1 - k, f);
			printf("%s: %u bytes of NALs from +0x%x%s\n", out, last + 1 - k, k, params ? " after the parameter sets" : "");
		} else
			printf("no start code in the written bytes: see %s.raw\n", out);
		fclose(f);
	}
#endif
	return 0;
}
