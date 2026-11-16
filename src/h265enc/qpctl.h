/*
 * qpctl.h: the 0x4040-byte "tables" buffer of list word 0x23 read as the QP control buffer of the Allegro core, and
 * the experiments of the T1 bench on it (qpbench.c, docs/linux-port/frontier/t1-qp-bench.md). BENCH ONLY: tc100_rtsp
 * does not include this file.
 *
 * Layout. Known = what the vendor encoder of the camera wrote (captures of 2026-11-07); matched = the layout of
 * Allegro's public control software (Xilinx/vcu-ctrl-sw, MIT: include/lib_common_enc/EncBuffers.h, QPTable.h), which
 * fits those bytes; nothing below "matched" has been tried on the camera.
 *   0x00  QP_CTRL, 48 bytes, "only 20 bytes used" (EP2_BUF_QP_CTRL): the core's own per-block QP adaptation
 *           0..11   six 16-bit little-endian thresholds: 2500 1000 256 5000 7000 9000        (known bytes)
 *           12..17  six one-byte QP steps: 1 3 10 1 2 3                                      (known bytes)
 *           18      lowest block QP: 25 (H.264 IDR: 31)                                      (known bytes)
 *           19      highest block QP: 36 for an IDR, 48 for a P picture                      (known bytes)
 *           20..47  zero
 *   0x30  SEG_CTRL, 16 bytes (EP2_BUF_SEG_CTRL: 8 segments x 2 bytes, VP9 only)              zero on the camera
 *   0x40  QP_BY_MB (EP2_BUF_QP_BY_MB), 0x4000 bytes here                                      zero on the camera
 *           per block: bits 0-5 a QP (MASK_QP), bit 6 forced intra (MASK_FORCE_INTRA), bit 7 forced zero motion
 *           (MASK_FORCE_MV0). Not known: the block size (32x32 = 2040 bytes at 1920x1080, 16x16 = 8160 bytes), the
 *           order, whether the QP is a difference or absolute, and whether the core reads the map at all without a
 *           bit of the list that says "the map is there" (the control software has such flags: QP_CTRL 1, SEG_CTRL 2,
 *           QP_BY_MB 4).
 *
 * An experiment is one specification (qpc_parse), applied to a buffer that holds the vendor's values (qpc_vendor)
 * right before each picture (qpc_apply):
 *   ctl                    nothing (the control run: how much two runs differ by themselves)
 *   min=N  max=N           byte 18 / 19 (0..51), for IDR and P pictures alike
 *   thrI=V                 threshold I (0..5), 0..65535
 *   dq=V  dqI=V            all six QP steps / step I (0..5); -128..255
 *   byte@OFF=V             any byte of the first 64 (OFF 0..63)
 *   map=V[,REGION][,GEOM]  bytes of the map. V: a number 0..255, +N / -N (a 6-bit difference), skip (0x80), intra (0x40)
 *                          REGION: none = the whole map (0x4000 bytes); first=K = the first K bytes; top bottom left
 *                          right = half of the picture; rect=X0:Y0:X1:Y1 = blocks X0..X1-1, Y0..Y1-1.
 *                          GEOM (for top .. rect): blk=N block size in pixels (default 32 for H.265, 16 for H.264),
 *                          cols=N blocks per row (default: width / blk rounded up), unit=N bytes per block (default 1)
 *   list@WORD:MASK=V       bits MASK of list word WORD (0..0x1f) = V (hexadecimal accepted): the search for the bit
 *                          that makes the core read the map. The riskiest one: an unknown bit can hang the core.
 * License: GPL-2.0-or-later
 */
#ifndef QPCTL_H
#define QPCTL_H
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define QPC_SIZE	0x4040u
#define QPC_HEAD	64u		/* QP_CTRL (48) + SEG_CTRL (16) */
#define QPC_MAP_SIZE	(QPC_SIZE - QPC_HEAD)
#define QPC_OFF_STEPS	12u
#define QPC_OFF_MIN	18u
#define QPC_OFF_MAX	19u
#define QPC_FORCE_INTRA	0x40u
#define QPC_FORCE_MV0	0x80u

/* the vendor's first 20 bytes (the same bytes as FE_TABLES_HEAD of freeenc.h: qpbench checks it at start) */
static const uint8_t QPC_VENDOR_HEAD[20] = { 0xc4, 0x09, 0xe8, 0x03, 0x00, 0x01, 0x88, 0x13, 0x58, 0x1b, 0x28, 0x23, 0x01,
					     0x03, 0x0a, 0x01, 0x02, 0x03, 0x19, 0x24 };

