/*
 * worktab.h: the 0x6400-byte buffer of list word 0x27 ("work"), computed instead of copied from the vendor encoder
 * (step 3, 2026-11-07). On IPCAM2 the vendor software fills it once and the same content serves every picture, IDR and
 * P; left at zero the core codes every picture alike whatever the QP (20-23 KB at QP 35 or 51). Its parts:
 *   0x000  52 x 4 bytes, one row per QP: the core's rate-distortion weights. Columns 1-3 are ceil(A * 2^(QP / 6))
 *          (A = 0.1617, 0.1839, 0.1617, read from the vendor's table); column 0 follows no such formula and is
 *          the vendor's 52 values.
 *   0x100  the HEVC default scaling lists (H.265 table 7-6) as 8x8 matrices in raster order, 64 bytes each:
 *          32x32 intra, inter; 16x16 intra x3, inter x3; 8x8 intra x3, inter x3; then the 4x4 lists (6 x 16, flat 16),
 *          the 16x16 DC values (3, a zero, 3, a zero) at 0x4e0 and the 32x32 DC values at 0x500
 *   0x520  32-bit forward quantisation factors 2^24 / (m * invLevelScale[q]) for q = QP % 6 (invLevelScale 40 45 51
 *          57 64 72, H.265 8.6.4.2), q outer then the matrices of a size: 32x32 (2 x 64), its DC (2 per q, padded to
 *          16 values), 16x16 (6 x 64), its DC (6 per q, padded to 40), 8x8 (6 x 64), 4x4 (6 x 16), then zeros.
 * tests/test_h265cmdlist.py WorkTable checks the whole buffer against the SHA-256 of the IPCAM2 capture.
 * License: GPL-2.0-or-later
 */
#ifndef WORKTAB_H
#define WORKTAB_H
#include <stdint.h>
#include <string.h>

#define WORKTAB_SIZE 0x6400

/* H.265 table 7-6, default 8x8 lists, in up-right diagonal scan order */
static const uint8_t WT_INTRA_DIAG[64] = {
	16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 17, 16, 17, 16, 17, 18, 17, 18, 18, 17, 18, 21, 19, 20, 21, 20, 19, 21,
	24, 22, 22, 24, 24, 22, 22, 24, 25, 25, 27, 30, 27, 25, 25, 29, 31, 35, 35, 31, 29, 36, 41, 44, 41, 36, 47, 54,
	54, 47, 65, 70, 65, 88, 88, 115 };
static const uint8_t WT_INTER_DIAG[64] = {
	16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 17, 17, 17, 17, 17, 18, 18, 18, 18, 18, 18, 20, 20, 20, 20, 20, 20, 20,
	24, 24, 24, 24, 24, 24, 24, 24, 25, 25, 25, 25, 25, 25, 25, 28, 28, 28, 28, 28, 28, 33, 33, 33, 33, 33, 41, 41,
	41, 41, 54, 54, 54, 71, 71, 91 };
static const uint8_t WT_RD_COL0[52] = {
	1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 3, 3, 4, 4, 4, 5, 6, 7, 7, 9, 10, 11, 13, 15, 17, 19,
	21, 24, 26, 29, 33, 37, 42, 47, 52, 58, 66, 74, 83, 93, 104 };

/* the 8x8 matrix in raster order from its diagonal scan (H.265 6.5.3, 8x8 up-right diagonal) */
/* 2^(q / 6) and the roundings without the maths library (tc100_rtsp has no libm): 2^(q % 6 / 6) * 2^(q / 6) */
static inline double wt_exp2_6(int q)
{
	static const double f[6] = { 1.0, 1.122462048309373, 1.259921049894873, 1.414213562373095, 1.587401051968199,
				     1.781797436280678 };

	return f[q % 6] * (double)(1u << (q / 6));
}

static inline int wt_ceil(double x) { int i = (int)x; return (double)i < x ? i + 1 : i; }
static inline int wt_round(double x) { return (int)(x + 0.5); }

