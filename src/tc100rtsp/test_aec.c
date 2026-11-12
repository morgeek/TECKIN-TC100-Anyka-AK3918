/* test_aec: host test of aec.c (make test_aec; tests/test_tc100rtsp.py runs it). Prints "all OK" or the failures.
 *
 *   test_aec                          the synthetic cases below
 *   test_aec -f far.raw mic.raw [ratio [d0 [queued]]]  (ratio "" = 1.0)
 *                                     offline evaluation of a measurement of the camera (docs/linux-port/audio-aec-measure.md):
 *                                     far.raw = what was played, mic.raw = what was recorded (both S16_LE mono 8 kHz,
 *                                     aligned at their start), ratio as RTSP_AUDIO_AEC_RATIO, d0 and queued in samples
 *                                     (default 0 and 0); prints the echo reduction per second.
 *
 * Synthetic echo: far end = coloured noise (rms 4000) with speech-like pauses, played through a loudspeaker with a cubic
 * term reaching 5 % of the signal at 3 sigma, a decaying room response of 20 ms (160 taps), a bulk delay of 40 ms
 * (320 samples; the speaker queue is reported as 300), and the microphone. */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "aec.h"

static int fails;
static uint32_t rs = 12345;

static void check(int ok, const char *what, double v)
{
	printf("%s %s (%.2f)\n", ok ? "ok  " : "FAIL", what, v);
	if (!ok) fails++;
}

static double rnd(void)		/* uniform -1..1 */
{
	rs ^= rs << 13; rs ^= rs >> 17; rs ^= rs << 5;
	return (double)(int32_t)rs / 2147483648.0;
}

static double gauss(void)
{
	double s = 0;
	int i;

	for (i = 0; i < 12; i++) s += rnd();
	return s / 2;			/* variance 1 */
}

/* coloured noise: one-pole low-pass (corner ~1.2 kHz) so the linear interpolation of the skew case is accurate */
static void noise(double *x, int n, double rms, double pole)
{
	double y = 0, sum = 0;
	int i;

	for (i = 0; i < n; i++) { y = pole * y + gauss(); x[i] = y; sum += y * y; }
	sum = sqrt(sum / n);
	for (i = 0; i < n; i++) x[i] *= rms / sum;
}

#define HLEN 160
static double h[HLEN];

static void make_h(void)
{
	int k;
	double e = 0;

	for (k = 0; k < HLEN; k++) { h[k] = rnd() * exp(-4.0 * k / HLEN); e += h[k] * h[k]; }
	for (k = 0; k < HLEN; k++) h[k] *= 0.45 / sqrt(e);	/* echo rms = 0.45 of the far end */
}

static double spk(double x) { double u = x / 12000.0; return x + 0.05 * 12000.0 * u * u * u; }

/* far-end signal as a function of the DAC sample index, linear (frac) positions via 4-point Hermite */
static double far_at(const double *f, int n, double t)
{
	int i = (int)floor(t);
	double u = t - i, a, b, c, d;

	if (i < 1 || i + 2 >= n) return 0;
	a = f[i - 1]; b = f[i]; c = f[i + 1]; d = f[i + 2];
	return b + 0.5 * u * (c - a + u * (2 * a - 5 * b + 4 * c - d + u * (3 * (b - c) + d - a)));
}

#define BULK 320
#define QUEUED 300
#define D0 300			/* the filter is told 300: the true delay (320) is 2.5 ms off */
#define BLK 128

/* echo[n] = (h * spk(far(n * ratio - BULK * ratio)))(n), in microphone time */
static void make_echo(const double *f, int n, double ratio, double *echo, int bulk)
{
	int i, k;
	static double s[200000];

	for (i = 0; i < n; i++) s[i] = spk(far_at(f, n, i * ratio - bulk * ratio));
	for (i = 0; i < n; i++) {
		double a = 0;

		for (k = 0; k < HLEN && k <= i; k++) a += h[k] * s[i - k];
		echo[i] = a;
	}
}

static double power(const int16_t *x, int a, int b)
{
	double s = 0;
	int i;

	for (i = a; i < b; i++) s += (double)x[i] * x[i];
	return s / (b - a) + 1e-9;
}

