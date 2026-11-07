/*
 * h265live: a short H.265 stream encoded by the AK3918EV300 core WITHOUT the vendor control software, straight from
 * the ISP (step 3 of the free encoder, 2026-11-07): one IDR then P pictures, each referencing the previous one,
 * at a fixed QP, with our own slice headers.
 *
 *   h265live [-n FRAMES] [-q QP] [-b KBPS] [-s SKIP] [-g GOP] LISTDIR out.h265
 *
 *   Nothing captured is needed any more (an empty LISTDIR): our lists (listgen.h), parameter sets (paramsets.h),
 *   slice headers (slicehdr.h) and side buffers (TABLES_HEAD, zeros). The capture's files, when LISTDIR has them,
 *   replace ours (tables.bin, work.bin, small.bin; list.bin + plist.bin with H265_VENDOR_LISTS=1, params.bin with
 *   H265_VENDOR_PARAMS=1), for comparisons.
 *
 *   LISTDIR  from `capture.py DIR --out LISTDIR`: list.bin (an IDR list of the vendor encoder, its 64 input words),
 *            plist.bin (the P list of cmdlist.build_list for the same buffers), tables.bin, small.bin, work.bin
 *            (params.bin, the vendor's VPS/SPS/PPS, only with H265_VENDOR_PARAMS=1: ours are paramsets.h).
 *            Data read from the camera's vendor encoder: never in git.
 *   -n       pictures to encode (default 50), -q QP (default 32), -s pictures skipped first while the ISP settles
 *            (default 15), -g an IDR every GOP pictures (default 0: only the first; 50 with -b)
 *   -b       target bit rate in kbit/s at 25 fps: one QP per picture (rc.h), -q is then the first one
 *
 * tc100_rtsp must be stopped (it owns the ISP and the encoder): test cameras only (v3/dev/h265-step2.sh live).
 * The source is the ISP's capture buffer itself (AK39_VI_G_PHYS gives its physical address, as tc100_rtsp's direct
 * capture): no copy. Two frame buffers in the encoder pool take turns as the reconstruction and the reference.
 *
 * What the captures of 2026-11-07 showed (README.md): the core writes only the slice data, from stream +0x820, its
 * length in list word 0x41; the software writes the NAL header and the slice header; the vendor counts POC 2 per
 * picture (log2_max_poc_lsb 10), one reference (delta POC -2, used), temporal MVP on, loop filter across slices on.
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
#include <sys/time.h>
#include <unistd.h>
#ifndef H265LIVE_NO_DEVICE
#include <linux/videodev2.h>
#endif

#include "slicehdr.h"
#include "rc.h"
#include <string.h>
#include "paramsets.h"
#include "listgen.h"
#include "worktab.h"

#ifndef H265LIVE_NO_DEVICE
#include "../libakuio/ak39_venc.h"
#endif

#define W 1920
#define H 1080
#define LIST_WORDS 112

/* pool layout (offsets): stream buffer, side buffers, list, two frame buffers (cmdlist.FRAME_PLANE_OFFSETS) */
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
#define FRAME0_OFF	0x100000u
#define FRAME_SIZE	0x340000u
#define POOL_NEED	(FRAME0_OFF + 2 * FRAME_SIZE)
#define F_UV		0x1fe000u
#define F_MVINFO	0x2fd000u
#define F_COLINFO	0x300400u
#define SRC_STRIDE	1920u
#define REC_PITCH	0x1e00u

#define R_IRQ_EN	0x8010
#define R_MASK		0x8014
#define R_STAT_CLR	0x8018
#define R_STAT		0x801c
#define R_ACK		0x8020
#define R_LIST		0x8080
#define R_START		0x8084
#define R_UNK		0x8300
#define R_CLK		0xc004

/* The 0x4040-byte "tables" buffer of list word 0x23: on IPCAM2 (2026-11-07) only its first 32 bytes are not zero, the
 * same for every picture of the main stream; read as little-endian 16-bit values 2500 1000 256 5000 7000 9000 ...
 * (thresholds of the core's own decisions, meaning not known), except byte 19: 0x24 for an IDR, 0x30 for a P picture
 * (the same for every P picture whatever its QP). Used when LISTDIR has no tables.bin. */
