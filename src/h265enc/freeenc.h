/*
 * freeenc.h: the free encoder as a library for tc100_rtsp (2026-11-07): H.265 1920x1080 (the main stream) and H.264
 * 640x360 (the sub stream) on the AK3918EV300 core without the vendor's libraries or data. What h265live.c and
 * h264live.c proved on IPCAM2, without their test switches:
 *   lists      listgen.h (generated from cmdlist.py), the per-picture words set here (addresses, QP, POC)
 *   headers    paramsets.h + slicehdr.h (H.265), avc.h (H.264): the vendor's bytes
 *   buffers    worktab.h (work), the tables head, zeros; two frame buffers take turns as reconstruction / reference
 *   start      H.265: mask bit 0 (bit 2 clear: set, the core hangs after an H.264 picture), clock bit 15 set,
 *              0x8084 = 2; H.264: mask bit 2 (bit 0 clear), clock bit 15 clear, 2 then 8 (venctrace)
 *   recovery   no interrupt: the core is reset (fe_hw_init), the picture is lost
 *   rate       rc.h, one QP per picture
 * The caller gives the register window and libakuio's pool calls (struct fe_env), and the physical address of each
 * NV12 picture (Y then UV right after it, as in the capture buffers). One encoder picture at a time: tc100_rtsp
 * encodes the main and sub pictures and the JPEGs one after the other in its capture loop.
 *
 * The output of a picture is in place, no copy: the core writes the slice data from stream + 0x820, and the start
 * code, the parameter sets (IDR) and the slice header are written right before it, so data .. data + len is one
 * Annex B access unit. It stays valid until the next fe_encode on the same encoder.
 *
 * FE_HOST_TEST: tests/test_h265cmdlist.py FreeEnc builds src/h265enc/fetest.c, where the "core" is a function that
 * fills the list's length word and the stream.
 * License: GPL-2.0-or-later
 */
#ifndef FREEENC_H
#define FREEENC_H
#include <stdint.h>
#include <string.h>
#include "paramsets.h"
#include "slicehdr.h"
#include "avc.h"
#include "rc.h"
#include "listgen.h"
#include "worktab.h"

struct fe_env {
	volatile uint32_t *regs;		/* the register window (0x20020000) */
	unsigned long (*alloc)(int size);	/* akuio_alloc_pmem: zeroed pool memory, its virtual address */
	void (*release)(unsigned long vaddr);	/* akuio_free_pmem */
	int (*v2p)(unsigned long vaddr);	/* akuio_vaddr2paddr */
	void (*wait)(unsigned long res);	/* akuio_wait_irq: waits for the interrupt, clears 0x8018; *res < 0: none */
	void (*reset)(void);			/* akuio_reset_video: the encoder's reset bit (NULL: none) */
};

struct fe_enc {
	const struct fe_env *env;
	int hevc, w, h, stride, fps, gop, qp0;
	uint8_t *mem;				/* one pool block: frames, stream, tables, work, small, list */
	uint32_t pa, frame_size, f_uv, f_mv, f_col, rec_pitch, stream_off, stream_alloc, tables_off, work_off, small_off,
		 list_off;
	int cur, frame, idrs, force_idr;
	struct rc rc;
	uint8_t params[192];
	int plen;
	uint32_t pictures, bytes, fails;
	uint32_t last_len, last_status;	/* of the last failed picture: list words 0x41 and 0x40 */
	uint32_t dbg[6];		/* of the last picture: 0x8300 and 0x8014 before the start, the wait's result, 0x8018,
					 * 0x801c and 0x8300 after it */
};

#define FE_STREAM_HEAD 0x820u
#define FE_TABLES_SIZE 0x4040u
#define FE_WORK_SIZE 0x6400u
#define FE_SMALL_SIZE 0x100u
#define FE_LIST_WORDS 112

#define FE_R_IRQ_EN	0x8010
#define FE_R_MASK	0x8014
#define FE_R_STAT	0x801c
#define FE_R_ACK	0x8020
#define FE_R_LIST	0x8080
#define FE_R_START	0x8084
#define FE_R_UNK	0x8300
#define FE_R_CLK	0xc004
#define FE_RD(e, o)	((e)->env->regs[(o) / 4])
#define FE_WR(e, o, v)	((e)->env->regs[(o) / 4] = (v))

static const uint8_t FE_TABLES_HEAD[20] = { 0xc4, 0x09, 0xe8, 0x03, 0x00, 0x01, 0x88, 0x13, 0x58, 0x1b, 0x28, 0x23, 0x01,
					   0x03, 0x0a, 0x01, 0x02, 0x03, 0x19, 0x24 };

static inline uint32_t fe_up(uint32_t v, uint32_t a) { return (v + a - 1) & ~(a - 1); }