static void run(struct aec *ac, const double *far, int n, const int16_t *mic, int16_t *out, int d0, double ratio)
{
	int pos, i;

	(void)d0;
	/* far end written up to (now + QUEUED); the microphone block [pos, pos + BLK) has just been read */
	{	/* the speaker queue holds QUEUED samples from the start */
		int16_t blk[BLK];
		int fw = 0;

		for (pos = 0; pos + BLK <= n; pos += BLK) {
			int upto = (int)floor((pos + BLK) * ratio) + QUEUED;	/* the speaker has consumed ratio frames per microphone frame */

			while (fw < upto) {
				int m = upto - fw > BLK ? BLK : upto - fw;

				for (i = 0; i < m; i++) blk[i] = (int16_t)lrint(fw + i < n ? far[fw + i] : 0);
				aec_far(ac, blk, m);
				fw += m;
			}
			aec_align(ac, QUEUED, BLK);
			for (i = 0; i < BLK; i++) out[pos + i] = (int16_t)aec_process(ac, mic[pos + i]);
		}
	}
}

static void speechlike(double *f, int n)		/* noise with envelope: 300 ms on, 100 ms pauses */
{
	int i;

	noise(f, n, 4000, 0.6);
	for (i = 0; i < n; i++) {
		int ph = i % 3200;

		if (ph >= 2400) f[i] *= 0.0;
	}
}

static int16_t *to16(const double *x, int n)
{
	int16_t *r = malloc((size_t)n * 2);
	int i;

	for (i = 0; i < n; i++) { double v = lrint(x[i]); r[i] = (int16_t)(v > 32767 ? 32767 : v < -32768 ? -32768 : v); }
	return r;
}

/* near-end loss: projection of the output on the near-end signal, in dB */
static double proj_db(const int16_t *out, const double *near, int a, int b)
{
	double xy = 0, xx = 1e-9;
	int i;

	for (i = a; i < b; i++) { xy += out[i] * near[i]; xx += near[i] * near[i]; }
	return 20 * log10(fabs(xy / xx) + 1e-9);
}