#define TABLES_TYPE_BYTE 19
static const uint8_t TABLES_HEAD[32] __attribute__((unused)) = { 0xc4, 0x09, 0xe8, 0x03, 0x00, 0x01, 0x88, 0x13, 0x58, 0x1b, 0x28, 0x23, 0x01, 0x03, 0x0a, 0x01, 0x02, 0x03, 0x19, 0x24, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 };

/* the list words that change between pictures, as cmdlist.build_list sets them (tests/test_h265cmdlist.py checks
 * h265live --dry against it) */
void h265_list_set(uint32_t *l, uint32_t base, uint32_t src_y, uint32_t src_uv, int cur, int idr, int qp, uint32_t poc)
{
	uint32_t size = STREAM_ALLOC - 0x200, rec = base + FRAME0_OFF + (uint32_t)cur * FRAME_SIZE,
		 ref = base + FRAME0_OFF + (uint32_t)(cur ^ 1) * FRAME_SIZE;
	int i;

	l[0x20] = src_y; l[0x21] = src_uv; l[0x22] = SRC_STRIDE;
	l[0x23] = base + TABLES_OFF;
	l[0x24] = rec; l[0x25] = rec + F_UV; l[0x26] = REC_PITCH; l[0x27] = base + WORK_OFF;
	l[0x2e] = rec + F_COLINFO; l[0x2f] = base + SMALL_OFF; l[0x37] = rec + F_MVINFO;
	if (idr) l[0x28] = l[0x29] = l[0x2c] = l[0x38] = 0;
	else { l[0x28] = ref; l[0x29] = ref + F_UV; l[0x2c] = ref + F_COLINFO; l[0x38] = ref + F_MVINFO; }
	for (i = 0x30; i <= 0x3c; i += 0x0c) {
		l[i] = base + STREAM_OFF; l[i + 1] = size; l[i + 2] = STREAM_HEAD; l[i + 3] = size - 2 * STREAM_HEAD;
	}
	l[0x03] = (l[0x03] & ~0x00ff0000u) | ((uint32_t)qp << 16);	/* qp */
	l[0x1c] = (l[0x1c] & ~0x007f0000u) | ((uint32_t)qp << 16);	/* sp_38 */
	l[0x0c] = poc; l[0x0d] = poc >= 2 ? poc - 2 : 0; l[0x0f] = poc >= 2 ? poc - 2 : 0;	/* sp_98 sp_9c sp_ac */
	l[0x10] = poc >= 4 ? poc - 4 : 0xffffffffu;				/* sp_b4 */
	for (i = 0x40; i < LIST_WORDS; i++) l[i] = 0;
}

/* a whole list from our own tables (listgen.h, generated from cmdlist.py): no capture needed */
void h265_list_build(uint32_t *l, uint32_t base, uint32_t src_y, uint32_t src_uv, int cur, int idr, int qp, uint32_t poc)
{
	memcpy(l, idr ? LISTGEN_IDR : LISTGEN_P, sizeof LISTGEN_IDR);
	memset(l + 32, 0, (LIST_WORDS - 32) * 4);
	h265_list_set(l, base, src_y, src_uv, cur, idr, qp, poc);
}

static int load(const char *dir, const char *name, void *dst, size_t n, int need)
{
	char p[1024];
	FILE *f;
	size_t got;

	snprintf(p, sizeof p, "%s/%s", dir, name);
	if (!(f = fopen(p, "rb"))) {
		if (need) fprintf(stderr, "cannot open %s: %s\n", p, strerror(errno));
		return need ? -1 : 0;
	}
	got = fread(dst, 1, n, f);
	fclose(f);
	if (got != n) { fprintf(stderr, "%s: %zu bytes, %zu expected\n", p, got, n); return -1; }
	return (int)got;
}

#ifndef H265LIVE_NO_DEVICE
static volatile uint32_t *regs;
#define RD(o)	(regs[(o) / 4])
#define WR(o, v) (regs[(o) / 4] = (v))

struct ak39_vi_phys { uint32_t index, phys_y, phys_uv, size; };
#define AK39_VI_G_PHYS _IOWR('V', BASE_VIDIOC_PRIVATE + 0, struct ak39_vi_phys)

static double now_ms(void)
{
	struct timeval tv;

	gettimeofday(&tv, NULL);
	return tv.tv_sec * 1000.0 + tv.tv_usec / 1000.0;
}