/* the frame buffer written last, per codec, across encoders (set with cur >= 0, read with cur < 0) */
static inline int fe_last_cur(int hevc, int cur)
{
	static int last[2] = { 1, 1 };

	if (cur >= 0) last[hevc ? 1 : 0] = cur;
	return last[hevc ? 1 : 0];
}

/* hevc 1 = H.265, 0 = H.264; w x h = 1920x1080, 1280x720 or 640x360; stride: of the source's Y plane (the width; a
 * bigger stride also lets a 640x360 H.264 encoder read the top-left of a bigger picture, the warm-up frame of
 * tc100_rtsp). NULL when out of pool memory. */
static inline struct fe_enc *fe_open_wh(const struct fe_env *env, struct fe_enc *e, int hevc, int w, int h, int stride,
					int fps, int gop, int kbps, int qmin, int qmax)
{
	uint32_t o, total;

	memset(e, 0, sizeof *e);
	e->env = env; e->hevc = hevc;
	/* the first reconstruction goes into the other buffer than the last picture of the previous encoder (a new encoder
	 * gets the same pool block back): on IPCAM2 an IDR into the buffer the last picture was written to hangs the core */
	e->cur = fe_last_cur(hevc, -1) ^ 1;
	e->w = w > 0 ? w : (hevc ? 1920 : 640);
	e->h = h > 0 ? h : (hevc ? 1080 : 360);
	e->stride = stride > 0 ? stride : e->w;
	e->fps = fps > 0 ? fps : 25; e->gop = gop > 0 ? gop : 2 * e->fps;
	if (e->w == 1920) {	/* 1920x1080 (h265live.c's frame layout, cmdlist.FRAME_PLANE_OFFSETS) */
		e->frame_size = hevc ? 0x340000 : 0x350000;
		e->f_uv = 0x1fe000; e->f_mv = 0x2fd000;
		e->f_col = hevc ? 0x300400 : 0x308000;
		e->rec_pitch = 0x1e00;
		e->stream_alloc = 0x7e900;
	} else if (e->w == 1280) {	/* 1280x720 (H.265 or H.264) */
		e->frame_size = 0x1a0000; e->f_uv = 0xf0000; e->f_mv = 0x168000; e->f_col = 0x16d000; e->rec_pitch = 0x1400;
		e->stream_alloc = 0x40000;
	} else {	/* 640x360: Y (tiled, pitch 0xa00), UV, motion info (0x1240 bytes), co-located info */
		e->frame_size = 0x63000; e->f_uv = 0x3c000; e->f_mv = 0x5a000; e->f_col = 0x5b240; e->rec_pitch = 0xa00;
		e->stream_alloc = 0xdf80;
	}
	o = 2 * e->frame_size;
	e->stream_off = o; o = fe_up(o + e->stream_alloc, 0x1000);
	e->tables_off = o; o = fe_up(o + FE_TABLES_SIZE, 0x1000);
	e->work_off = o; o = fe_up(o + FE_WORK_SIZE, 0x1000);
	e->small_off = o; o += 0x400;
	e->list_off = o; o += 0x200;
	total = fe_up(o, 0x1000);
	e->mem = (uint8_t *)env->alloc((int)total);
	if (!e->mem) return NULL;
	e->pa = (uint32_t)env->v2p((unsigned long)e->mem);
	if (!e->pa) { env->release((unsigned long)e->mem); e->mem = NULL; return NULL; }
	memset(e->mem, 0, total);
	memcpy(e->mem + e->tables_off, FE_TABLES_HEAD, sizeof FE_TABLES_HEAD);
	if (hevc) h265_work_table(e->mem + e->work_off); else h264_work_table(e->mem + e->work_off);
	e->qp0 = (qmin + qmax) / 2 < 32 ? (qmin + qmax) / 2 : 32;
	rc_init(&e->rc, kbps > 0 ? kbps : 1000, e->fps, qmin > 0 ? qmin : 20, qmax > 0 && qmax <= 51 ? qmax : 51, e->qp0);
	e->plen = hevc ? h265_param_sets(e->params, sizeof e->params, (uint32_t)e->w, (uint32_t)e->h, (uint32_t)e->fps)
		       : h264_param_sets(e->params, sizeof e->params, (uint32_t)e->w, (uint32_t)e->h, (uint32_t)e->fps,
					 (uint32_t)(kbps > 0 ? kbps : (e->w > 640 ? 1000 : 250)));
	if (e->plen < 0) { env->release((unsigned long)e->mem); e->mem = NULL; return NULL; }
	return e;
}

static inline struct fe_enc *fe_open(const struct fe_env *env, struct fe_enc *e, int hevc, int stride, int fps, int gop,
				     int kbps, int qmin, int qmax)
{
	return fe_open_wh(env, e, hevc, hevc ? 1920 : 640, hevc ? 1080 : 360, stride, fps, gop, kbps, qmin, qmax);
}

