/* aacenc.c: a small AAC-LC encoder for the microphone of the camera (8 kHz, mono), in integer arithmetic only.
 *
 * Written for this project (GPL-2.0, like the rest), from the ISO/IEC 14496-3 description of the format; no code of another
 * encoder. The only third-party data are the Huffman code tables of the standard (aacenc_tab.h, numbers read from FFmpeg's
 * aactab.c by aacenc_tab_gen.py, LGPL-2.1-or-later, so redistributable under the GPL 2).
 *
 * What it does, per frame of 1024 samples (128 ms): sine window over the last 2048 samples, MDCT (folding + DCT-IV through
 * a 512-point complex FFT, 32-bit data, Q30 twiddles, no libm: the tables come from an integer sine at start), one global
 * quantizer step for the whole frame (all scale factors equal, so no scale factor costs more than 1 bit), power-law
 * quantization, the cheapest of the Huffman codebooks band by band, sections merged. The step is the finest one that keeps
 * the frame inside a bit budget (a small reservoir lets a loud frame borrow what the quiet ones left) and never finer than
 * a noise floor (there is nothing to gain in coding the 16-bit noise of the microphone). No psychoacoustic model, no TNS,
 * no PNS, no short blocks: long blocks only, a mono single channel element.
 *
 * Scale: X = 2 * sum(window * x * cos(...)) as ISO defines it; with the 4 extra bits kept in the integer transform
 * (x16), |X_true| = |X_int| / 8, so the dequantizer gain 2^((sf-100)/4) becomes 2^((sf-88)*0.1875) in the power domain
 * used by quant(): the constant 88 is 100 - 12 (8^0.75 = 2^2.25).
 */
#include <stdint.h>
#include <string.h>
#include "aacenc.h"
#include "aacenc_tab.h"

#define M		1024		/* spectral lines */
#define NF		512		/* FFT points: M / 2 */
#define NBANDS		40

/* ---- tables built at the first use ---------------------------------------------------------------------------- */
static int tabs_ready;
static int16_t win[M];			/* sine window, first half, Q15 */
static int32_t pre_c[NF], pre_s[NF];	/* exp(-i*pi*(n + 1/4)/M), Q30 */
static int32_t post_c[NF], post_s[NF];	/* exp(-i*pi*k/M) */
static int32_t tw_c[NF / 2], tw_s[NF / 2];	/* FFT: cos and sin of 2*pi*j/512 */
static uint16_t rev[NF];
static int32_t fre[NF], fim[NF];	/* FFT work (the writer is one thread) */

/* sin of a phase in turns Q16 (65536 = 2*pi), result Q30; Taylor series on the first quadrant */
static int32_t sinq30(uint32_t ph)
{
	uint32_t q = (ph >> 14) & 3, f = ph & 16383;
	int64_t y, y2, term, sum;
	int i;

	if (q & 1) f = 16384 - f;
	y = ((int64_t)f * 1686629713LL) >> 14;		/* f / 16384 * pi / 2, Q30 */
	y2 = (y * y) >> 30;
	term = y; sum = y;
	for (i = 1; i <= 6; i++) {
		term = -((term * y2) >> 30) / ((2 * i) * (2 * i + 1));
		sum += term;
	}
	if (sum > (1LL << 30)) sum = 1LL << 30;
	return (int32_t)(q >= 2 ? -sum : sum);
}
static int32_t cosq30(uint32_t ph) { return sinq30(ph + 16384); }

static void tabs_init(void)
{
	int i, j, b;

	if (tabs_ready) return;
	for (i = 0; i < M; i++) {
		int32_t s = sinq30((uint32_t)(2 * i + 1) * 8);

		s = (s + (1 << 14)) >> 15;
		win[i] = (int16_t)(s > 32767 ? 32767 : s);
	}
	for (i = 0; i < NF; i++) {
		pre_c[i] = cosq30((uint32_t)(4 * i + 1) * 8); pre_s[i] = sinq30((uint32_t)(4 * i + 1) * 8);
		post_c[i] = cosq30((uint32_t)i * 32); post_s[i] = sinq30((uint32_t)i * 32);
	}
	for (i = 0; i < NF / 2; i++) { tw_c[i] = cosq30((uint32_t)i * 128); tw_s[i] = sinq30((uint32_t)i * 128); }
	for (i = 0; i < NF; i++) {
		for (j = 0, b = 0; j < 9; j++) b |= ((i >> j) & 1) << (8 - j);
		rev[i] = (uint16_t)b;
	}
	tabs_ready = 1;
}