/* one picture on the core; 0 and the slice data length in *len, or -1 */
static int encode(int fd, uint32_t list_paddr, const uint32_t *lr, uint32_t *len)
{
	uint32_t st;
	int r;

	WR(R_IRQ_EN, 0x1000007); WR(0x822c, 0);
	WR(R_MASK, RD(R_MASK) | 0x5u);
	WR(R_CLK, RD(R_CLK) | 0x8e00);
	(void)RD(R_UNK);
	WR(R_LIST, list_paddr);
	WR(R_START, 2);
	r = ioctl(fd, AKUIO_WAIT_IRQ, &(int){ 0 });
	st = RD(R_STAT_CLR);
	WR(R_STAT_CLR, st);
	WR(R_MASK, RD(R_MASK));
	if (RD(R_ACK) == 0x10001) WR(R_ACK, 0x10000);
	(void)RD(R_STAT); (void)RD(R_ACK); WR(R_ACK, 1);
	if (r < 0 || !(st & 1)) { fprintf(stderr, "encoder: %s, status %08x\n", r < 0 ? strerror(errno) : "no end", st); return -1; }
	*len = lr[0x41];
	return *len && *len <= STREAM_ALLOC - STREAM_HEAD ? 0 : -1;
}
#endif

int main(int argc, char **argv)
{
	int a = 1, n = 50, qp = 32, skip = 15, gop = -1, dry = 0, kbps = 0, vlists = 0;
	struct rc rcs;
	static uint32_t ilist[LIST_WORDS], plist[LIST_WORDS];
	static uint8_t params[4096];
	int plen;

	while (a < argc && argv[a][0] == '-') {
		if (!strcmp(argv[a], "--dry")) dry = 1;
		else if (a + 1 < argc && !strcmp(argv[a], "-n")) n = atoi(argv[++a]);
		else if (a + 1 < argc && !strcmp(argv[a], "-q")) qp = atoi(argv[++a]);
		else if (a + 1 < argc && !strcmp(argv[a], "-s")) skip = atoi(argv[++a]);
		else if (a + 1 < argc && !strcmp(argv[a], "-g")) gop = atoi(argv[++a]);
		else if (a + 1 < argc && !strcmp(argv[a], "-b")) kbps = atoi(argv[++a]);
		else break;
		a++;
	}
	if (argc - a != 2 || qp < 0 || qp > 51 || n < 1) {
		fprintf(stderr, "usage: %s [--dry] [-n FRAMES] [-q QP] [-b KBPS] [-s SKIP] [-g GOP] LISTDIR out.h265\n", argv[0]);
		return 2;
	}
	const char *dir = argv[a], *out = argv[a + 1];

	if (gop < 0) gop = kbps > 0 ? 50 : 0;
	rc_init(&rcs, kbps > 0 ? kbps : 1, 25, 20, 51, qp);

	/* our lists (listgen.h); H265_VENDOR_LISTS=1: the capture's list.bin and plist.bin as templates */
	vlists = getenv("H265_VENDOR_LISTS") && getenv("H265_VENDOR_LISTS")[0] == '1';
	if (vlists) {
		if (load(dir, "list.bin", ilist, 0x40 * 4, 1) < 0 || load(dir, "plist.bin", plist, 0x40 * 4, 1) < 0) return 1;
		if (((ilist[3] >> 28) & 3) != 2 || ((plist[3] >> 28) & 3) != 1) { fprintf(stderr, "list.bin must be an IDR list, plist.bin a P list\n"); return 1; }
	}
	/* our VPS/SPS/PPS (paramsets.h: the same bytes as the vendor's); H265_VENDOR_PARAMS=1: params.bin of the capture */
	if (getenv("H265_VENDOR_PARAMS") && getenv("H265_VENDOR_PARAMS")[0] == '1') {
		FILE *pf;
		char p[1024];

		snprintf(p, sizeof p, "%s/params.bin", dir);
		if (!(pf = fopen(p, "rb"))) { fprintf(stderr, "no %s\n", p); return 1; }
		plen = (int)fread(params, 1, sizeof params, pf);
		fclose(pf);
	} else if ((plen = h265_param_sets(params, sizeof params, W, H, 25)) < 0) {
		fprintf(stderr, "parameter sets: no room\n"); return 1;
	}
	if (dry) {
		/* the lists of the first three pictures and their slice headers, for the tests */
		static uint32_t l[LIST_WORDS];
		uint8_t hb[64];
		int k, i, hl;

		for (k = 0; k < 3; k++) {
			int idr = k == 0;

			if (vlists) {
				memcpy(l, idr ? ilist : plist, sizeof l);
				h265_list_set(l, 0x81800000u, 0x82d00000u, 0x82d00000u + W * H, k & 1, idr, qp, (uint32_t)(2 * k));
			} else
				h265_list_build(l, 0x81800000u, 0x82d00000u, 0x82d00000u + W * H, k & 1, idr, qp, (uint32_t)(2 * k));
			printf("picture %d list:", k);
			for (i = 0; i < 0x40; i++) printf(" %08x", l[i]);
			hl = h265_slice_nal(hb, sizeof hb, idr, qp, (uint32_t)(2 * k));
			printf("\npicture %d head:", k);
			for (i = 0; i < hl; i++) printf(" %02x", hb[i]);
			printf("\n");
		}
		return 0;
	}
#ifdef H265LIVE_NO_DEVICE
	fprintf(stderr, "built without the device: --dry only\n");
	(void)out; (void)n; (void)skip; (void)gop; (void)plen; (void)rcs;
	return 2;
#else
	{
		struct ak39_venc_pool_info info;
		const char *dev = getenv("AKUIO_DEV") ? getenv("AKUIO_DEV") : "/dev/uio0";
		int fd = open(dev, O_RDWR | O_SYNC), vfd, k, cur = 0, frame = 0, bad = 0;
		uint8_t *pool;
		struct v4l2_format fmt;
		struct v4l2_requestbuffers rq;
		struct ak39_vi_phys ph[4];
		enum v4l2_buf_type bt = V4L2_BUF_TYPE_VIDEO_CAPTURE;
		FILE *f;
		uint32_t total = 0, *lr;
		int vtables;
		double t0, tenc = 0;

		if (fd < 0 || ioctl(fd, AK39_VENC_POOL_INFO, &info) < 0) { perror(dev); return 1; }
		if (info.size < POOL_NEED) { fprintf(stderr, "pool too small (%u, %u needed)\n", info.size, POOL_NEED); return 1; }
		pool = mmap(NULL, info.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, AK39_VENC_MMAP_POOL);
		regs = mmap(NULL, info.regs_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, AK39_VENC_MMAP_REGS);
		if (pool == MAP_FAILED || regs == (void *)MAP_FAILED) { perror("mmap"); return 1; }
		/* the side buffers: ours (TABLES_HEAD, zeros) unless LISTDIR holds the capture's */
		memset(pool + TABLES_OFF, 0, TABLES_SIZE);
		memcpy(pool + TABLES_OFF, TABLES_HEAD, sizeof TABLES_HEAD);
		if ((vtables = load(dir, "tables.bin", pool + TABLES_OFF, TABLES_SIZE, 0)) < 0) return 1;
		h265_work_table(pool + WORK_OFF);		/* worktab.h: the vendor's content, computed */
		memset(pool + SMALL_OFF, 0, SMALL_SIZE);
		if (load(dir, "work.bin", pool + WORK_OFF, WORK_SIZE, 0) < 0 || load(dir, "small.bin", pool + SMALL_OFF, SMALL_SIZE, 0) < 0) return 1;
		memset(pool + FRAME0_OFF, 0, 2 * FRAME_SIZE);
		lr = (uint32_t *)(void *)(pool + LIST_OFF);

		/* the capture, as tc100_rtsp: NV12 1920x1080, mmap buffers whose physical address the driver gives */
		vfd = open(getenv("H265_VIDEO") ? getenv("H265_VIDEO") : "/dev/video0", O_RDWR);
		if (vfd < 0) { perror("video"); return 1; }
		memset(&fmt, 0, sizeof fmt);
		fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
		fmt.fmt.pix.width = W; fmt.fmt.pix.height = H;
		fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_NV12; fmt.fmt.pix.field = V4L2_FIELD_NONE;
		if (ioctl(vfd, VIDIOC_S_FMT, &fmt) < 0) { perror("S_FMT"); return 1; }
		memset(&rq, 0, sizeof rq);
		rq.count = 2; rq.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; rq.memory = V4L2_MEMORY_MMAP;
		if (ioctl(vfd, VIDIOC_REQBUFS, &rq) < 0 || rq.count < 1 || rq.count > 4) { perror("REQBUFS"); return 1; }
		for (k = 0; k < (int)rq.count; k++) {
			struct v4l2_buffer b;

			memset(&b, 0, sizeof b);
			b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; b.memory = V4L2_MEMORY_MMAP; b.index = (unsigned)k;
			ph[k].index = (unsigned)k; ph[k].phys_y = ph[k].phys_uv = ph[k].size = 0;
			if (ioctl(vfd, VIDIOC_QUERYBUF, &b) < 0 || ioctl(vfd, AK39_VI_G_PHYS, &ph[k]) < 0 || !ph[k].phys_y) {
				fprintf(stderr, "buffer %d: no physical address (AK39_VI_G_PHYS: %s)\n", k, strerror(errno)); return 1;
			}
			printf("capture buffer %d: Y %08x UV %08x (%u bytes)\n", k, ph[k].phys_y, ph[k].phys_uv, ph[k].size);
			if (ioctl(vfd, VIDIOC_QBUF, &b) < 0) { perror("QBUF"); return 1; }
		}
		if (ioctl(vfd, VIDIOC_STREAMON, &bt) < 0) { perror("STREAMON"); return 1; }
		if (!(f = fopen(out, "wb"))) { perror(out); return 1; }
		/* init of the core, as the vendor's start (src/jpegenc/jpeg_hw.h) */
		WR(R_IRQ_EN, 0xffffffff); WR(R_STAT_CLR, 0xffffff);
		(void)RD(R_ACK); WR(R_ACK, 1); WR(0x822c, 0);
		(void)RD(R_ACK); WR(R_ACK, 0x10000);
		WR(0x8034, 0); WR(0x8054, 0x70);
		t0 = now_ms();
		for (k = 0; frame < n && k < n + skip + 50; k++) {
			struct v4l2_buffer b;
			uint32_t len = 0;
			int idr = frame == 0 || (gop > 0 && frame % gop == 0), last_idr = gop > 0 ? frame - frame % gop : 0;
			uint32_t poc = (uint32_t)(2 * (frame - last_idr));
			uint8_t hb[64];
			int hl, q = kbps > 0 ? rc_qp(&rcs, idr) : qp;
			double te;

			memset(&b, 0, sizeof b);
			b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; b.memory = V4L2_MEMORY_MMAP;
			if (ioctl(vfd, VIDIOC_DQBUF, &b) < 0) { perror("DQBUF"); break; }
			if (k < skip || b.index >= rq.count) { ioctl(vfd, VIDIOC_QBUF, &b); continue; }
			{
				uint32_t sy = ph[b.index].phys_y, suv = ph[b.index].phys_uv ? ph[b.index].phys_uv : sy + W * H;

				if (vlists) {
					memcpy(lr, idr ? ilist : plist, 0x40 * 4);
					h265_list_set(lr, info.paddr, sy, suv, cur, idr, q, poc);
				} else
					h265_list_build(lr, info.paddr, sy, suv, cur, idr, q, poc);
			}
			if (!vtables) pool[TABLES_OFF + TABLES_TYPE_BYTE] = idr ? 0x24 : 0x30;
			if (frame == 0 || idr) fwrite(params, 1, (size_t)plen, f);
			te = now_ms();
			if (encode(fd, info.paddr + LIST_OFF, lr, &len) < 0) { bad++; ioctl(vfd, VIDIOC_QBUF, &b); if (bad > 3) break; continue; }
			tenc += now_ms() - te;
			ioctl(vfd, VIDIOC_QBUF, &b);
			hl = h265_slice_nal(hb, sizeof hb, idr, q, poc);
			if (kbps > 0) rc_done(&rcs, idr, q, (int64_t)hl + len);
			fwrite(hb, 1, (size_t)hl, f);
			fwrite(pool + STREAM_OFF + STREAM_HEAD, 1, len, f);
			printf("picture %3d %s poc %3u qp %2d: %6u bytes\n", frame, idr ? "IDR" : "P  ", poc, q, hl + len);
			total += (uint32_t)hl + len;
			cur ^= 1;
			frame++;
		}
		ioctl(vfd, VIDIOC_STREAMOFF, &bt);
		close(vfd);
		fclose(f);
		WR(R_IRQ_EN, 0x1000007); WR(0x822c, 0);
		printf("%d pictures, %u bytes (%.0f kbit/s at 25 fps), %.1f ms per picture on the core, %.1f s in all, %d failed\n",
		       frame, total, frame ? total * 8.0 / frame * 25 / 1000 : 0, frame ? tenc / frame : 0, (now_ms() - t0) / 1000, bad);
		return frame == n && !bad ? 0 : 1;
	}
#endif
}