static inline void fe_close(struct fe_enc *e)
{
	if (e->mem) e->env->release((unsigned long)e->mem);
	e->mem = NULL;
}

/* ABR: a new target bit rate (the buffer of the rate control is kept) */
static inline void fe_set_kbps(struct fe_enc *e, int kbps)
{
	if (kbps > 0) e->rc.budget = (int64_t)kbps * 1000 / 8 / e->fps;
}

/* the 112 words of a picture's list into l */
static inline void fe_list(const struct fe_enc *e, uint32_t *l, uint32_t src_y, uint32_t src_uv, int idr, int qp,
			   uint32_t poc)
{
	uint32_t base = e->pa, rec = base + (uint32_t)e->cur * e->frame_size, ref = base + (uint32_t)(e->cur ^ 1) * e->frame_size,
		 st = base + e->stream_off;
	int i;

	if (e->hevc) {
		if (e->w == 1280) memcpy(l, idr ? LISTGEN_720P_IDR : LISTGEN_720P_P, 32 * 4);
		else memcpy(l, idr ? LISTGEN_IDR : LISTGEN_P, 32 * 4);
	} else {
		if (e->w == 1920) memcpy(l, idr ? LISTGEN_H264_1080P_IDR : LISTGEN_H264_1080P_P, 32 * 4);
		else if (e->w == 1280) memcpy(l, idr ? LISTGEN_H264_720P_IDR : LISTGEN_H264_720P_P, 32 * 4);
		else memcpy(l, idr ? LISTGEN_H264_IDR : LISTGEN_H264_P, 32 * 4);
	}
	for (i = 32; i < FE_LIST_WORDS; i++) l[i] = 0;
	l[0x20] = src_y; l[0x21] = src_uv; l[0x22] = (uint32_t)e->stride;
	l[0x23] = base + e->tables_off;
	l[0x24] = rec; l[0x25] = rec + e->f_uv; l[0x26] = e->rec_pitch; l[0x27] = base + e->work_off;
	l[0x2e] = rec + e->f_col; l[0x2f] = base + e->small_off; l[0x37] = rec + e->f_mv;
	if (!idr) { l[0x28] = ref; l[0x29] = ref + e->f_uv; l[0x2c] = ref + e->f_col; l[0x38] = ref + e->f_mv; }
	if (e->hevc) {	/* h265live: the stream in both groups, the size 0x200 short of the allocation */
		uint32_t size = e->stream_alloc - 0x200;

		for (i = 0x30; i <= 0x3c; i += 0x0c) {
			l[i] = st; l[i + 1] = size; l[i + 2] = FE_STREAM_HEAD; l[i + 3] = size - 2 * FE_STREAM_HEAD;
		}
	} else {
		l[0x3c] = st; l[0x3d] = e->stream_alloc; l[0x3e] = FE_STREAM_HEAD; l[0x3f] = e->stream_alloc - 2 * FE_STREAM_HEAD;
		l[0x1b] = (l[0x1b] & ~0x03ff0000u) | ((uint32_t)(qp + 32 >= 60 ? 10 : (qp + 32) / 6) << 16);	/* sp_8c */
	}
	l[0x03] = (l[0x03] & ~0x00ff0000u) | ((uint32_t)qp << 16);
	l[0x1c] = (l[0x1c] & ~0x007f0000u) | ((uint32_t)qp << 16);
	l[0x0c] = poc; l[0x0d] = poc >= 2 ? poc - 2 : 0; l[0x0f] = poc >= 2 ? poc - 2 : 0;
	l[0x10] = poc >= 4 ? poc - 4 : 0xffffffffu;
}

#ifndef FE_HOST_TEST
/* the reset bit, then the vendor's initialisation of the registers (h265live, src/jpegenc/jpeg_hw.h hw_init) */
static inline void fe_hw_init(const struct fe_env *env)
{
	volatile uint32_t *r = env->regs;

	if (env->reset) env->reset();
	r[FE_R_IRQ_EN / 4] = 0xffffffff; r[0x8018 / 4] = 0xffffff;
	(void)r[FE_R_ACK / 4]; r[FE_R_ACK / 4] = 1; r[0x822c / 4] = 0;
	(void)r[FE_R_ACK / 4]; r[FE_R_ACK / 4] = 0x10000;
	r[0x8034 / 4] = 0; r[0x8054 / 4] = 0x70;
}

