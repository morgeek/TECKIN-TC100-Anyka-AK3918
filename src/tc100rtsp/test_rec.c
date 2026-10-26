/* Host test of rec.c: synthetic H.264 / H.265 access units (real SPS, dummy slices) through the recorder into
 * Matroska files. tests/test_tc100rtsp.py checks the files.
 * usage: REC_TEST_ANY_FS=1 ./test_rec DIR h264|h265 SECONDS FPS GOP SEGMENT_S [DROP_FRAME] */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "rec.h"

void rec_test_drop(void);

struct bw { unsigned char b[256]; int pos; };
static void put(struct bw *w, unsigned long long v, int n) { while (n--) { if (v >> n & 1) w->b[w->pos >> 3] |= 0x80 >> (w->pos & 7); w->pos++; } }
static void ue(struct bw *w, unsigned v) { unsigned x = v + 1; int n = 0; while ((x >> n) > 1) n++; put(w, 0, n); put(w, x, n + 1); }
static int finish(struct bw *w) { put(w, 1, 1); while (w->pos & 7) put(w, 0, 1); return w->pos >> 3; }

/* NAL header + RBSP with emulation prevention, after a start code */
static int nal(unsigned char *o, const unsigned char *hdr, int hl, const unsigned char *r, int n)
{
	int i, k = 0, z = 0;

	o[k++] = 0; o[k++] = 0; o[k++] = 0; o[k++] = 1;
	memcpy(o + k, hdr, hl); k += hl;
	for (i = 0; i < n; i++) {
		if (z >= 2 && r[i] <= 3) { o[k++] = 3; z = 0; }
		o[k++] = r[i];
		z = r[i] ? 0 : z + 1;
	}
	return k;
}

static int payload(unsigned char *o, int n, unsigned seed)	/* slice bytes without start code patterns */
{
	int i;

	for (i = 0; i < n; i++) { seed = seed * 1103515245u + 12345u; o[i] = 0x11 + (seed >> 16) % 0xe0; }
	return n;
}

int main(int argc, char **argv)
{
	struct rec_cfg c;
	unsigned char sps[64], pps[16], vps[32], au[20000], tmp[16000], jpg[64];
	int spsn, ppsn, vpsn = 0, hevc, secs, fps, gop, f, n, drop = -1;
	struct bw w;

	if (argc < 7) { fprintf(stderr, "usage: test_rec DIR h264|h265 SECONDS FPS GOP SEGMENT_S [DROP]\n"); return 2; }
	hevc = !strcmp(argv[2], "h265");
	secs = atoi(argv[3]); fps = atoi(argv[4]); gop = atoi(argv[5]);
	if (argc > 7) drop = atoi(argv[7]);

	memset(&w, 0, sizeof w);
	if (!hevc) {				/* baseline, 640x360 (368 coded, 8 rows cropped) */
		static const unsigned char h[1] = { 0x67 }, hp[1] = { 0x68 };

		put(&w, 66, 8); put(&w, 0xc0, 8); put(&w, 30, 8);
		ue(&w, 0); ue(&w, 0); ue(&w, 2); ue(&w, 1); put(&w, 0, 1);
		ue(&w, 39); ue(&w, 22); put(&w, 1, 1); put(&w, 1, 1);
		put(&w, 1, 1); ue(&w, 0); ue(&w, 0); ue(&w, 0); ue(&w, 4);
		put(&w, 0, 1);
		spsn = nal(sps, h, 1, w.b, finish(&w));
		memset(&w, 0, sizeof w); ue(&w, 0); ue(&w, 0); put(&w, 0, 1); put(&w, 0, 1); ue(&w, 0);
		ppsn = nal(pps, hp, 1, w.b, finish(&w));
	} else {				/* Main, 640x360, PTL full of zero bytes (emulation prevention) */
		static const unsigned char hv[2] = { 0x40, 0x01 }, hs[2] = { 0x42, 0x01 }, hp[2] = { 0x44, 0x01 };
		static const unsigned char vb[] = { 0x0c, 0x01, 0xff, 0xff, 0x01, 0x60, 0, 0, 3, 0, 0x90 };

		vpsn = nal(vps, hv, 2, vb, sizeof vb);
		put(&w, 0, 4); put(&w, 0, 3); put(&w, 1, 1);
		put(&w, 0, 2); put(&w, 0, 1); put(&w, 1, 5); put(&w, 0x60000000ULL, 32); put(&w, 9, 4);
		put(&w, 0, 32); put(&w, 0, 12); put(&w, 93, 8);
		ue(&w, 0); ue(&w, 1); ue(&w, 640); ue(&w, 360); put(&w, 0, 1); ue(&w, 0); ue(&w, 0); ue(&w, 4);
		spsn = nal(sps, hs, 2, w.b, finish(&w));
		memset(&w, 0, sizeof w); ue(&w, 0); ue(&w, 0); put(&w, 0, 7);
		ppsn = nal(pps, hp, 2, w.b, finish(&w));
	}
	memcpy(jpg, "\xff\xd8\xff\xe0 test picture \xff\xd9", 20);

	memset(&c, 0, sizeof c);
	c.mode = REC_ALWAYS;
	snprintf(c.dir, sizeof c.dir, "%s", argv[1]);
	snprintf(c.status, sizeof c.status, "%s/status", argv[1]);
	c.segment_s = atoi(argv[6]); c.reserve_mb = 16; c.offline_s = 5; c.postroll_s = 30; c.ring_kb = 8192;
	if (rec_config(&c)) return 1;
	for (n = 0; n < 200 && !rec_active(); n++) usleep(10000);
	if (!rec_active()) { fprintf(stderr, "recorder not active\n"); return 1; }

	for (f = 0; f < secs * fps; f++) {
		unsigned long long ts = 5000000ULL + (unsigned long long)f * 1000000ULL / fps;
		int key = f % gop == 0, k = 0;

		if (f == drop) { rec_test_drop(); continue; }
		if (hevc) { static const unsigned char aud[3] = { 0, 0, 1 }; memcpy(au + k, aud, 3); k += 3; au[k++] = 0x46; au[k++] = 0x01; au[k++] = 0x50; }
		else { au[k++] = 0; au[k++] = 0; au[k++] = 1; au[k++] = 0x09; au[k++] = 0xf0; }
		if (key) {
			if (hevc) { memcpy(au + k, vps, vpsn); k += vpsn; }
			memcpy(au + k, sps, spsn); k += spsn;
			memcpy(au + k, pps, ppsn); k += ppsn;
		}
		{
			unsigned char h[2];
			int pl = payload(tmp, key ? 6000 : 700 + f % 300, f);

			if (hevc) { h[0] = (key ? 19 : 1) << 1; h[1] = 1; }
			else h[0] = key ? 0x65 : 0x41;
			au[k++] = 0; au[k++] = 0; au[k++] = 1;
			memcpy(au + k, h, hevc ? 2 : 1); k += hevc ? 2 : 1;
			memcpy(au + k, tmp, pl); k += pl;
		}
		if (rec_frame(au, k, ts, key, hevc)) { fprintf(stderr, "frame %d not queued\n", f); return 1; }
		if (key) rec_thumb(jpg, 20, ts);
		if (!(f % 50)) usleep(2000);
	}
	for (n = 0; n < 1000 && !rec_idle(); n++) usleep(10000);
	usleep(200000);
	rec_shutdown();
	printf("pushed %d frames\n", f);
	return 0;
}
