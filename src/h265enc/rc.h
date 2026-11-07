/*
 * rc.h: the rate control of the free encoder (step 3, 2026-11-07): one QP per picture, from the size of the pictures
 * already coded, for a target bit rate. The vendor library does this too (its P pictures went from QP 38 to 42 for
 * 1.6 Mbit/s on IPCAM2); the core itself codes a picture at the QP of its list and slice header.
 *
 * Model: at a given content, the size of a coded picture halves when the QP grows by 6 (H.264/H.265 quantiser step
 * doubles every 6). A virtual buffer holds what was sent over the budget (bytes): the next P picture aims at
 * budget - buffer / RC_SPREAD, its QP moves by 6 * log2(last size / that aim) times RC_GAIN, at most RC_STEP per picture,
 * within [qmin, qmax]. An IDR is coded at the P QP minus RC_IDR_OFFSET (quality anchor); its excess over one budget
 * goes into the buffer and is paid back by the P pictures after it; the QP is moved by P pictures only.
 * No floating point library: log2 by a table of 1/16 steps.
 *
 * License: GPL-2.0-or-later
 */
#ifndef RC_H
#define RC_H
#include <stdint.h>

#define RC_SPREAD	25	/* pictures over which the buffer is paid back (1 s at 25 fps) */
#define RC_GAIN_NUM	1	/* the QP step taken: gain 1/2 of the model's */
#define RC_GAIN_DEN	2
#define RC_STEP		3	/* at most +-3 QP from one P picture to the next */
#define RC_IDR_SHARE	4	/* an IDR is about 4 P pictures at the same QP (start only) */
#define RC_IDR_OFFSET	2

struct rc {
	int qmin, qmax, qp;		/* qp: the next P picture's */
	int64_t budget;			/* bytes per picture */
	int64_t buffer;			/* bytes sent over the budget so far (can be negative) */
	int idr_qp;
	int started;			/* the first picture was coded */
};

static inline void rc_init(struct rc *r, int kbps, int fps, int qmin, int qmax, int qp0)
{
	r->qmin = qmin; r->qmax = qmax;
	r->budget = (int64_t)kbps * 1000 / 8 / (fps > 0 ? fps : 25);
	r->buffer = 0;
	r->qp = qp0 < qmin ? qmin : qp0 > qmax ? qmax : qp0;
	r->idr_qp = r->qp - RC_IDR_OFFSET;
	r->started = 0;
}

/* 16 * log2(a / b) for a, b > 0, to +-1 */
static inline int rc_log2x16(int64_t a, int64_t b)
{
	/* 16 * log2(1 + i/16) for i = 0..16 */
	static const uint8_t t[17] = { 0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 15, 16 };
	int s = 0;

	if (a <= 0 || b <= 0) return 0;
	while (a >= 2 * b) { b *= 2; s += 16; }
	while (a < b) { a *= 2; s -= 16; }
	return s + t[(int)((a - b) * 16 / b)];
}

static inline int rc_clamp(const struct rc *r, int q)
{
	return q < r->qmin ? r->qmin : q > r->qmax ? r->qmax : q;
}

/* the QP of the next picture */
static inline int rc_qp(struct rc *r, int idr)
{
	if (idr) {
		r->idr_qp = rc_clamp(r, r->qp - RC_IDR_OFFSET);
		return r->idr_qp;
	}
	return r->qp;
}

/* a picture of `bytes` was coded at `qp` */
static inline void rc_done(struct rc *r, int idr, int qp, int64_t bytes)
{
	int64_t aim;
	int d;

	if (!r->started) {
		/* start: the first IDR says how big the scene is; a P picture is about 1/RC_IDR_SHARE of it at the same QP
		 * (IPCAM2: 45 KB IDR, 12 KB P at QP 34-36), so the first P QP is set from it at full gain, and the IDR's
		 * excess is not paid back (no QP surge in the first second) */
		r->started = 1;
		if (idr) {
			d = 6 * rc_log2x16(bytes / RC_IDR_SHARE, r->budget) / 16 + RC_IDR_OFFSET;
			r->qp = rc_clamp(r, qp + d);
			return;
		}
	}
	r->buffer += bytes - r->budget;		/* an IDR's excess is paid back by the next pictures */
	if (idr) return;
	aim = r->budget - r->buffer / RC_SPREAD;
	if (aim < r->budget / 4) aim = r->budget / 4;
	d = 6 * rc_log2x16(bytes, aim) * RC_GAIN_NUM / (16 * RC_GAIN_DEN);
	if (d > RC_STEP) d = RC_STEP;
	if (d < -RC_STEP) d = -RC_STEP;
	r->qp = rc_clamp(r, qp + d);
}
#endif
