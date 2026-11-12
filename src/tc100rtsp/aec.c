/* aec.c: acoustic echo cancellation for the two-way audio of tc100_rtsp (plan 3 of docs/linux-port/plans-2026-11-12.md).
 * 8 kHz mono, integers only (no libm, no floats), Q15 step size and Q28 weights.
 *
 * - far end ring (1 s) fed with the samples written to the speaker, through a linear resampler when the speaker clock
 *   and the microphone clock differ (aec_set_ratio: an adaptive filter cannot follow a fixed skew of 1600 ppm);
 * - bulk delay: aec_align() sets where the reference starts (speaker queue / ratio + unread microphone frames + a
 *   constant); it moves the reference only when it is off by more than 96 samples (the queue is read by period, 16 ms)
 *   and then shifts the weights with it, so what was learned is kept;
 * - NLMS filter (256 taps by default, up to 512): y = w.x, e = mic - y, w += mu e x / (|x|^2 + reg), running window
 *   energy kept exactly in integers; adaptation only while the far end is active and no double talk is suspected;
 * - double talk: Geigel test, |mic| > L1(w) x peak of the reference (L1 of the weights is a bound of the echo gain; at
 *   least 0.5), switched on once the filter has learned for one second of far end; adaptation then stops for 100 ms
 *   after the last trigger. A divergence guard resets the weights when the error is clearly above the microphone;
 * - residual suppressor: gain 0 to -18 dB from the ratio of the error power to the power of the echo estimate (error
 *   far below the estimate: only residual echo left, full attenuation; error as large as the estimate: someone
 *   talks, none), faster down than up, only while the far end is active (150 ms hangover after it stops).
 */
#include <stdlib.h>
#include <string.h>
#include "aec.h"

#define RING 8192
#define RMASK (RING - 1)
#define MAXDELAY 7000		/* queued + unread + d0, samples: the ring must also hold the taps */
#define Q24 (1 << 24)
#define WMAX (3 << 28)		/* weights Q28: +-3 */
#define UNITY 4096
#define HANG 1200		/* 150 ms of far end hangover (reverberation tail and the delay estimate) */
#define DTHOLD 800		/* 100 ms of frozen adaptation after a double talk trigger */
#define LEARN 8000		/* 1 s of far end before the double talk test is used */
#define TOL 96			/* the reference is moved when the delay estimate is off by more than this */
#define MU 13107		/* step size 0.4, Q15 */
#define REG 64			/* regularisation, per tap: the energy of a far end of rms 8 */
#define ETHR 1024		/* far end active when the mean square of the window is above this (rms 32, -60 dBFS) */
#define EFMAX 12000		/* longest freeze by the error test, 1.5 s (then slow adaptation) */
#define GMAX (1 << 22)		/* largest step factor: keeps one update of a weight below 2^29 */
#define PYMIN 2500		/* the echo estimate counts when its mean square is above this (rms 50) */

struct aec {
	int taps, supp;
	uint32_t ratio;				/* far frames per microphone frame, Q24 */
	int d0;
	int16_t ring[RING];
	uint32_t wp, rp;			/* samples in the ring / index of the reference for the next microphone sample */
	int32_t w[AEC_TAPS_MAX];
	int64_t energy;				/* sum of the squares of the window ring[rp-taps .. rp-1] (before the sample at rp is added) */
	int64_t en_blk;				/* the energy the step normalisation r was computed with */
	int32_t r;				/* NLMS step normalisation, mu / energy, Q8 of the Q28 weight scale: one division per block */
	int live, resync, hold, dt, learn, n64, efrun, blk, tgl;
	int32_t fp, l1;				/* peak follower of the reference, L1 norm of the weights (Q8) */
	int32_t pm, pe, py;			/* smoothed powers: microphone, error, echo estimate */
	int32_t sg, sgt;			/* suppressor gain and its target, Q12 */
	uint32_t pos;				/* resampler: position of the next output after prev, Q24 */
	int prev;
	unsigned resets, realigns;
};

struct aec *aec_new(int taps)
{
	struct aec *a = calloc(1, sizeof *a);

	if (!a) return NULL;
	a->taps = taps < 32 ? (taps <= 0 ? AEC_TAPS_DEFAULT : 32) : taps > AEC_TAPS_MAX ? AEC_TAPS_MAX : taps;
	a->supp = 1;
	a->ratio = Q24;
	a->sg = a->sgt = UNITY;
	a->l1 = 128;
	a->resync = 1;
	return a;
}

void aec_free(struct aec *a) { free(a); }

void aec_reset(struct aec *a)
{
	memset(a->ring, 0, sizeof a->ring);
	memset(a->w, 0, sizeof a->w);
	a->wp = a->rp = 0; a->energy = 0; a->en_blk = 0; a->r = 0; a->blk = 0; a->tgl = 0;
	a->live = 0; a->resync = 1; a->hold = a->dt = a->learn = a->n64 = a->efrun = 0;
	a->fp = 0; a->l1 = 128; a->pm = a->pe = a->py = 0;
	a->sg = a->sgt = UNITY;
	a->pos = 0; a->prev = 0;
}