enum { QPC_CTL, QPC_HEAD8, QPC_HEAD16, QPC_MAP, QPC_LIST };

struct qpc_exp {
	int kind;
	uint32_t off, n, val, mask;	/* HEAD8: n bytes from off = val; HEAD16: the 16-bit value at off; LIST: word off */
	uint32_t first;			/* MAP: the first `first` bytes (0: the rectangle below) */
	int x0, y0, x1, y1, cols, rows, unit, blk;
};

/* the whole buffer as the vendor's software leaves it before a picture (freeenc.h fe_open_wh + fe_encode) */
static inline void qpc_vendor(uint8_t *t, int hevc, int idr)
{
	memset(t, 0, QPC_SIZE);
	memcpy(t, QPC_VENDOR_HEAD, sizeof QPC_VENDOR_HEAD);
	t[QPC_OFF_MIN] = !hevc && idr ? 0x1f : 0x19;
	t[QPC_OFF_MAX] = idr ? 0x24 : 0x30;
}

static inline int qpc_num(const char *s, long lo, long hi, long *out)
{
	char *e;
	long v;

	if (!s || !*s) return -1;
	v = strtol(s, &e, 0);
	if (*e || v < lo || v > hi) return -1;
	*out = v;
	return 0;
}

static inline int qpc_u32(const char *s, uint32_t *out)
{
	char *e;
	unsigned long long v;

	if (!s || !*s || *s == '-') return -1;
	v = strtoull(s, &e, 0);
	if (*e || v > 0xffffffffull) return -1;
	*out = (uint32_t)v;
	return 0;
}

static inline int qpc_mapval(const char *s, long *out)
{
	if (!s) return -1;
	if (!strcmp(s, "skip")) { *out = QPC_FORCE_MV0; return 0; }
	if (!strcmp(s, "intra")) { *out = QPC_FORCE_INTRA; return 0; }
	if (s[0] == '+' || s[0] == '-') {
		if (qpc_num(s, -32, 31, out)) return -1;
		*out &= 0x3f;
		return 0;
	}
	return qpc_num(s, 0, 255, out);
}

