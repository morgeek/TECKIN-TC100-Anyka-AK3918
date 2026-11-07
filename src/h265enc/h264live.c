/*
 * h264live: a short H.264 640x360 stream (the sub stream) encoded by the AK3918EV300 core WITHOUT the vendor control
 * software, from the ISP's sub channel (2026-11-07): one IDR then P pictures, each referencing the previous one, with
 * our own lists (listgen.h), SPS / PPS / slice headers (avc.h) and side buffers (h264_work_table, tables head).
 *
 *   h264live [--dry] [-n FRAMES] [-q QP] [-b KBPS] [-s SKIP] [-g GOP] out.h264
 *
 *   -n pictures (default 50), -q QP (default 32; with -b the first one), -b target kbit/s at 25 fps (rc.h; also the
 *   SPS's HRD bit rate, default 250), -s pictures skipped first while the ISP settles (default 15), -g an IDR every GOP
 *   pictures (default 0: only the first; 50 with -b). H264_D8=<hex>: list word 0x1f (sp_d8, default 0; the vendor's
 *   changes with every picture).
 *
 * tc100_rtsp must be stopped (it owns the ISP and the encoder): test cameras only (v3/dev/h265-step2.sh live264).
 * The kernel's ISP sub channel (ak39_vi.sub_channel, on by default) puts the 640x360 NV12 picture right after the
 * 1920x1080 one in each capture buffer: the core reads it there (AK39_VI_G_PHYS gives the physical address).
 *
 * What the captures of 2026-11-07 showed (cmdlist.py PROFILE_H264_360P): the same core and list layout as H.265,
 * slice_type_c = 0, macroblock counts instead of CTB counts, the stream buffer in list words 0x3c-0x3f only, the
 * work buffer with the rate-distortion weights only, the tables head with byte 18 = 0x1f for an IDR (0x19 for a P
 * picture, as H.265); the core writes the CABAC slice data from stream + 0x820, its length in list word 0x41.
 * The start differs from H.265 (src/h265enc/venctrace, the vendor library's register accesses): see encode().
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
#include "../libakuio/ak39_venc.h"
#endif

#include "avc.h"
#include "rc.h"
#include "listgen.h"
#include "worktab.h"

#define W 640
#define H 360
#define MAIN_W 1920
#define MAIN_H 1080
#define LIST_WORDS 112

/* pool layout (offsets) */
#define STREAM_OFF	0x000000u
#define STREAM_ALLOC	0xdf80u		/* the vendor's */
#define STREAM_HEAD	0x820u
#define TABLES_OFF	0x020000u
#define TABLES_SIZE	0x4040u
#define WORK_OFF	0x028000u
#define WORK_SIZE	0x6400u
#define SMALL_OFF	0x02f000u
#define SMALL_SIZE	0x100u
#define LIST_OFF	0x02f400u
#define FRAME0_OFF	0x040000u
#define FRAME_SIZE	0x080000u	/* Y (tiled, pitch 0xa00: 0x3c000), UV, motion info (0x1240), co-located info */
#define POOL_NEED	(FRAME0_OFF + 2 * FRAME_SIZE)
#define F_UV		0x040000u
#define F_MVINFO	0x060000u
#define F_COLINFO	0x062000u
#define SRC_STRIDE	640u
#define REC_PITCH	0xa00u

#define R_IRQ_EN	0x8010
#define R_MASK		0x8014
#define R_STAT_CLR	0x8018
#define R_STAT		0x801c
#define R_ACK		0x8020
#define R_LIST		0x8080
#define R_START		0x8084
#define R_UNK		0x8300
#define R_CLK		0xc004

/* the tables buffer: the H.265 head (h265live.c), bytes 18-19 = 0x1f 0x24 for an IDR, 0x19 0x30 for a P picture */
static const uint8_t TABLES_HEAD[32] __attribute__((unused)) = { 0xc4, 0x09, 0xe8, 0x03, 0x00, 0x01, 0x88, 0x13, 0x58, 0x1b, 0x28, 0x23, 0x01, 0x03, 0x0a, 0x01, 0x02, 0x03, 0x19, 0x30 };

