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

	/* idle frame rate: off, needs motion detection, waits idle_after, never while recording continuously */
	CHECK(idle_fps_now(15, 0, 10, 1, 0, 100, 0) == 15);		/* IDLE_FPS=0: off */
	CHECK(idle_fps_now(15, 5, 10, 0, 0, 100, 0) == 15);		/* no motion detection: nothing changes */
	CHECK(idle_fps_now(15, 5, 10, 1, 1, 100, 0) == 15);		/* continuous recording keeps the full rate */
	CHECK(idle_fps_now(15, 5, 10, 1, 0, 109.9, 100) == 15);	/* quiet for less than idle_after */
	CHECK(idle_fps_now(15, 5, 10, 1, 0, 110, 100) == 5);
	CHECK(idle_fps_now(15, 5, 10, 1, 0, 111, 110.5) == 15);	/* motion: back at once */
	CHECK(idle_fps_now(15, 15, 10, 1, 0, 500, 0) == 15);		/* not below the stream rate: off */
	CHECK(idle_fps_now(15, 20, 10, 1, 0, 500, 0) == 15);
	CHECK(idle_fps_now(15, 5, 0, 1, 0, 100.5, 100) == 15 && idle_fps_now(15, 5, 0, 1, 0, 101, 100) == 5);	/* after < 1 -> 1 s */

	/* log rotation: nothing without a path or below the limit, then path -> path.1 and a new file on fd 2 */
	{
		char dir[] = "/tmp/lrXXXXXX", lp[64], l1[72], buf[256];
		int fdsave = dup(2), fosave = dup(1), f;
		FILE *fp;
		size_t n;

		CHECK(mkdtemp(dir) != NULL);
		snprintf(lp, sizeof lp, "%s/t.log", dir); snprintf(l1, sizeof l1, "%s.1", lp);
		CHECK(log_rotate(NULL, 100) == 0 && log_rotate("", 100) == 0 && log_rotate(lp, 100) == 0);	/* unset / missing file */
		f = open(lp, O_WRONLY | O_CREAT | O_APPEND, 0644);
		CHECK(f >= 0);
		dup2(f, 2); close(f);
		CHECK(write(2, "0123456789", 10) == 10);
		CHECK(log_rotate(lp, 10) == 0);			/* not larger than the limit */
		CHECK(write(2, "x", 1) == 1);
		CHECK(log_rotate(lp, 10) == 1);
		CHECK(write(2, "after\n", 6) == 6);
		CHECK(log_rotate(lp, 100) == 0);
		fp = fopen(l1, "r"); n = fp ? fread(buf, 1, sizeof buf - 1, fp) : 0; buf[n] = 0; if (fp) fclose(fp);
		CHECK(n == 11 && !strcmp(buf, "0123456789x"));		/* the old file kept whole */
		fp = fopen(lp, "r"); n = fp ? fread(buf, 1, sizeof buf - 1, fp) : 0; buf[n] = 0; if (fp) fclose(fp);
		CHECK(!strcmp(buf, "log rotated\nafter\n"));
		CHECK(write(2, "0123456789abcdef", 16) == 16);	/* second rotation replaces the old .1 */
		CHECK(log_rotate(lp, 20) == 1);
		fp = fopen(l1, "r"); n = fp ? fread(buf, 1, sizeof buf - 1, fp) : 0; buf[n] = 0; if (fp) fclose(fp);
		CHECK(!strncmp(buf, "log rotated\nafter\n0123", 22));
		fflush(stdout); dup2(fdsave, 2); dup2(fosave, 1); close(fdsave); close(fosave);
		unlink(lp); unlink(l1); rmdir(dir);
	}

	/* queue shrink: back to the floor when the last second needed little, otherwise to twice the peak, never above cap */
	CHECK(q_target(0, 786432, 65536, 790528) == 65536);
	CHECK(q_target(20000, 786432, 65536, 790528) == 65536);
	CHECK(q_target(40000, 786432, 65536, 790528) == 131072);	/* 2 * 40000 > 64 KB */
	CHECK(q_target(100000, 786432, 65536, 790528) == 262144);
	CHECK(q_target(700000, 786432, 65536, 790528) == 786432);	/* the peak needs all of it: unchanged */
	CHECK(q_target(900000, 786432, 65536, 790528) == 786432);
	CHECK(q_target(0, 16384, 65536, 790528) == 16384);		/* a small queue is never grown by the trim */

	/* NAL table: same cut as next_nal(), 3 and 4 byte start codes, trailing zeros trimmed, H.264 and H.265 headers */
	{
		static const unsigned char fr[] = { 0, 0, 0, 1, 0x09, 0xf0,			/* AUD */
			0, 0, 0, 1, 0x67, 0x42, 0x00, 0x1e,				/* SPS */
			0, 0, 1, 0x68, 0xce, 0x3c, 0x80, 0,				/* PPS, 3-byte start code, trailing zero trimmed */
			0, 0, 0, 1, 0x65, 0x88, 0x00, 0x00, 0x02, 0xff };		/* IDR slice, 00 00 02 inside is no start code */
		unsigned char cp[sizeof fr + 8];
		struct nal_tab t;

		CHECK(nal_scan(&t, fr, sizeof fr) == 4);
		CHECK(t.off[0] == 4 && t.len[0] == 2 && t.hdr[0] == 0x09);
		CHECK(t.off[1] == 10 && t.len[1] == 4 && t.hdr[1] == 0x67);
		CHECK(t.off[2] == 17 && t.len[2] == 4 && t.hdr[2] == 0x68);
		CHECK(t.off[3] == 26 && t.len[3] == 6 && t.hdr[3] == 0x65);
		CHECK((t.hdr[3] & 31) == 5);				/* H.264 IDR */
		{ static const unsigned char h[] = { 0, 0, 0, 1, 0x40, 0x01, 0xaa, 0, 0, 1, 0x26, 0x01, 0xbb, 0xcc };
		  CHECK(nal_scan(&t, h, sizeof h) == 2 && t.len[0] == 3 && t.len[1] == 4 && ((t.hdr[1] >> 1) & 63) == 19 && ((t.hdr[0] >> 1) & 63) == 32); }
		CHECK(nal_scan(&t, fr, 2) == 0);				/* too short */
		{ static const unsigned char e[] = { 0, 0, 1 }; CHECK(nal_scan(&t, e, 3) == 0); }	/* start code, nothing after it */
		{ static const unsigned char n[] = { 1, 2, 3, 4, 5, 6 }; CHECK(nal_scan(&t, n, 6) == 0); }
		/* copy: aligned (word path), odd lengths, unaligned (memcpy path) */
		for (int len = 0; len <= (int)sizeof fr; len++) {
			static uint32_t src[16], dst[16];

			memcpy(src, fr, sizeof fr); memset(dst, 0xee, sizeof dst);
			nal_copy(dst, src, len);
			CHECK(!memcmp(dst, fr, len) && ((unsigned char *)dst)[len] == 0xee);
		}
		memset(cp, 0xee, sizeof cp);
		nal_copy(cp + 1, fr, sizeof fr);
		CHECK(!memcmp(cp + 1, fr, sizeof fr) && cp[0] == 0xee);
		/* a table cap: more NALs than the table holds are ignored, not overrun */
		{ unsigned char big[NALT_MAX * 6 + 40]; unsigned k, z = 0;
		  for (k = 0; k < NALT_MAX + 5; k++) { big[z++] = 0; big[z++] = 0; big[z++] = 1; big[z++] = 0x41; big[z++] = 0x11; big[z++] = 0x22; }
		  CHECK(nal_scan(&t, big, z) == NALT_MAX && t.len[NALT_MAX - 1] == 3); }
	}

	printf(fails ? "%d FAILED\n" : "util: all OK\n", fails);
	return fails != 0;
}