#define MUL30(a, c) ((int32_t)(((int64_t)(a) * (c)) >> 30))

/* in-place forward FFT of fre/fim (decimation in time), no scaling: the data is kept below 2^30 by the input scale */
static void fft512(void)
{
	int i, len, half, step, j, k;

	for (i = 0; i < NF; i++) {
		j = rev[i];
		if (j > i) {
			int32_t t = fre[i]; fre[i] = fre[j]; fre[j] = t;
			t = fim[i]; fim[i] = fim[j]; fim[j] = t;
		}
	}
	for (len = 2; len <= NF; len <<= 1) {
		half = len >> 1; step = NF / len;
		for (i = 0; i < NF; i += len)
			for (j = 0, k = 0; j < half; j++, k += step) {
				int a = i + j, b = a + half;
				int32_t wr = tw_c[k], wi = -tw_s[k];
				int32_t tr = MUL30(fre[b], wr) - MUL30(fim[b], wi);
				int32_t ti = MUL30(fre[b], wi) + MUL30(fim[b], wr);

				fre[b] = fre[a] - tr; fim[b] = fim[a] - ti;
				fre[a] += tr; fim[a] += ti;
			}
	}
}

/* windowed 2048 samples (hist, cur) -> e->X, x16 scale */
static void mdct(struct aacenc *e)
{
	int32_t u[M];
	int i, n;

#define ZW(n) ((int32_t)((n) < M ? e->hist[n] : e->cur[(n) - M]) * (int32_t)((n) < M ? win[n] : win[2 * M - 1 - (n)]) >> 11)
	for (i = 0; i < M / 2; i++) u[i] = -ZW(3 * M / 2 - 1 - i) - ZW(3 * M / 2 + i);
	for (; i < M; i++) u[i] = ZW(i - M / 2) - ZW(3 * M / 2 - 1 - i);
#undef ZW
	for (n = 0; n < NF; n++) {
		int32_t ur = u[2 * n], ui = u[M - 1 - 2 * n];

		fre[n] = MUL30(ur, pre_c[n]) + MUL30(ui, pre_s[n]);
		fim[n] = MUL30(ui, pre_c[n]) - MUL30(ur, pre_s[n]);
	}
	fft512();
	for (n = 0; n < NF; n++) {
		int32_t yr = MUL30(fre[n], post_c[n]) + MUL30(fim[n], post_s[n]);
		int32_t yi = MUL30(fim[n], post_c[n]) - MUL30(fre[n], post_s[n]);

		e->X[2 * n] = yr;
		e->X[M - 1 - 2 * n] = -yi;
	}
}

/* ---- quantization --------------------------------------------------------------------------------------------- */
/* 64 * y^0.75 (6 fractional bits): y = (1 + t) * 2^n, (1 + t)^0.75 by a degree-4 polynomial (error 6e-6, far below the
 * quantizer's own rounding), 2^(0.75 n) from a shift and the table of 2^(k/4) */
static uint32_t pow34(uint32_t y)
{
	static const int32_t c[5] = { 1073748607, 804945648, -97486375, 31439450, -6841341 };
	static const uint32_t f[4] = { 1073741824u, 1276901417u, 1518500250u, 1805811301u };	/* 2^(k/4), Q30 */
	int n, i;
	int64_t t, p;
	unsigned e;

	if (!y) return 0;
	n = 31 - __builtin_clz(y);
	t = (int64_t)((y << (31 - n)) - 0x80000000u) >> 1;	/* the fraction of y, Q30 */
	p = c[4];
	for (i = 3; i >= 0; i--) p = ((p * t) >> 30) + c[i];
	p = (p * f[(3 * n) & 3]) >> 30;				/* Q30, 1 .. 3.4 */
	e = (unsigned)(3 * n) >> 2;				/* 2^e: the 6 fractional bits and the Q30 are one shift */
	return (uint32_t)(p >> (24 - e));
}