int aec_set_ratio(struct aec *a, const char *spec)
{
	long num = 0, den = 0;
	const char *p = spec;
	int neg = 0, any = 0;
	int64_t r;

	a->ratio = Q24;
	if (!spec || !*spec) return 0;
	if (*p == '+' || *p == '-') { neg = *p == '-'; p++; }
	while (*p >= '0' && *p <= '9') { num = num * 10 + (*p++ - '0'); any = 1; if (num > 100000000) return -1; }
	if (!any) return -1;
	if (*p == '/') {
		if (neg) return -1;
		for (p++; *p >= '0' && *p <= '9'; p++) { den = den * 10 + (*p - '0'); if (den > 100000000) return -1; }
		if (*p || den <= 0) return -1;
		r = ((int64_t)num << 24) / den;
	} else {
		if (*p || num > 20000) return -1;
		r = Q24 + (((int64_t)(neg ? -num : num) << 24) / 1000000);
	}
	if (r < Q24 - Q24 / 50 || r > Q24 + Q24 / 50) return -1;	/* 2 % either way at most */
	a->ratio = (uint32_t)r;
	return 0;
}

void aec_set_d0(struct aec *a, int samples) { a->d0 = samples < 0 ? 0 : samples > 4000 ? 4000 : samples; }
void aec_set_suppressor(struct aec *a, int on) { a->supp = on != 0; }
int aec_far_active(const struct aec *a) { return a->hold > 0; }

void aec_counters(const struct aec *a, unsigned *resets, unsigned *realigns)
{
	if (resets) *resets = a->resets;
	if (realigns) *realigns = a->realigns;
}

static void push(struct aec *a, int v)
{
	a->ring[a->wp & RMASK] = (int16_t)v;
	a->wp++;
}

void aec_far(struct aec *a, const int16_t *x, int n)
{
	int i;

	if (a->ratio == Q24) {
		for (i = 0; i < n; i++) push(a, x[i]);
		return;
	}
	for (i = 0; i < n; i++) {
		int c = x[i];

		while (a->pos < Q24) {
			push(a, a->prev + (int)(((int64_t)(c - a->prev) * a->pos) >> 24));
			a->pos += a->ratio;
		}
		a->pos -= Q24;
		a->prev = c;
	}
}

static void window_energy(struct aec *a)
{
	int k;

	a->energy = 0;
	for (k = 1; k <= a->taps; k++) {		/* rp itself is added by aec_process */
		int x = a->ring[(a->rp - (uint32_t)k) & RMASK];

		a->energy += (int64_t)x * x;
	}
}

/* the reference moves by diff samples (positive: later): the echo path moves the other way along the filter */
static void shift_weights(struct aec *a, int diff)
{
	int n = a->taps, d = diff < 0 ? -diff : diff;

	if (d >= n) { memset(a->w, 0, sizeof a->w); a->learn = 0; return; }
	if (diff > 0) {
		memmove(a->w + d, a->w, (size_t)(n - d) * sizeof a->w[0]);
		memset(a->w, 0, (size_t)d * sizeof a->w[0]);
	} else {
		memmove(a->w, a->w + d, (size_t)(n - d) * sizeof a->w[0]);
		memset(a->w + n - d, 0, (size_t)d * sizeof a->w[0]);
	}
}

void aec_align(struct aec *a, int queued, int unread)
{
	int64_t q, delay;
	uint32_t target;

	if (queued < 0) { a->live = 0; return; }
	if (!a->live) { a->live = 1; a->resync = 1; }
	q = a->ratio == Q24 ? queued : ((int64_t)queued << 24) / a->ratio;
	delay = q + (unread < 0 ? 0 : unread) + a->d0;
	if (delay > MAXDELAY) delay = MAXDELAY;
	target = a->wp - (uint32_t)delay;		/* wp and rp wrap at 2^32: only differences are used */
	if (a->resync) {
		a->rp = target;
		window_energy(a);
		a->resync = 0;
		return;
	}
	{
		int32_t diff = (int32_t)(target - a->rp);

		if (diff > TOL || diff < -TOL) {
			if (diff > RING / 2 || diff < -RING / 2) diff = diff > 0 ? RING / 2 : -RING / 2;
			shift_weights(a, (int)diff);
			a->rp += (uint32_t)diff;
			window_energy(a);
			a->realigns++;
		}
	}
}

static int clip16(int64_t v) { return v > 32767 ? 32767 : v < -32768 ? -32768 : (int)v; }