/* 0 and *x, or -1 (a specification that is not understood changes nothing: the bench refuses to run) */
static inline int qpc_parse(struct qpc_exp *x, const char *spec, int w, int h, int hevc)
{
	char b[96], *tok[8], *p, *eq, *k;
	int nt = 0, i, region = 0;
	long v;

	memset(x, 0, sizeof *x);
	if (!spec || !*spec || strlen(spec) >= sizeof b || w <= 0 || h <= 0) return -1;
	strcpy(b, spec);
	for (p = b; nt < 8; ) {
		tok[nt++] = p;
		if (!(p = strchr(p, ','))) break;
		*p++ = 0;
	}
	if (p) return -1;
	k = tok[0];
	if ((eq = strchr(k, '='))) *eq++ = 0;
	if (strcmp(k, "map") && nt != 1) return -1;
	if (!strcmp(k, "ctl")) { x->kind = QPC_CTL; return eq ? -1 : 0; }
	if (!eq) return -1;
	if (!strcmp(k, "min") || !strcmp(k, "max")) {
		if (qpc_num(eq, 0, 51, &v)) return -1;
		x->kind = QPC_HEAD8; x->off = k[1] == 'i' ? QPC_OFF_MIN : QPC_OFF_MAX; x->n = 1; x->val = (uint32_t)v;
		return 0;
	}
	if (!strncmp(k, "thr", 3) && k[3] >= '0' && k[3] <= '5' && !k[4]) {
		if (qpc_num(eq, 0, 65535, &v)) return -1;
		x->kind = QPC_HEAD16; x->off = 2u * (uint32_t)(k[3] - '0'); x->n = 2; x->val = (uint32_t)v;
		return 0;
	}
	if (!strncmp(k, "dq", 2) && (!k[2] || (k[2] >= '0' && k[2] <= '5' && !k[3]))) {
		if (qpc_num(eq, -128, 255, &v)) return -1;
		x->kind = QPC_HEAD8; x->val = (uint32_t)v & 0xff;
		x->off = QPC_OFF_STEPS + (k[2] ? (uint32_t)(k[2] - '0') : 0); x->n = k[2] ? 1 : 6;
		return 0;
	}
	if (!strncmp(k, "byte@", 5)) {
		long off;

		if (qpc_num(k + 5, 0, QPC_HEAD - 1, &off) || qpc_num(eq, 0, 255, &v)) return -1;
		x->kind = QPC_HEAD8; x->off = (uint32_t)off; x->n = 1; x->val = (uint32_t)v;
		return 0;
	}
	if (!strncmp(k, "list@", 5)) {
		char *c = strchr(k + 5, ':');
		long word;

		if (!c) return -1;
		*c++ = 0;
		if (qpc_num(k + 5, 0, 0x1f, &word) || qpc_u32(c, &x->mask) || qpc_u32(eq, &x->val)) return -1;
		if (!x->mask || (x->val & ~x->mask)) return -1;
		x->kind = QPC_LIST; x->off = (uint32_t)word;
		return 0;
	}
	if (strcmp(k, "map") || qpc_mapval(eq, &v)) return -1;
	x->kind = QPC_MAP; x->val = (uint32_t)v;
	x->blk = hevc ? 32 : 16; x->unit = 1;
	for (i = 1; i < nt; i++) {	/* the geometry first: the regions are counted in its blocks */
		if (!strncmp(tok[i], "blk=", 4)) {
			if (qpc_num(tok[i] + 4, 8, 64, &v) || (v & (v - 1))) return -1;
			x->blk = (int)v;
		} else if (!strncmp(tok[i], "unit=", 5)) {
			if (qpc_num(tok[i] + 5, 1, 64, &v)) return -1;
			x->unit = (int)v;
		} else if (!strncmp(tok[i], "cols=", 5)) {
			if (qpc_num(tok[i] + 5, 1, 4096, &v)) return -1;
			x->cols = (int)v;
		}
	}
	if (!x->cols) x->cols = (w + x->blk - 1) / x->blk;
	x->rows = (h + x->blk - 1) / x->blk;
	x->x0 = x->y0 = 0; x->x1 = x->cols; x->y1 = x->rows;
	for (i = 1; i < nt; i++) {
		char *t = tok[i];

		if (!strncmp(t, "blk=", 4) || !strncmp(t, "unit=", 5) || !strncmp(t, "cols=", 5)) continue;
		if (region++) return -1;	/* one region */
		if (!strncmp(t, "first=", 6)) {
			if (qpc_num(t + 6, 1, QPC_MAP_SIZE, &v)) return -1;
			x->first = (uint32_t)v;
		} else if (!strcmp(t, "top")) x->y1 = x->rows / 2;
		else if (!strcmp(t, "bottom")) x->y0 = x->rows / 2;
		else if (!strcmp(t, "left")) x->x1 = x->cols / 2;
		else if (!strcmp(t, "right")) x->x0 = x->cols / 2;
		else if (!strncmp(t, "rect=", 5)) {
			long r[4];
			char *s = t + 5, *c;
			int j;

			for (j = 0; j < 4; j++) {
				c = strchr(s, ':');
				if ((j < 3) != (c != NULL)) return -1;
				if (c) *c = 0;
				if (qpc_num(s, 0, 4096, &r[j])) return -1;
				s = c ? c + 1 : s;
			}
			x->x0 = (int)r[0]; x->y0 = (int)r[1]; x->x1 = (int)r[2]; x->y1 = (int)r[3];
		} else return -1;
	}
	if (!region) { x->first = QPC_MAP_SIZE; return 0; }
	if (x->first) return 0;
	if (x->x0 >= x->x1 || x->y0 >= x->y1 || x->x1 > x->cols || x->y1 > x->rows) return -1;
	if ((uint64_t)x->cols * (uint32_t)x->rows * (uint32_t)x->unit > QPC_MAP_SIZE) return -1;
	return 0;
}

/* the experiment on top of the vendor's values: t = the tables buffer, l = the picture's list (NULL: none) */
static inline void qpc_apply(const struct qpc_exp *x, uint8_t *t, uint32_t *l)
{
	uint32_t i;
	int y;

	switch (x->kind) {
	case QPC_HEAD8:
		for (i = 0; i < x->n; i++) t[x->off + i] = (uint8_t)x->val;
		break;
	case QPC_HEAD16:
		t[x->off] = (uint8_t)x->val; t[x->off + 1] = (uint8_t)(x->val >> 8);
		break;
	case QPC_MAP:
		if (x->first) { memset(t + QPC_HEAD, (int)x->val, x->first); break; }
		for (y = x->y0; y < x->y1; y++)
			memset(t + QPC_HEAD + (uint32_t)(y * x->cols + x->x0) * (uint32_t)x->unit, (int)x->val,
			       (size_t)(x->x1 - x->x0) * (size_t)x->unit);
		break;
	case QPC_LIST:
		if (l) l[x->off] = (l[x->off] & ~x->mask) | x->val;
		break;
	default:
		break;
	}
}
#endif