static void synthetic(void)
{
	enum { N = 8000 * 14 };
	static double far[N], echo[N], near[N];
	static int16_t out[N], mic[N];
	struct aec *ac;
	double erle, loss, e1, e2;
	int i;
	int16_t *m16;

	rs = 12345;
	make_h();
	speechlike(far, N);
	make_echo(far, N, 1.0, echo, BULK);

	/* single talk, 0 to 4 s: echo reduction in the 2nd to 3rd second and in the 3rd to 4th, linear filter alone and all */
	m16 = to16(echo, N);
	memcpy(mic, m16, sizeof mic); free(m16);
	ac = aec_new(256); aec_set_d0(ac, D0); aec_set_suppressor(ac, 0);
	run(ac, far, 4 * 8000, mic, out, 0, 1.0);
	erle = 10 * log10(power(mic, 16000, 24000) / power(out, 16000, 24000));
	check(erle >= 20, "echo reduction after 2 s, linear filter only (dB)", erle);
	aec_free(ac);
	ac = aec_new(256); aec_set_d0(ac, D0);
	run(ac, far, 4 * 8000, mic, out, 0, 1.0);
	erle = 10 * log10(power(mic, 16000, 24000) / power(out, 16000, 24000));
	check(erle >= 20, "echo reduction after 2 s, with the suppressor (dB)", erle);
	erle = 10 * log10(power(mic, 24000, 32000) / power(out, 24000, 32000));
	check(erle >= 20, "echo reduction in the 4th second (dB)", erle);
	aec_free(ac);

	/* double talk: converge 3 s, near end (rms 3000, uncorrelated) joins from 3 s to 6 s, then single talk again */
	noise(near, N, 3000, 0.5);
	for (i = 0; i < 3 * 8000; i++) near[i] = 0;
	for (i = 6 * 8000; i < N; i++) near[i] = 0;
	for (i = 0; i < N; i++) { double v = lrint(echo[i] + near[i]); mic[i] = (int16_t)(v > 32767 ? 32767 : v < -32768 ? -32768 : v); }
	ac = aec_new(256); aec_set_d0(ac, D0);
	run(ac, far, 8 * 8000, mic, out, 0, 1.0);
	loss = proj_db(out, near, 4 * 8000, 6 * 8000);
	check(loss > -3 && loss < 1, "near end kept in double talk (dB, > -3)", loss);
	e1 = 10 * log10(power(mic, 7 * 8000, 8 * 8000) / power(out, 7 * 8000, 8 * 8000));
	check(e1 >= 20, "no divergence: echo reduction 1 s after the double talk (dB)", e1);
	{
		unsigned rst;

		aec_counters(ac, &rst, NULL);
		check(rst == 0, "no reset of the filter", rst);
	}
	aec_free(ac);

	/* delay jump: the echo comes 10 ms (80 samples) later after 3 s, nothing told to the filter */
	{
		static double echo2[N], late[N];
		int cut = 3 * 8000;

		make_echo(far, N, 1.0, echo2, BULK + 80);
		for (i = 0; i < N; i++) late[i] = i < cut ? echo[i] : echo2[i];
		m16 = to16(late, N);
		memcpy(mic, m16, sizeof mic); free(m16);
		ac = aec_new(256); aec_set_d0(ac, D0);
		run(ac, far, 8 * 8000, mic, out, 0, 1.0);
		e1 = 10 * log10(power(mic, cut, cut + 4000) / power(out, cut, cut + 4000));
		e2 = 10 * log10(power(mic, cut + 3 * 8000, cut + 4 * 8000) / power(out, cut + 3 * 8000, cut + 4 * 8000));
		check(e2 >= 20, "re-converged 3 s after a 10 ms delay jump (dB)", e2);
		printf("     (first 0.5 s after the jump: %.1f dB)\n", e1);
		aec_free(ac);
	}

	/* skew: the speaker clock is 1600 ppm (625/624) faster than the microphone clock; 12 s, delay not re-estimated */
	{
		static double echo3[N];
		double e_off, e_on;

		make_echo(far, N, 625.0 / 624.0, echo3, BULK);
		m16 = to16(echo3, N);
		memcpy(mic, m16, sizeof mic); free(m16);
		ac = aec_new(256); aec_set_d0(ac, D0);
		run(ac, far, 12 * 8000, mic, out, 0, 625.0 / 624.0);
		e_off = 10 * log10(power(mic, 10 * 8000, 12 * 8000) / power(out, 10 * 8000, 12 * 8000));
		aec_free(ac);
		ac = aec_new(256); aec_set_d0(ac, D0);
		check(aec_set_ratio(ac, "625/624") == 0, "ratio 625/624 accepted", 0);
		run(ac, far, 12 * 8000, mic, out, 0, 625.0 / 624.0);
		e_on = 10 * log10(power(mic, 10 * 8000, 12 * 8000) / power(out, 10 * 8000, 12 * 8000));
		aec_free(ac);
		ac = aec_new(256); aec_set_d0(ac, D0);
		check(aec_set_ratio(ac, "1600") == 0, "ratio 1600 ppm accepted", 0);
		run(ac, far, 12 * 8000, mic, out, 0, 625.0 / 624.0);
		erle = 10 * log10(power(mic, 10 * 8000, 12 * 8000) / power(out, 10 * 8000, 12 * 8000));
		aec_free(ac);
		check(e_off < 10, "skew 1600 ppm without resampling: echo stays (dB, < 10)", e_off);
		check(e_on >= 20, "skew 1600 ppm with 625/624: echo reduced (dB)", e_on);
		check(erle >= 20, "skew 1600 ppm given as ppm: echo reduced (dB)", erle);
	}

	/* a realign in the middle of speech must not leave the energy sum wrong: after the far end stops the filter work stops
	 * (hold expires) instead of running for ever (or the far end being taken for silent) */
	{
		static double nz[8000 * 6];
		int16_t blk[BLK], act_mid = 0, act_end = 1, pos, k;
		int fw = 0, p;

		noise(nz, 3 * 8000, 4000, 0.6);
		ac = aec_new(256); aec_set_d0(ac, D0);
		for (p = 0; p + BLK <= 5 * 8000; p += BLK) {
			int upto = p + BLK + QUEUED, q = QUEUED;

			if (p / BLK == 94 || p / BLK == 95) q = QUEUED + 200;		/* the queue jumps: two realigns */
			if (p / BLK == 95) upto = p + BLK + QUEUED + 200;
			while (fw < upto) {
				int m = upto - fw > BLK ? BLK : upto - fw;

				for (k = 0; k < m; k++) blk[k] = (int16_t)lrint(fw + k < 3 * 8000 ? nz[fw + k] : 0);
				aec_far(ac, blk, m);
				fw += m;
			}
			aec_align(ac, q, BLK);
			for (k = 0; k < BLK; k++) aec_process(ac, 0);
			if (p / BLK == 125) act_mid = (int16_t)aec_far_active(ac);
			if (p / BLK == 281) act_end = (int16_t)aec_far_active(ac);
		}
		pos = 0; (void)pos;
		check(act_mid == 1, "far end active during the speech, after the realigns", act_mid);
		check(act_end == 0, "hold expired 1.5 s after the far end stopped (no work for ever)", act_end);
		aec_free(ac);
	}

	/* ratio syntax */
	ac = aec_new(0);
	check(aec_set_ratio(ac, "") == 0 && aec_set_ratio(ac, "-800") == 0 && aec_set_ratio(ac, "+300") == 0, "ratio: empty, -800, +300", 0);
	check(aec_set_ratio(ac, "abc") < 0 && aec_set_ratio(ac, "5/0") < 0 && aec_set_ratio(ac, "3/2") < 0 &&
	      aec_set_ratio(ac, "30000") < 0 && aec_set_ratio(ac, "625/") < 0, "ratio: garbage and out of range refused", 0);
	aec_free(ac);

	/* far end silent: the microphone passes unchanged and nothing is processed */
	ac = aec_new(256);
	aec_align(ac, -1, 128);
	for (i = 0; i < 1000; i++) if (aec_process(ac, (i * 37) % 2000 - 1000) != (i * 37) % 2000 - 1000) break;
	check(i == 1000 && !aec_far_active(ac), "no far end: unchanged", i);
	aec_free(ac);
}