static const uint32_t g16[16] = { 65536, 57549, 50535, 44376, 38968, 34219, 30048, 26386, 23170, 20347, 17867, 15689, 13777, 12098, 10624, 9329 };

static void quant(struct aacenc *e, int sf)
{
	int k = sf - 88, i;
	unsigned shift = 22 + 3u * (unsigned)(k >> 4);
	uint64_t g = g16[k & 15], rnd;

	if (shift > 60) { memset(e->q, 0, sizeof e->q); return; }
	rnd = (13285ULL << shift) >> 15;		/* 0.4054 */
	for (i = 0; i < M; i++) {
		uint64_t v = (e->P[i] * g + rnd) >> shift;

		if (v > 8191) v = 8191;
		e->q[i] = (int16_t)(e->X[i] < 0 ? -(int)v : (int)v);
	}
}

/* ---- bit stream ------------------------------------------------------------------------------------------------ */
struct bw { uint8_t *p; unsigned pos; };

static void put(struct bw *w, uint32_t v, unsigned n)
{
	while (n) {
		unsigned room = 8 - (w->pos & 7), t = n < room ? n : room, byte = w->pos >> 3;

		if (!(w->pos & 7)) w->p[byte] = 0;
		w->p[byte] |= (uint8_t)(((v >> (n - t)) & ((1u << t) - 1)) << (room - t));
		w->pos += t; n -= t;
	}
}

#define EMIT(v, n) do { bits += (n); if (w) put(w, (v), (n)); } while (0)
static int iabs(int x) { return x < 0 ? -x : x; }

/* the Huffman coded coefficients of one band with codebook cb (1..11): the bits they take, written when w is not NULL */
static unsigned band_code(struct bw *w, const int16_t *q, int n, int cb)
{
	const uint16_t *hc = aac_hcode + aac_hoff[cb - 1];
	const uint8_t *hb = aac_hbits + aac_hoff[cb - 1];
	unsigned bits = 0;
	int i;

	if (cb <= 4) {
		for (i = 0; i < n; i += 4) {
			int a = q[i], b = q[i + 1], c = q[i + 2], d = q[i + 3], idx;

			if (cb <= 2) idx = 27 * (a + 1) + 9 * (b + 1) + 3 * (c + 1) + d + 1;
			else idx = 27 * iabs(a) + 9 * iabs(b) + 3 * iabs(c) + iabs(d);
			EMIT(hc[idx], hb[idx]);
			if (cb > 2) {
				if (a) EMIT(a < 0, 1);
				if (b) EMIT(b < 0, 1);
				if (c) EMIT(c < 0, 1);
				if (d) EMIT(d < 0, 1);
			}
		}
		return bits;
	}
	for (i = 0; i < n; i += 2) {
		int a = q[i], b = q[i + 1], idx, ea = 0, eb = 0;

		if (cb <= 6) {
			idx = 9 * (a + 4) + b + 4;
			EMIT(hc[idx], hb[idx]);
			continue;
		}
		{
			int aa = iabs(a), bb = iabs(b), mul = cb <= 8 ? 8 : cb <= 10 ? 13 : 17;

			if (cb == 11) {
				if (aa >= 16) { ea = aa; aa = 16; }
				if (bb >= 16) { eb = bb; bb = 16; }
			}
			idx = mul * aa + bb;
			EMIT(hc[idx], hb[idx]);
			if (a) EMIT(a < 0, 1);
			if (b) EMIT(b < 0, 1);
		}
		for (idx = 0; idx < 2; idx++) {
			int v = idx ? eb : ea, nb = 4;

			if (!v) continue;
			while ((v >> (nb + 1)) != 0) nb++;	/* floor(log2 v) */
			EMIT((1u << (nb - 4 + 1)) - 2, (unsigned)(nb - 4 + 1));	/* nb - 4 ones and a zero */
			EMIT((unsigned)(v - (1 << nb)), (unsigned)nb);
		}
	}
	return bits;
}