static inline void wt_raster(uint8_t *out, const uint8_t *diag)
{
	int i = 0, x, y, d;

	for (d = 0; d < 15; d++)
		for (y = d < 8 ? d : 7; y >= 0; y--) {
			x = d - y;
			if (x > 7) break;
			out[y * 8 + x] = diag[i++];
		}
}

static inline void wt_u32(uint8_t *p, uint32_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24); }

static inline void h265_work_table(uint8_t *b)
{
	static const uint32_t il[6] = { 40, 45, 51, 57, 64, 72 };
	uint8_t A[64], B[64];
	const uint8_t *mat32[2] = { A, B }, *mat6[6] = { A, A, A, B, B, B };
	int q, i, k, o;
	uint8_t *u;

	memset(b, 0, WORKTAB_SIZE);
	for (q = 0; q < 52; q++) {
		double s = wt_exp2_6(q);

		b[4 * q] = WT_RD_COL0[q];
		b[4 * q + 1] = (uint8_t)wt_ceil(0.1617 * s);
		b[4 * q + 2] = (uint8_t)wt_ceil(0.1839 * s);
		b[4 * q + 3] = (uint8_t)wt_ceil(0.1617 * s);
	}
	wt_raster(A, WT_INTRA_DIAG);
	wt_raster(B, WT_INTER_DIAG);
	o = 0x100;
	for (i = 0; i < 2; i++, o += 64) memcpy(b + o, mat32[i], 64);
	for (k = 0; k < 2; k++) for (i = 0; i < 6; i++, o += 64) memcpy(b + o, mat6[i], 64);
	memset(b + o, 16, 96);					/* 4x4: flat */
	b[0x4e0] = b[0x4e1] = b[0x4e2] = 16; b[0x4e4] = b[0x4e5] = b[0x4e6] = 16;	/* 16x16 DC */
	b[0x500] = b[0x501] = 16;				/* 32x32 DC */
	u = b + 0x520;
#define WT_Q(m, q) ((1u << 24) / ((uint32_t)(m) * il[q]))
	for (q = 0; q < 6; q++) for (i = 0; i < 2; i++) for (k = 0; k < 64; k++, u += 4) wt_u32(u, WT_Q(mat32[i][k], q));
	for (q = 0; q < 6; q++) for (i = 0; i < 2; i++, u += 4) wt_u32(u, WT_Q(16, q));
	u += 4 * 4;
	for (q = 0; q < 6; q++) for (i = 0; i < 6; i++) for (k = 0; k < 64; k++, u += 4) wt_u32(u, WT_Q(mat6[i][k], q));
	for (q = 0; q < 6; q++) for (i = 0; i < 6; i++, u += 4) wt_u32(u, WT_Q(16, q));
	u += 4 * 4;
	for (q = 0; q < 6; q++) for (i = 0; i < 6; i++) for (k = 0; k < 64; k++, u += 4) wt_u32(u, WT_Q(mat6[i][k], q));
	for (q = 0; q < 6; q++) for (i = 0; i < 6; i++) for (k = 0; k < 16; k++, u += 4) wt_u32(u, WT_Q(16, q));
#undef WT_Q
}

/* The H.264 encoder's work buffer (the 640x360 sub stream, captures of 2026-11-07): only the 52 x 4 bytes of the
 * rate-distortion weights, the rest zero (no scaling lists: flat). Column 0 is round(2^(QP / 6) / 4) (at least 1),
 * columns 1-3 those of H.265 except 13 instead of 12 at QP 37 in columns 1 and 3 (the vendor's table).
 * tests/test_h265cmdlist.py WorkTable checks it against the SHA-256 of the IPCAM2 capture. */
static inline void h264_work_table(uint8_t *b)
{
	int q;

	memset(b, 0, WORKTAB_SIZE);
	for (q = 0; q < 52; q++) {
		double s = wt_exp2_6(q);
		int c0 = wt_round(0.25 * s);

		b[4 * q] = (uint8_t)(c0 < 1 ? 1 : c0);
		b[4 * q + 1] = b[4 * q + 3] = q == 37 ? 13 : (uint8_t)wt_ceil(0.1617 * s);
		b[4 * q + 2] = (uint8_t)wt_ceil(0.1839 * s);
	}
}
#endif
