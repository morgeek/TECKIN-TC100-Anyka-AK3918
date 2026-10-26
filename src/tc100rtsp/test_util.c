/* Host test of util.h (RTSP path -> stream, dBFS level meter, motion zones). make test_util && ./test_util */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include "util.h"

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); fails++; } } while (0)

static int ref_rms_db(const short *s, int n)	/* the 2.x formula, with libm */
{
	double sum = 0, sq = 0, mean, var, rms;
	int i;

	for (i = 0; i < n; i++) { sum += s[i]; sq += (double)s[i] * s[i]; }
	mean = sum / n; var = sq / n - mean * mean; rms = var > 0 ? sqrt(var) : 0;
	return rms > 0.5 ? (int)lrint(20.0 * log10(rms / 32768.0)) : -96;
}

int main(void)
{
	static short pcm[8000];
	struct lvl l;
	int i, k;

	/* paths */
	CHECK(url_is_sub("rtsp://192.168.1.5:554/video1_unicast"));
	CHECK(url_is_sub("rtsp://192.168.1.5/video1"));
	CHECK(url_is_sub("rtsp://192.168.1.5/video1/track1"));
	CHECK(url_is_sub("rtsp://cam/ch1"));
	CHECK(url_is_sub("rtsp://cam/ch1/track1"));
	CHECK(url_is_sub("rtsp://user:pw@cam:8554/sub"));
	CHECK(url_is_sub("rtsp://cam/SUB?x=1"));
	CHECK(url_is_sub("rtsp://cam/live/video1_stream"));
	CHECK(!url_is_sub("rtsp://cam/video0_unicast"));
	CHECK(!url_is_sub("rtsp://cam/"));
	CHECK(!url_is_sub("rtsp://cam"));
	CHECK(!url_is_sub("rtsp://cam/ch0"));
	CHECK(!url_is_sub("rtsp://cam/ch10"));
	CHECK(!url_is_sub("rtsp://cam/subway"));
	CHECK(!url_is_sub("rtsp://cam/unicast"));
	CHECK(!url_is_sub("rtsp://cam/video0?x=video1"));	/* the query is not the path */
	CHECK(url_is_sub("/video1"));

	/* log10 without libm */
	{ double x; for (x = 1; x < 4e18; x = x * 3 + 1) CHECK(fabs(log10_d(x) - log10(x)) < 1e-9); }
	CHECK(fabs(log10_d(0.001) + 3) < 1e-9);

	/* level: sine, square, DC only, silence, noise; against the 2.x formula */
	for (k = 0; k < 6; k++) {
		srand(k);
		for (i = 0; i < 8000; i++) {
			double v;

			switch (k) {
			case 0: v = 16384 * sin(i * 2 * M_PI * 440 / 8000); break;
			case 1: v = (i / 10) & 1 ? 32767 : -32767; break;
			case 2: v = -1450; break;
			case 3: v = 0; break;
			case 4: v = -1450 + (rand() % 201) - 100; break;
			default: v = -1450 + 3000 * sin(i * 0.05); break;
			}
			pcm[i] = (short)lrint(v);
		}
		lvl_reset(&l);
		for (i = 0; i < 8000; i++) lvl_add(&l, pcm[i]);
		printf("level %d: rms %d dBFS (2.x %d), peak %d dBFS\n", k, lvl_rms_db(&l), ref_rms_db(pcm, 8000), lvl_peak_db(&l));
		CHECK(abs(lvl_rms_db(&l) - ref_rms_db(pcm, 8000)) <= 0);
	}
	{	/* four 0.25 s windows merged = the whole second */
		struct lvl w, s;

		lvl_reset(&s);
		for (k = 0; k < 4; k++) {
			lvl_reset(&w);
			for (i = k * 2000; i < (k + 1) * 2000; i++) lvl_add(&w, pcm[i]);
			lvl_merge(&s, &w);
		}
		CHECK(s.n == 8000 && lvl_rms_db(&s) == ref_rms_db(pcm, 8000));
	}
	lvl_reset(&l);
	CHECK(lvl_rms_db(&l) == -96 && lvl_peak_db(&l) == -96);
	lvl_reset(&l); for (i = 0; i < 100; i++) lvl_add(&l, i & 1 ? 16384 : -16384);
	CHECK(lvl_rms_db(&l) == -6 && lvl_peak_db(&l) == -6);

	/* zones */
	{
		int z[4][4], n = 0, w;
		unsigned char m[64 * 36];
		static const char *lines[] = { "MDZ1=\"0,0,50,100\"\n", "MDZ2=10,10,20,20\r\n", "MDZ3=\"50,0,40,10\"\n",
					       "MDZ5=\"0,0,10,10\"\n", "MDZ1=\"0,0,101,10\"\n", "# comment\n", "MDZ4=\"1,2,3\"\n",
					       "MDZ4=\"0,90,100,100\"" };

		for (i = 0; i < 8; i++) if (n < 4 && mdz_parse_line(lines[i], z[n])) n++;
		CHECK(n == 3);
		CHECK(z[0][0] == 0 && z[0][2] == 50 && z[1][1] == 10 && z[2][1] == 90);
		w = mdz_mask(m, 64, 36, z, 0);
		CHECK(w == 64 * 36);
		w = mdz_mask(m, 64, 36, z, 1);		/* left half */
		CHECK(w == 32 * 36 && m[0] == 0 && m[63] == 1 && m[31] == 0 && m[32] == 1);
		w = mdz_mask(m, 64, 36, z, 3);
		printf("zones: %d of %d cells watched\n", w, 64 * 36);
		CHECK(w < 32 * 36 && w > 0);
		/* the 2.x md.c rule for the cell centre: (2x+1)*50/w percent */
		{
			int zz[1][4] = { { 0, 0, 100, 100 } };

			CHECK(mdz_mask(m, 64, 36, zz, 1) == 0);
		}
	}
	/* sensitivity: same decision as before the zones (2304 cells) */
	CHECK(md_triggered(12, 2304, 100) == 1 && md_triggered(11, 2304, 100) == 0);	/* 0.5 % */
	CHECK(md_triggered(104, 2304, 60) == 1 && md_triggered(103, 2304, 60) == 0);	/* 4.5 % */
	CHECK(md_triggered(10, 0, 100) == 0);
	CHECK(md_triggered(3, 100, 100) == 1);		/* fewer watched cells: a smaller count is enough */

	printf(fails ? "%d FAILED\n" : "util: all OK\n", fails);
	return fails != 0;
}
