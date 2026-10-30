/* Host test of livemp4.c: access units (synthetic H.264 with a real SPS, or an Annex B file) go in through live_frame, what the
 * browser would get comes out of the viewers' FIFOs into files that tests/test_tc100rtsp.py parses.
 *   test_livemp4 flow DIR OUT_A OUT_B [INPUT.h264]   viewer A from the start (P frames first: nothing until the IDR), viewer B
 *                                                    attached half way, a third FIFO refused
 *   test_livemp4 slow DIR OUT                        a viewer that reads nothing for a while: frames are skipped until a keyframe,
 *                                                    the time line stays continuous, the viewer is not dropped
 *   test_livemp4 stuck DIR                           a viewer that never reads is dropped (its FIFO removed) after 1.5 s
 *   test_livemp4 change DIR                          a new SPS (other picture size) drops the viewers; stream=none drops too
 * Prints "OK ..." lines, exits 1 on a failed check. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "livemp4.h"

static const unsigned char SPS[] = { 0x67, 0x42, 0xc0, 0x1e, 0xda, 0x02, 0x80, 0xbf, 0xe5, 0x40 };	/* baseline 3.0, 640x360 (as test_rec.c) */
static const unsigned char PPS[] = { 0x68, 0xcc };

#define CHECK(c, ...) do { if (!(c)) { fprintf(stderr, "FAIL line %d: ", __LINE__); fprintf(stderr, __VA_ARGS__); fputc('\n', stderr); exit(1); } } while (0)

static int make_au(unsigned char *o, int f, int key, int size)
{
	int k = 0, i;
	unsigned seed = (unsigned)f * 2654435761u + 1;

	o[k++] = 0; o[k++] = 0; o[k++] = 1; o[k++] = 0x09; o[k++] = 0xf0;			/* access unit delimiter */
	if (key) {
		o[k++] = 0; o[k++] = 0; o[k++] = 0; o[k++] = 1; memcpy(o + k, SPS, sizeof SPS); k += (int)sizeof SPS;
		o[k++] = 0; o[k++] = 0; o[k++] = 0; o[k++] = 1; memcpy(o + k, PPS, sizeof PPS); k += (int)sizeof PPS;
	}
	o[k++] = 0; o[k++] = 0; o[k++] = 1; o[k++] = key ? 0x65 : 0x41;
	o[k++] = (unsigned char)(0x11 + f / 100); o[k++] = (unsigned char)(0x11 + f % 100);	/* the frame number, for the test */
	for (i = 0; i < size; i++) { seed = seed * 1103515245u + 12345u; o[k++] = (unsigned char)(0x11 + (seed >> 16) % 0xe0); }
	return k;
}

static int new_fifo(const char *dir, const char *name)
{
	char p[300];
	int fd;

	snprintf(p, sizeof p, "%s/%s", dir, name);
	unlink(p);
	CHECK(mkfifo(p, 0600) == 0, "mkfifo %s: %s", p, strerror(errno));
	fd = open(p, O_RDONLY | O_NONBLOCK);
	CHECK(fd >= 0, "open %s", p);
	return fd;
}

static int exists(const char *dir, const char *name)
{
	char p[300];

	snprintf(p, sizeof p, "%s/%s", dir, name);
	return access(p, F_OK) == 0;
}

static long drain(int fd, FILE *out)
{
	unsigned char b[65536];
	long total = 0;
	ssize_t n;

	while ((n = read(fd, b, sizeof b)) > 0) { if (out) fwrite(b, 1, (size_t)n, out); total += n; }
	return total;
}

static uint64_t scan_t = 1000;
static void scan(void) { scan_t += 500; live_scan(scan_t); }

/* access units of a file (start at an AUD) */
static unsigned char *in_buf; static long in_len, in_au[20001]; static int in_n;
static void load(const char *path)
{
	FILE *f = fopen(path, "rb");
	long i;

	CHECK(f, "open %s", path);
	in_buf = malloc(64u << 20); in_len = (long)fread(in_buf, 1, 64u << 20, f); fclose(f);
	for (i = 0; i + 4 < in_len; i++)
		if (in_buf[i] == 0 && in_buf[i + 1] == 0 && in_buf[i + 2] == 1 && (in_buf[i + 3] & 31) == 9 && in_n < 20000)
			in_au[in_n++] = i > 0 && in_buf[i - 1] == 0 ? i - 1 : i;
	in_au[in_n] = in_len;
	CHECK(in_n > 0, "no access units in %s", path);
}