/* the core: one list, the vendor's register sequence for its codec; 0 or -1 (no interrupt: the core is reset) */
static inline int fe_run(struct fe_enc *e, uint32_t list_pa)
{
	int res = -1;

	e->dbg[0] = FE_RD(e, FE_R_UNK); e->dbg[1] = FE_RD(e, FE_R_MASK);
	FE_WR(e, FE_R_IRQ_EN, 0x1000007); FE_WR(e, 0x822c, 0);
	if (e->hevc) {
		FE_WR(e, FE_R_MASK, (FE_RD(e, FE_R_MASK) & ~0x4u) | 0x1u);
		FE_WR(e, FE_R_CLK, FE_RD(e, FE_R_CLK) | 0x8e00);
		(void)FE_RD(e, FE_R_UNK);
		FE_WR(e, FE_R_LIST, list_pa);
		FE_WR(e, FE_R_START, 2);
	} else {
		FE_WR(e, FE_R_MASK, (FE_RD(e, FE_R_MASK) & ~0x5u) | 0x4u);
		FE_WR(e, FE_R_CLK, (FE_RD(e, FE_R_CLK) & ~0x8000u) | 0x0e00);
		(void)FE_RD(e, FE_R_UNK); (void)FE_RD(e, FE_R_UNK);
		FE_WR(e, FE_R_LIST, list_pa);
		FE_WR(e, FE_R_START, 2);
		FE_WR(e, FE_R_LIST, list_pa);
		FE_WR(e, FE_R_START, 8);
	}
	e->env->wait((unsigned long)&res);
	e->dbg[2] = (uint32_t)res; e->dbg[3] = FE_RD(e, 0x8018); e->dbg[4] = FE_RD(e, FE_R_STAT); e->dbg[5] = FE_RD(e, FE_R_UNK);
	/* the end status (write 1 to clear) is cleared here too: libakuio does it only when it has the registers mapped,
	 * and a status left set makes the next wait return at once, the core still busy (0x8300 = 0x20001) */
	FE_WR(e, 0x8018, e->dbg[3]);
	FE_WR(e, FE_R_MASK, FE_RD(e, FE_R_MASK));
	if (!e->hevc) FE_WR(e, FE_R_MASK, FE_RD(e, FE_R_MASK) & ~0x4u);
	if (FE_RD(e, FE_R_ACK) == 0x10001) FE_WR(e, FE_R_ACK, 0x10000);
	(void)FE_RD(e, FE_R_STAT); (void)FE_RD(e, FE_R_ACK); FE_WR(e, FE_R_ACK, 1);
	if (res < 0) { fe_hw_init(e->env); return -1; }
	return 0;
}
#else
static int fe_run(struct fe_enc *e, uint32_t list_pa);	/* fetest.c: the simulated core */
#endif

/* encode the NV12 picture at physical src_pa (Y, then UV at src_pa + stride * height); 0 and *data / *len / *idr,
 * or -1 */
static inline int fe_encode(struct fe_enc *e, uint32_t src_pa, uint8_t **data, uint32_t *len, int *idr_out)
{
	uint32_t *l = (uint32_t *)(void *)(e->mem + e->list_off), n, fr, poc, hl, off;
	uint8_t hb[64], *st = e->mem + e->stream_off;
	int idr, q, h;

	idr = e->frame == 0 || e->force_idr || e->frame % e->gop == 0;
	if (idr) { e->frame = 0; e->force_idr = 0; }
	fr = (uint32_t)e->frame;
	poc = 2 * fr;
	q = rc_qp(&e->rc, idr);
	fe_list(e, l, src_pa, src_pa + (uint32_t)e->stride * (uint32_t)e->h, idr, q, poc);
	e->mem[e->tables_off + 18] = !e->hevc && idr ? 0x1f : 0x19;
	e->mem[e->tables_off + 19] = idr ? 0x24 : 0x30;
	if (fe_run(e, e->pa + e->list_off) < 0) { e->last_len = 0; e->last_status = 0xffffffffu; e->fails++; e->force_idr = 1; return -1; }
	n = l[0x41];
	if (!n || n > e->stream_alloc - 2 * FE_STREAM_HEAD) { e->last_len = n; e->last_status = l[0x40]; e->fails++; e->force_idr = 1; return -1; }
	h = e->hevc ? h265_slice_nal(hb, sizeof hb, idr, q, poc) : h264_slice_nal(hb, sizeof hb, idr, q, fr, (uint32_t)(e->idrs & 1));
	if (h < 0) return -1;
	hl = (uint32_t)h + (idr ? (uint32_t)e->plen : 0);
	off = FE_STREAM_HEAD - hl;
	if (idr) memcpy(st + off, e->params, (size_t)e->plen);
	memcpy(st + FE_STREAM_HEAD - (uint32_t)h, hb, (size_t)h);
	if (idr) e->idrs++;
	rc_done(&e->rc, idr, q, (int64_t)h + n);
	fe_last_cur(e->hevc, e->cur);
	e->cur ^= 1;
	e->frame++;
	e->pictures++; e->bytes += hl + n;
	*data = st + off; *len = hl + n; *idr_out = idr;
	return 0;
}
#endif