/* the cheapest codebook of a band (0 = all zero) and its bits */
static int best_cb(const int16_t *q, int n, unsigned *bits, int fast)
{
	int i, m = 0, first, last, cb, best = 0;
	unsigned bb = ~0u;

	for (i = 0; i < n; i++) { int v = iabs(q[i]); if (v > m) m = v; }
	if (!m) { *bits = 0; return 0; }
	first = m <= 1 ? 1 : m <= 2 ? 3 : m <= 4 ? 5 : m <= 7 ? 7 : m <= 12 ? 9 : 11;
	last = first + (fast ? 1 : 3) > 11 ? 11 : first + (fast ? 1 : 3);	/* the search takes two candidates, the final pass four */
	for (cb = first; cb <= last; cb++) {
		unsigned b = band_code(NULL, q, n, cb);

		if (b < bb) { bb = b; best = cb; }
	}
	*bits = bb;
	return best;
}

/* quantize at sf, pick the codebooks: total bits of the access unit, cbs[] and *maxsfb for the writer */
static unsigned plan(struct aacenc *e, int sf, uint8_t *cbs, int *maxsfb, int fast)
{
	unsigned bits = 26 + 6, b, sfbits = aac_sfbits[60];
	int i, last = 0;

	quant(e, sf);
	for (i = 0; i < NBANDS; i++) {
		cbs[i] = (uint8_t)best_cb(e->q + aac_swb8k[i], aac_swb8k[i + 1] - aac_swb8k[i], &b, fast);
		if (cbs[i]) { last = i + 1; bits += b + sfbits; }
	}
	*maxsfb = last;
	for (i = 0; i < last;) {			/* sections: runs of one codebook */
		int j = i;

		while (j < last && cbs[j] == cbs[i]) j++;
		bits += 4 + 5u * (unsigned)((j - i) / 31 + 1);
		i = j;
	}
	return bits;
}

static unsigned emit(struct aacenc *e, int sf, const uint8_t *cbs, int maxsfb, uint8_t *out)
{
	struct bw bw, *w = &bw;
	unsigned bits = 0;
	int i;

	bw.p = out; bw.pos = 0;
	EMIT(0, 3); EMIT(0, 4);				/* SCE, instance 0 */
	EMIT((unsigned)sf, 8);				/* global gain */
	EMIT(0, 1); EMIT(0, 2); EMIT(0, 1);		/* reserved, ONLY_LONG, sine window */
	EMIT((unsigned)maxsfb, 6); EMIT(0, 1);		/* max_sfb, no predictor */
	for (i = 0; i < maxsfb;) {			/* section data */
		int j = i, len;

		while (j < maxsfb && cbs[j] == cbs[i]) j++;
		EMIT(cbs[i], 4);
		for (len = j - i; len >= 31; len -= 31) EMIT(31, 5);
		EMIT((unsigned)len, 5);
		i = j;
	}
	for (i = 0; i < maxsfb; i++)			/* scale factors: all equal to the global gain, delta 0 */
		if (cbs[i]) EMIT(aac_sfcode[60], aac_sfbits[60]);
	EMIT(0, 3);					/* no pulse, no TNS, no gain control */
	for (i = 0; i < maxsfb; i++)
		if (cbs[i]) bits += band_code(w, e->q + aac_swb8k[i], aac_swb8k[i + 1] - aac_swb8k[i], cbs[i]);
	EMIT(7, 3);					/* ID_END */
	(void)bits;
	return (bw.pos + 7) / 8;
}

/* ---- the frame ----------------------------------------------------------------------------------------------- */
#define SF_MAX	255