int main(int argc, char **argv)
{
	static unsigned char au[200000];
	const char *mode = argc > 2 ? argv[1] : "", *dir = argc > 2 ? argv[2] : "";
	int f, fdA = -1, fdB = -1, fdC = -1, n;
	FILE *oa = NULL, *ob = NULL;

	if (argc < 3) { fprintf(stderr, "usage: test_livemp4 flow|slow|stuck|change DIR ...\n"); return 2; }
	mkdir(dir, 0755);
	setenv("TC100_LIVE_DIR", dir, 1);
	live_init();
	CHECK(!live_count() && !live_wants(0), "no viewer yet");

	if (!strcmp(mode, "flow")) {
		int total = 60, gop = 10, first_key = 3, half;

		CHECK(argc >= 5, "usage");
		if (argc > 5) { load(argv[5]); total = in_n; }
		half = total / 2;
		oa = fopen(argv[3], "wb"); ob = fopen(argv[4], "wb");
		live_stream(0, "main", SPS, sizeof SPS);
		fdA = new_fifo(dir, "100.fifo");
		scan();
		CHECK(live_count() == 1 && live_wants(0) && !live_wants(1), "viewer A attached");
		for (f = 0; f < total; f++) {
			uint64_t ts = 5000000ULL + (uint64_t)f * 1000000ULL / 15;
			int key, len;

			if (in_n) {
				long i;

				len = (int)(in_au[f + 1] - in_au[f]);
				for (i = in_au[f], key = 0; i + 4 < in_au[f + 1]; i++)
					if (in_buf[i] == 0 && in_buf[i + 1] == 0 && in_buf[i + 2] == 1 && (in_buf[i + 3] & 31) == 5) key = 1;
				live_frame(0, in_buf + in_au[f], (uint32_t)len, ts, key);
			} else {
				key = f >= first_key && (f - first_key) % gop == 0;
				len = make_au(au, f, key, key ? 6000 : 500 + f % 300);
				live_frame(0, au, (uint32_t)len, ts, key);
			}
			if (f < 3 && !in_n) CHECK(drain(fdA, oa) == 0, "nothing is sent before the first IDR");
			drain(fdA, oa);
			if (fdB >= 0) drain(fdB, ob);
			if (f == half) {
				fdB = new_fifo(dir, "101.fifo");
				scan();
				CHECK(live_count() == 2, "viewer B attached");
				fdC = new_fifo(dir, "102.fifo");
				scan();
				CHECK(live_count() == 2 && !exists(dir, "102.fifo"), "a third viewer is refused and its FIFO removed");
				CHECK(drain(fdC, NULL) == 0, "the refused viewer gets end of file, no data");
			}
		}
		drain(fdA, oa); drain(fdB, ob);
		fclose(oa); fclose(ob);
		CHECK(live_count() == 2, "both viewers still attached");
		live_close_all();
		CHECK(!exists(dir, "100.fifo") && !exists(dir, "101.fifo") && !live_count(), "FIFOs removed at exit");
		printf("OK flow %d frames\n", total);
		return 0;
	}
	if (!strcmp(mode, "slow")) {
		int k = 0;

		CHECK(argc >= 4, "usage");
		oa = fopen(argv[3], "wb");
		live_stream(0, "main", SPS, sizeof SPS);
		fdA = new_fifo(dir, "100.fifo");
		scan();
		for (f = 0; f < 150; f++) {			/* 150 frames, a keyframe every 10, ~1.4 MB: far more than FIFO and buffer */
			int key = f % 10 == 0, len = make_au(au, f, key, key ? 12000 : 9000);

			live_frame(0, au, (uint32_t)len, 5000000ULL + (uint64_t)f * 66666, key);
		}
		CHECK(live_count() == 1, "a viewer that is slow for a moment is kept");
		for (n = 0; n < 40; n++) {			/* the reader wakes up: everything buffered arrives, the stream goes on */
			drain(fdA, oa);
			scan();
			{
				int key = (150 + k) % 10 == 0, len = make_au(au, 150 + k, key, key ? 12000 : 9000);

				live_frame(0, au, (uint32_t)len, 5000000ULL + (uint64_t)(150 + k) * 66666, key);
				k++;
			}
			usleep(20000);
		}
		drain(fdA, oa);
		fclose(oa);
		CHECK(live_count() == 1, "still attached");
		live_close_all();
		printf("OK slow\n");
		return 0;
	}
	if (!strcmp(mode, "stuck")) {
		live_stream(0, "main", SPS, sizeof SPS);
		fdA = new_fifo(dir, "100.fifo");
		scan();
		for (f = 0; f < 30; f++) { int key = f % 10 == 0, len = make_au(au, f, key, key ? 6000 : 700); live_frame(0, au, (uint32_t)len, 5000000ULL + (uint64_t)f * 66666, key); }
		CHECK(live_count() == 1 && exists(dir, "100.fifo"), "attached");
		usleep(700000); scan();
		CHECK(live_count() == 1, "not dropped after 0.7 s");
		usleep(1000000); scan();
		CHECK(live_count() == 0 && !exists(dir, "100.fifo"), "dropped after 1.7 s without a read");
		/* a viewer whose FIFO is removed is dropped at the next scan */
		fdB = new_fifo(dir, "101.fifo");
		scan();
		CHECK(live_count() == 1, "attached again");
		{ char p[300]; snprintf(p, sizeof p, "%s/101.fifo", dir); unlink(p); }
		scan();
		CHECK(live_count() == 0, "FIFO removed: viewer dropped");
		printf("OK stuck\n");
		return 0;
	}
	if (!strcmp(mode, "change")) {
		char line[200];
		FILE *fs;
		char p[300];

		live_stream(1, "sub", SPS, sizeof SPS);
		snprintf(p, sizeof p, "%s/status", dir);
		fs = fopen(p, "r"); CHECK(fs && fgets(line, sizeof line, fs), "status file"); fclose(fs);
		CHECK(!strcmp(line, "stream=sub codec=avc1.42c01e width=640 height=360\n"), "status line: %s", line);
		fdA = new_fifo(dir, "100.fifo");
		scan();
		CHECK(live_count() == 1 && live_wants(1) && !live_wants(0), "attached to the sub-stream");
		{ int len = make_au(au, 0, 1, 3000); live_frame(0, au, (uint32_t)len, 5000000, 1); }	/* another stream: ignored */
		CHECK(drain(fdA, NULL) == 0, "frames of the other stream are not sent");
		{ int len = make_au(au, 0, 1, 3000); live_frame(1, au, (uint32_t)len, 5000000, 1); }
		CHECK(drain(fdA, NULL) > 600, "init segment and the first frame");
		live_stream(0, "main", SPS, sizeof SPS);			/* the live stream is another one now: the viewer is dropped */
		CHECK(live_count() == 0 && !exists(dir, "100.fifo"), "stream switch drops the viewers");
		fdA = new_fifo(dir, "100.fifo");
		scan();
		CHECK(live_count() == 1, "attached to main");
		live_stream(-1, "none", NULL, 0);
		fs = fopen(p, "r"); CHECK(fs && fgets(line, sizeof line, fs), "status file"); fclose(fs);
		CHECK(!strcmp(line, "stream=none\n") && live_count() == 0, "stream=none, viewers dropped");
		fdB = new_fifo(dir, "101.fifo");
		scan();
		CHECK(live_count() == 0 && !exists(dir, "101.fifo"), "no viewer without a stream");
		live_stream(0, "main", SPS, 3);			/* a damaged SPS: pending */
		fs = fopen(p, "r"); CHECK(fs && fgets(line, sizeof line, fs), "status file"); fclose(fs);
		CHECK(!strcmp(line, "stream=pending\n"), "pending: %s", line);
		printf("OK change\n");
		return 0;
	}
	fprintf(stderr, "unknown mode %s\n", mode);
	return 2;
}