static int16_t *slurp(const char *p, int *n)
{
	FILE *f = fopen(p, "rb");
	int16_t *b;
	long sz;

	if (!f) { perror(p); exit(2); }
	fseek(f, 0, SEEK_END); sz = ftell(f); fseek(f, 0, SEEK_SET);
	b = malloc((size_t)sz + 2);
	*n = (int)fread(b, 2, (size_t)sz / 2, f);
	fclose(f);
	return b;
}

static int offline(int argc, char **argv)
{
	int nf, nm, n, pos, i, d0 = argc > 5 ? atoi(argv[5]) : 0, q = argc > 6 ? atoi(argv[6]) : 0, fw = 0;
	int16_t *far = slurp(argv[2], &nf), *mic = slurp(argv[3], &nm), blk[BLK];
	struct aec *ac = aec_new(256);
	double tot_in = 0, tot_out = 0, ratio = 1.0;

	if (argc > 4 && argv[4][0]) {
		if (aec_set_ratio(ac, argv[4])) { fprintf(stderr, "bad ratio %s\n", argv[4]); return 2; }
		if (strchr(argv[4], '/')) ratio = atof(argv[4]) / atof(strchr(argv[4], '/') + 1);
		else ratio = 1.0 + atof(argv[4]) / 1e6;
	}
	aec_set_d0(ac, d0);
	n = nm;
	for (pos = 0; pos + BLK <= n; pos += BLK) {
		int16_t out[BLK];
		double a = 0, b = 0;
		int upto = (int)floor((pos + BLK) * ratio) + q;	/* what the speaker has consumed, plus the queue */

		while (fw < upto) {
			int m = upto - fw > BLK ? BLK : upto - fw;

			for (i = 0; i < m; i++) blk[i] = fw + i < nf ? far[fw + i] : 0;
			aec_far(ac, blk, m);
			fw += m;
		}
		aec_align(ac, q, BLK);
		for (i = 0; i < BLK; i++) {
			out[i] = (int16_t)aec_process(ac, mic[pos + i]);
			a += (double)mic[pos + i] * mic[pos + i]; b += (double)out[i] * out[i];
		}
		tot_in += a; tot_out += b;
		if ((pos + BLK) % 8000 < BLK && pos > 0) {
			printf("t=%3d s: echo reduction %.1f dB\n", (pos + BLK) / 8000, 10 * log10((tot_in + 1) / (tot_out + 1)));
			tot_in = tot_out = 0;
		}
	}
	return 0;
}

int main(int argc, char **argv)
{
	if (argc > 3 && !strcmp(argv[1], "-f")) return offline(argc, argv);
	synthetic();
	printf(fails ? "%d FAILED\n" : "all OK\n", fails);
	return fails != 0;
}