int aec_process(struct aec *a, int m)
{
	int n = a->taps, k, e, y = 0, active;
	int32_t x0, xo;
	int16_t tmp[AEC_TAPS_MAX];
	const int16_t *xw;
	int64_t acc;

	if (!a->live && a->hold <= 0 && a->sg >= UNITY) return m;
	while ((int32_t)(a->wp - a->rp) <= 0) push(a, 0);	/* nothing queued: the far end is silent */
	x0 = a->ring[a->rp & RMASK];
	xo = a->ring[(a->rp - (uint32_t)n) & RMASK];
	a->energy += (int64_t)x0 * x0 - (int64_t)xo * xo;
	if (a->energy < 0) a->energy = 0;
	if (a->energy > (int64_t)ETHR * n) a->hold = HANG;
	else if (a->hold > 0) a->hold--;
	active = a->hold > 0;

	a->pm += (int32_t)((((int64_t)m * m) - a->pm) >> 6);
	if (active) {
		if ((a->rp & RMASK) >= (uint32_t)(n - 1)) xw = a->ring + (a->rp & RMASK);
		else {
			for (k = 0; k < n; k++) tmp[n - 1 - k] = a->ring[(a->rp - (uint32_t)k) & RMASK];
			xw = tmp + n - 1;
		}
		acc = 0;
		for (k = 0; k < n; k++) acc += (int64_t)a->w[k] * xw[-k];
		y = clip16(acc >> 28);
		e = clip16((int64_t)m - y);
		a->pe += (int32_t)((((int64_t)e * e) - a->pe) >> 6);
		a->py += (int32_t)((((int64_t)y * y) - a->py) >> 6);

		/* peak follower and double talk */
		{
			int ax = x0 < 0 ? -x0 : x0;

			if (ax > a->fp) a->fp = ax; else a->fp -= (a->fp >> 8) + (a->fp > 0);
		}
		if (++a->n64 >= 64) {
			int64_t sum = 0;

			a->n64 = 0;
			for (k = 0; k < n; k++) {
				int32_t wk = a->w[k];

				if (wk > WMAX) wk = a->w[k] = WMAX; else if (wk < -WMAX) wk = a->w[k] = -WMAX;
				sum += wk < 0 ? -(int64_t)wk : wk;
			}
			sum >>= 20;
			a->l1 = sum > 4096 ? 4096 : (int32_t)sum;
			/* divergence: the error is well above the microphone while the filter should be helping */
			if (a->learn > 2000 && a->pm > 20000 && a->pe > 2 * (int64_t)a->pm) {
				memset(a->w, 0, sizeof a->w);
				a->learn = 0; a->efrun = 0; a->resets++;
			}
		}
		if (a->learn >= LEARN) {
			int64_t g = a->l1 < 128 ? 128 : a->l1, thr = (a->fp * g) >> 8;

			if (m > thr || -m > thr) a->dt = DTHOLD;
			/* the error is not far below the echo estimate: someone talks near the camera (or the room changed:
			 * after 1.5 s of it the filter goes on adapting, sixteen times slower) */
			if (a->py > PYMIN && (int64_t)a->pe * 4 > a->py) {
				if (a->efrun < EFMAX) { a->efrun++; a->dt = DTHOLD; }
			} else if (a->efrun > 0) a->efrun--;
		}
		if (a->dt > 0) a->dt--;
		else if (a->energy > (int64_t)ETHR * n) {
			if (a->learn < LEARN) a->learn++;
			/* the step normalisation (one 64-bit division) once per 16 samples, again at once when the energy doubles
			 * (a burst starts); the update itself runs on every second sample with twice the step */
			if (--a->blk <= 0 || a->energy > 2 * a->en_blk) {
				int64_t rr;

				a->en_blk = a->energy + (int64_t)REG * n;
				rr = (((int64_t)MU << 29)) / a->en_blk;		/* MU Q15 << 21 (Q28 weights, Q-8 shift) << 8 */
				a->r = (int32_t)(rr > 0x3fffffff ? 0x3fffffff : rr);
				a->blk = 16;
			}
			if ((a->tgl ^= 1)) {
				int64_t g = ((int64_t)e * a->r) >> 7;		/* twice mu e / energy, scaled for the shift below */

				if (a->efrun >= EFMAX) g >>= 4;
				if (g > GMAX) g = GMAX; else if (g < -GMAX) g = -GMAX;
				{
					const int32_t g32 = (int32_t)g;

					for (k = 0; k < n; k++) a->w[k] += (int32_t)(((int64_t)g32 * xw[-k]) >> 8);
				}
			}
		}

		/* suppressor target: from the error to echo estimate power ratio (x256), every 8th sample */
		if (!(a->n64 & 7)) {
			a->sgt = UNITY;
			if (a->supp && a->dt <= 0 && a->py > PYMIN) {
				int64_t q = ((int64_t)a->pe << 8) / ((int64_t)a->py + 1);

				if (q <= 32) a->sgt = UNITY / 8;
				else if (q < 128) a->sgt = UNITY / 8 + (int32_t)((UNITY - UNITY / 8) * (q - 32) / 96);
			}
		}
	} else {
		e = m;
		a->pe = a->pm; a->py = 0; a->dt = 0;
		a->sgt = UNITY;
	}
	if (a->sgt < a->sg) a->sg -= (a->sg - a->sgt + 31) >> 5;	/* down in ~4 ms */
	else a->sg += (a->sgt - a->sg + 255) >> 8;			/* up in ~30 ms */
	a->rp++;
	return a->sg >= UNITY ? e : clip16(((int64_t)e * a->sg) >> 12);
}