void h264_list_build(uint32_t *l, uint32_t base, uint32_t src_y, uint32_t src_uv, int cur, int idr, int qp,
		     uint32_t poc, uint32_t d8)
{
	uint32_t rec = base + FRAME0_OFF + (uint32_t)cur * FRAME_SIZE, ref = base + FRAME0_OFF + (uint32_t)(cur ^ 1) * FRAME_SIZE;
	int i;

	memcpy(l, idr ? LISTGEN_H264_IDR : LISTGEN_H264_P, sizeof LISTGEN_H264_IDR);
	for (i = 32; i < LIST_WORDS; i++) l[i] = 0;
	l[0x20] = src_y; l[0x21] = src_uv; l[0x22] = SRC_STRIDE;
	l[0x23] = base + TABLES_OFF;
	l[0x24] = rec; l[0x25] = rec + F_UV; l[0x26] = REC_PITCH; l[0x27] = base + WORK_OFF;
	l[0x2e] = rec + F_COLINFO; l[0x2f] = base + SMALL_OFF; l[0x37] = rec + F_MVINFO;
	if (!idr) { l[0x28] = ref; l[0x29] = ref + F_UV; l[0x2c] = ref + F_COLINFO; l[0x38] = ref + F_MVINFO; }
	l[0x3c] = base + STREAM_OFF; l[0x3d] = STREAM_ALLOC; l[0x3e] = STREAM_HEAD; l[0x3f] = STREAM_ALLOC - 2 * STREAM_HEAD;
	l[0x03] = (l[0x03] & ~0x00ff0000u) | ((uint32_t)qp << 16);		/* qp */
	l[0x1c] = (l[0x1c] & ~0x007f0000u) | ((uint32_t)qp << 16);		/* sp_38 */
	l[0x1b] = (l[0x1b] & ~0x03ff0000u) | ((uint32_t)(qp + 32 >= 60 ? 10 : (qp + 32) / 6) << 16);	/* sp_8c */
	l[0x1f] = d8;								/* sp_d8 */
	l[0x0c] = poc; l[0x0d] = poc >= 2 ? poc - 2 : 0; l[0x0f] = poc >= 2 ? poc - 2 : 0;	/* sp_98 sp_9c sp_ac */
	l[0x10] = poc >= 4 ? poc - 4 : 0xffffffffu;				/* sp_b4 */
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

/* one picture, the vendor's H.264 sequence (venctrace of 2026-11-07): interrupt mask bit 2 (bit 0 is H.265's), clock
 * register bit 15 clear (H.265 sets it), the list address then 2 (the core loads the list), the address again then 8
 * (H.264 encodes it); after the interrupt the mask is cleared. 0 and the slice data length in *len, or -1 */
static int encode(int fd, uint32_t list_paddr, const uint32_t *lr, uint32_t *len)
{
	uint32_t st;
	int r;

	WR(R_IRQ_EN, 0x1000007); WR(0x822c, 0);
	WR(R_MASK, (RD(R_MASK) & ~0x5u) | 0x4u);
	WR(R_CLK, (RD(R_CLK) & ~0x8000u) | 0x0e00);
	(void)RD(R_UNK); (void)RD(R_UNK);
	WR(R_LIST, list_paddr);
	WR(R_START, 2);
	WR(R_LIST, list_paddr);
	WR(R_START, 8);
	r = ioctl(fd, AKUIO_WAIT_IRQ, &(int){ 0 });
	st = RD(R_STAT_CLR);
	WR(R_STAT_CLR, st);
	WR(R_MASK, RD(R_MASK));
	WR(R_MASK, RD(R_MASK) & ~0x4u);
	if (RD(R_ACK) == 0x10001) WR(R_ACK, 0x10000);
	(void)RD(R_STAT); (void)RD(R_ACK); WR(R_ACK, 1);
	if (getenv("H264_DEBUG"))
		fprintf(stderr, "after the wait: r %d status %08x, 8300 %08x, list 40-41 %08x %08x\n", r, st, RD(R_UNK), lr[0x40], lr[0x41]);
	if (r < 0) { fprintf(stderr, "encoder: %s, status %08x\n", strerror(errno), st); return -1; }
	*len = lr[0x41];
	return *len && *len <= STREAM_ALLOC - 2 * STREAM_HEAD ? 0 : -1;
}
#endif

int main(int argc, char **argv)
{
	int a = 1, n = 50, qp = 32, skip = 15, gop = -1, dry = 0, kbps = 0;
	uint32_t d8 = getenv("H264_D8") ? (uint32_t)strtoul(getenv("H264_D8"), NULL, 16) : 0;
	struct rc rcs;
	static uint8_t params[512];
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
	if (argc - a != 1 || qp < 0 || qp > 51 || n < 1) {
		fprintf(stderr, "usage: %s [--dry] [-n FRAMES] [-q QP] [-b KBPS] [-s SKIP] [-g GOP] out.h264\n", argv[0]);
		return 2;
	}
	const char *out = argv[a];

	if (gop < 0) gop = kbps > 0 ? 50 : 0;
	rc_init(&rcs, kbps > 0 ? kbps : 1, 25, 20, 51, qp);
	if ((plen = h264_param_sets(params, sizeof params, W, H, 25, kbps > 0 ? (uint32_t)kbps : 250)) < 0) {
		fprintf(stderr, "parameter sets: no room\n"); return 1;
	}
	if (dry) {
		/* the parameter sets, then the lists and slice headers of the first three pictures, for the tests */
		static uint32_t l[LIST_WORDS];
		uint8_t hb[64];
		int k, i, hl;

		printf("params:");
		for (i = 0; i < plen; i++) printf(" %02x", params[i]);
		printf("\n");
		for (k = 0; k < 3; k++) {
			h264_list_build(l, 0x81800000u, 0x835f7600u, 0x835f7600u + W * H, k & 1, k == 0, qp, (uint32_t)(2 * k), d8);
			printf("picture %d list:", k);
			for (i = 0; i < 0x40; i++) printf(" %08x", l[i]);
			hl = h264_slice_nal(hb, sizeof hb, k == 0, qp, (uint32_t)k, 0);
			printf("\npicture %d head:", k);
			for (i = 0; i < hl; i++) printf(" %02x", hb[i]);
			printf("\n");
		}
		return 0;
	}
#ifdef H265LIVE_NO_DEVICE
	fprintf(stderr, "built without the device: --dry only\n");
	(void)out; (void)n; (void)skip; (void)gop; (void)rcs;
	return 2;
#else
	{
		struct ak39_venc_pool_info info;
		const char *dev = getenv("AKUIO_DEV") ? getenv("AKUIO_DEV") : "/dev/uio0";
		int fd = open(dev, O_RDWR | O_SYNC), vfd, k, cur = 0, frame = 0, bad = 0, idrs = 0, last_idr = 0;
		uint8_t *pool;
		struct v4l2_format fmt;
		struct v4l2_requestbuffers rq;
		struct ak39_vi_phys ph[4];
		enum v4l2_buf_type bt = V4L2_BUF_TYPE_VIDEO_CAPTURE;
		FILE *f;
		uint32_t total = 0, *lr, main_len = MAIN_W * MAIN_H * 3 / 2;
		double t0, tenc = 0;

		if (fd < 0 || ioctl(fd, AK39_VENC_POOL_INFO, &info) < 0) { perror(dev); return 1; }
		if (info.size < POOL_NEED) { fprintf(stderr, "pool too small (%u, %u needed)\n", info.size, POOL_NEED); return 1; }
		pool = mmap(NULL, info.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, AK39_VENC_MMAP_POOL);
		regs = mmap(NULL, info.regs_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, AK39_VENC_MMAP_REGS);
		if (pool == MAP_FAILED || regs == (void *)MAP_FAILED) { perror("mmap"); return 1; }
		memset(pool + TABLES_OFF, 0, TABLES_SIZE);
		memcpy(pool + TABLES_OFF, TABLES_HEAD, sizeof TABLES_HEAD);
		h264_work_table(pool + WORK_OFF);
		memset(pool + SMALL_OFF, 0, SMALL_SIZE);
		memset(pool + FRAME0_OFF, 0, 2 * FRAME_SIZE);
		lr = (uint32_t *)(void *)(pool + LIST_OFF);

		vfd = open(getenv("H265_VIDEO") ? getenv("H265_VIDEO") : "/dev/video0", O_RDWR);
		if (vfd < 0) { perror("video"); return 1; }
		memset(&fmt, 0, sizeof fmt);
		fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
		fmt.fmt.pix.width = MAIN_W; fmt.fmt.pix.height = MAIN_H;
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
			printf("capture buffer %d: Y %08x (%u bytes, %u in the V4L2 buffer)\n", k, ph[k].phys_y, ph[k].size, b.length);
			if (ph[k].size < main_len + W * H * 3 / 2 && b.length < main_len + W * H * 3 / 2) {
				fprintf(stderr, "buffer %d has no room for the sub picture: is the ISP sub channel on (ak39_vi.sub_channel)?\n", k);
				return 1;
			}
			if (ioctl(vfd, VIDIOC_QBUF, &b) < 0) { perror("QBUF"); return 1; }
		}
		if (ioctl(vfd, VIDIOC_STREAMON, &bt) < 0) { perror("STREAMON"); return 1; }
		if (!(f = fopen(out, "wb"))) { perror(out); return 1; }
		WR(R_IRQ_EN, 0xffffffff); WR(R_STAT_CLR, 0xffffff);
		(void)RD(R_ACK); WR(R_ACK, 1); WR(0x822c, 0);
		(void)RD(R_ACK); WR(R_ACK, 0x10000);
		WR(0x8034, 0); WR(0x8054, 0x70);
		t0 = now_ms();
		for (k = 0; frame < n && k < n + skip + 50; k++) {
			struct v4l2_buffer b;
			uint32_t len = 0, fr;
			int idr = frame == 0 || (gop > 0 && frame % gop == 0);
			uint8_t hb[64];
			int hl, q;
			double te;

			if (idr) last_idr = frame;
			fr = (uint32_t)(frame - last_idr);
			q = kbps > 0 ? rc_qp(&rcs, idr) : qp;
			memset(&b, 0, sizeof b);
			b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; b.memory = V4L2_MEMORY_MMAP;
			if (ioctl(vfd, VIDIOC_DQBUF, &b) < 0) { perror("DQBUF"); break; }
			if (k < skip || b.index >= rq.count) { ioctl(vfd, VIDIOC_QBUF, &b); continue; }
			{
				uint32_t sy = ph[b.index].phys_y + main_len;

				h264_list_build(lr, info.paddr, sy, sy + W * H, cur, idr, q, 2 * fr, d8);
			}
			pool[TABLES_OFF + 18] = idr ? 0x1f : 0x19;
			pool[TABLES_OFF + 19] = idr ? 0x24 : 0x30;
			if (idr) fwrite(params, 1, (size_t)plen, f);
			te = now_ms();
			if (encode(fd, info.paddr + LIST_OFF, lr, &len) < 0) { bad++; ioctl(vfd, VIDIOC_QBUF, &b); if (bad > 3) break; continue; }
			tenc += now_ms() - te;
			ioctl(vfd, VIDIOC_QBUF, &b);
			hl = h264_slice_nal(hb, sizeof hb, idr, q, fr, (uint32_t)(idrs & 1));
			if (idr) idrs++;
			if (kbps > 0) rc_done(&rcs, idr, q, (int64_t)hl + len);
			fwrite(hb, 1, (size_t)hl, f);
			fwrite(pool + STREAM_OFF + STREAM_HEAD, 1, len, f);
			printf("picture %3d %s frame %2u qp %2d: %6u bytes\n", frame, idr ? "IDR" : "P  ", fr & 15, q, hl + len);
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