static int encode_frame(struct aacenc *e, uint8_t *out)
{
	uint8_t cbs[NBANDS];
	int i, lo, hi, maxsfb, sf;
	unsigned bits, budget, n;

	mdct(e);
	{
		/* below ythr a line quantizes to 0 even at the finest step: no power needed (most of the high lines of speech) */
		uint32_t ythr, lo_y = 0, hi_y = 1u << 30;
		int k = e->sf_floor - 88;
		unsigned sh = 22 + 3u * (unsigned)(k >> 4);
		uint64_t g = g16[k & 15], rnd = (13285ULL << sh) >> 15;

		while (hi_y - lo_y > 1) {
			uint32_t mid_y = lo_y + (hi_y - lo_y) / 2;

			if (((pow34(mid_y) * g + rnd) >> sh) >= 1) hi_y = mid_y; else lo_y = mid_y;
		}
		ythr = hi_y;
		for (i = 0; i < M; i++) {
			int32_t x = e->X[i];
			uint32_t y = (uint32_t)(x < 0 ? -x : x);

			e->P[i] = y < ythr ? 0 : pow34(y);
		}
	}
	budget = (unsigned)(e->bits_frame + (e->credit < e->bits_frame ? e->credit : e->bits_frame));
	if (budget > 8u * (AAC_OUT_MAX - 8)) budget = 8u * (AAC_OUT_MAX - 8);
	lo = e->sf_floor; hi = SF_MAX;
	if (plan(e, lo, cbs, &maxsfb, 1) <= budget) {
		hi = lo;
	} else {					/* smallest sf in (lo, hi] inside the budget: gallop from the last frame's, then bisect */
		int p = e->last_sf > lo ? e->last_sf : lo + 4, step = 4;

		if (plan(e, p, cbs, &maxsfb, 1) <= budget) {
			hi = p;
			while (hi - step > lo) {
				if (plan(e, hi - step, cbs, &maxsfb, 1) > budget) { lo = hi - step; break; }
				hi -= step; step *= 2;
			}
		} else {
			lo = p;
			while (lo + step < SF_MAX) {
				if (plan(e, lo + step, cbs, &maxsfb, 1) <= budget) { hi = lo + step; break; }
				lo += step; step *= 2;
			}
		}
		while (hi - lo > 1) {
			int mid = (lo + hi) / 2;

			if (plan(e, mid, cbs, &maxsfb, 1) <= budget) hi = mid; else lo = mid;
		}
	}
	sf = hi;
	bits = plan(e, sf, cbs, &maxsfb, 0);
	n = emit(e, sf, cbs, maxsfb, out);
	e->credit += e->bits_frame - (int)bits;
	if (e->credit < 0) e->credit = 0;
	if (e->credit > 2 * e->bits_frame) e->credit = 2 * e->bits_frame;
	e->last_bits = bits; e->last_sf = sf;
	memcpy(e->hist, e->cur, sizeof e->hist);
	return (int)n;
}

void aacenc_reset(struct aacenc *e)
{
	memset(e->hist, 0, sizeof e->hist);
	e->fill = 0;
	e->credit = 0;
}

void aacenc_init(struct aacenc *e, unsigned bitrate)
{
	tabs_init();
	memset(e, 0, sizeof *e);
	if (bitrate < 8000) bitrate = 8000;
	if (bitrate > 48000) bitrate = 48000;
	e->bits_frame = (int)(bitrate * AAC_FRAME / AAC_RATE);
	e->sf_floor = 136;
}

int aacenc_feed(struct aacenc *e, const int16_t *pcm, int n, uint8_t *out)
{
	int k = AAC_FRAME - e->fill, r = 0;

	if (n > AAC_FRAME) n = AAC_FRAME;
	if (n < k) k = n;
	memcpy(e->cur + e->fill, pcm, (size_t)k * sizeof *pcm);
	e->fill += k;
	if (e->fill == AAC_FRAME) {
		r = encode_frame(e, out);
		e->fill = 0;
		memcpy(e->cur, pcm + k, (size_t)(n - k) * sizeof *pcm);
		e->fill = n - k;
	}
	return r;
}

int16_t aac_alaw(unsigned char a)
{
	int t, seg;

	a ^= 0x55;
	t = (a & 0x0f) << 4;
	seg = (a & 0x70) >> 4;
	if (seg == 0) t += 8;
	else { t += 0x108; if (seg > 1) t <<= seg - 1; }
	return (int16_t)((a & 0x80) ? t : -t);
}
