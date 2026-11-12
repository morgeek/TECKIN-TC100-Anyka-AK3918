/* test_adsp: host test of adsp.c (make test_adsp; tests/test_tc100rtsp.py runs it). Prints "all OK" or the failures. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "adsp.h"

static int fails;

static void check(int ok, const char *what, double v)
{
	printf("%s %s (%.2f)\n", ok ? "ok  " : "FAIL", what, v);
	if (!ok) fails++;
}

/* RMS in dBFS of the last half of n samples of a sine (frequency f, amplitude a) through d */
static double tone_db(struct adsp *d, double f, double a, int n, int speaker, int *peak)
{
	double sum = 0;
	int i, pk = 0;

	for (i = 0; i < n; i++) {
		int y = adsp_sample(d, (int)lrint(a * sin(2 * M_PI * f * i / 8000.0)), speaker);

		if (i >= n / 2) { sum += (double)y * y; if (abs(y) > pk) pk = abs(y); }
	}
	if (peak) *peak = pk;
	return 10 * log10(sum / (n / 2) / (32768.0 * 32768.0) + 1e-12);
}

int main(void)
{
	struct adsp d;
	double in, out, lo, hi;
	int pk;

	/* high-pass only: hum down, voice untouched */
	adsp_init(&d, 1, 0, 0);
	in = 20 * log10(10000 / 32768.0 / sqrt(2));
	out = tone_db(&d, 50, 10000, 16000, 0, NULL);
	check(in - out > 15, "50 Hz hum down more than 15 dB", in - out);
	adsp_init(&d, 1, 0, 0);
	out = tone_db(&d, 1000, 10000, 16000, 0, NULL);
	check(fabs(in - out) < 0.5, "1 kHz within 0.5 dB", in - out);
	{	/* a DC offset is removed: a constant 20000 for 1 s, the last half */
		double sum = 0;
		int i, y;

		adsp_init(&d, 1, 0, 0);
		for (i = 0; i < 8000; i++) { y = adsp_sample(&d, 20000, 0); if (i >= 4000) sum += (double)y * y; }
		out = 10 * log10(sum / 4000 / (32768.0 * 32768.0) + 1e-12);
		check(out < -60, "DC removed", out);
	}

	/* gate and level: quiet hiss lower, a quiet voice louder, a loud one not clipped hard */
	adsp_init(&d, 0, 1, 0);
	lo = tone_db(&d, 1000, 30, 16000, 0, NULL);			/* ~-61 dBFS */
	check(lo < 20 * log10(30 / 32768.0 / sqrt(2)) - 9, "below the gate: -12 dB", lo);
	adsp_init(&d, 0, 1, 0);
	in = 20 * log10(1000 / 32768.0 / sqrt(2));
	hi = tone_db(&d, 1000, 1000, 24000, 0, NULL);			/* ~-33 dBFS */
	check(hi - in > 12 && hi - in < 18.5, "quiet voice raised 12 to 18 dB", hi - in);
	adsp_init(&d, 0, 1, 0);
	tone_db(&d, 1000, 32000, 16000, 0, &pk);
	check(pk <= 32767 && pk > 8000, "loud input: no wrap, level kept", pk);

	/* far end active (echo canceller at work): the gain does not rise, and the two steps give what adsp_sample gives */
	adsp_init(&d, 0, 1, 0);
	d.hold = 1;
	hi = tone_db(&d, 1000, 1000, 24000, 0, NULL);
	check(fabs(hi - in) < 0.5, "hold: the level gain stays at x1", hi - in);
	{
		struct adsp d1, d2;
		int i, same = 1;

		adsp_init(&d1, 1, 1, 1);
		adsp_init(&d2, 1, 1, 1);
		for (i = 0; i < 4000; i++) {
			int v = (int)lrint(9000 * sin(2 * M_PI * 700 * i / 8000.0)) + (i * 7919 % 301);

			if (adsp_sample(&d1, v, i > 2000) != adsp_rest(&d2, adsp_hpf(&d2, v), i > 2000)) same = 0;
		}
		check(same, "adsp_hpf + adsp_rest = adsp_sample", same);
	}

	/* mute while the speaker plays, back after */
	adsp_init(&d, 0, 0, 1);
	out = tone_db(&d, 1000, 10000, 800, 1, NULL);			/* 100 ms with the speaker on */
	check(out < -60, "muted within 50 ms of the speaker", out);
	out = tone_db(&d, 1000, 10000, 4000, 0, NULL);
	check(out > 20 * log10(10000 / 32768.0 / sqrt(2)) - 1, "back after the speaker (within 1 dB)", out);

	/* everything off: the samples go through unchanged */
	adsp_init(&d, 0, 0, 0);
	check(!adsp_on(&d) && adsp_sample(&d, -1234, 1) == -1234, "off: unchanged", 0);

	printf(fails ? "%d FAILED\n" : "all OK\n", fails);
	return fails != 0;
}
