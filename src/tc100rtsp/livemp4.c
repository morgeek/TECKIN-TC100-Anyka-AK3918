/* livemp4.c: live video for the browser, from the H.264 stream tc100_rtsp already encodes. No decoding, no re-encoding.
 *
 * Like "Listen" (alisten.c, www/cgi-bin/audio_stream.cgi): www/cgi-bin/live.cgi makes a FIFO <dir>/<pid>.fifo and cats it
 * to the browser after a header (Content-Type video/mp4); tc100_rtsp finds it (live_scan, twice a second), opens it
 * O_RDWR|O_NONBLOCK and writes into it from the capture loop. The browser plays it with Media Source Extensions
 * (src/webui/index/30-live-view.js).
 *
 * What a viewer receives: an initialisation segment (ftyp + moov with avcC, from the SPS / PPS of the first keyframe it
 * sees: mp4box.c, the recorder's writer) followed by one moof + mdat per frame (low latency: nothing waits for a second
 * fragment). A viewer starts at the next IDR. Sequence numbers count from 1, decode times (tfdt) come from the frame
 * timestamps, relative to the first frame; a frame lasts as long as the one before it did (its real length is not known
 * when it is sent). Video only: browsers do not play the A-law track.
 *
 * Limits: LIVE_MAX viewers (2); a viewer is dropped when its FIFO was removed, when it has read nothing for 1.5 s, when no
 * keyframe came for 10 s after it attached, when the stream changes (other SPS) or after LIVE_SECONDS (10 min); its FIFO is
 * removed, the CGI's cat reads end of file, and the page reconnects. The capture loop never blocks: writes are
 * non-blocking, what the FIFO does not take now waits in a small buffer of the viewer (LIVE_OUT_MAX); when that is full
 * frames are skipped until the next keyframe (the decode time line is kept continuous over the hole).
 * Environment (tests): TC100_LIVE_DIR, TC100_LIVE_SECONDS.
 *
 * <dir>/status tells live.cgi what it may serve: "stream=sub|main codec=avc1.42c01e width=640 height=360", or "stream=none"
 * (no H.264 stream: 415) or "stream=pending" (parameter sets not known yet: 503). */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#include "livemp4.h"
#include "mp4box.h"

#define LIVE_MAX	2
#define LIVE_OUT_MAX	(256 * 1024)	/* unwritten bytes kept per viewer */
#define LIVE_STALL_MS	1500		/* nothing read for this long: dropped */
#define LIVE_START_MS	10000		/* no keyframe for this long after attaching: dropped */
#define LIVE_DIR	"/tmp/tc100_live"
#define FIRST_DUR	6000		/* 90 kHz ticks, the first frame (15 fps) */

struct viewer {
	int fd;
	char path[128];
	uint64_t since_ms, read_ms;	/* attached; last time the reader was seen to take data */
	uint64_t wrote, rd_last;	/* bytes written into the FIFO; bytes the reader had taken at the last scan */
	int started, need_key;
	uint32_t seq;
	uint64_t t0_us, prev_ts_us, prev_dt;
	uint32_t prev_dur;
	unsigned char sps[MP4_PS_MAX]; int spsn;
	struct buf tx; size_t off;	/* bytes not written yet: tx.p[off .. tx.n) */
};
static struct viewer V[LIVE_MAX];
static const char *dir = LIVE_DIR;
static unsigned live_seconds = 600;
static int ready, cur_si = -1, nview;
static uint64_t last_scan;
static char status_last[160];
static int direct = 1;	/* RTSP_LIVE_DIRECT=0 (or TC100_LIVE_DIRECT=0): the old way, a payload buffer per frame then a copy per viewer */

static uint64_t mono_ms(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return (uint64_t)t.tv_sec * 1000 + (uint64_t)t.tv_nsec / 1000000;
}

static void v_drop(struct viewer *v)
{
	if (v->fd >= 0) close(v->fd);
	if (v->path[0]) unlink(v->path);
	free(v->tx.p);
	memset(v, 0, sizeof *v);
	v->fd = -1;
	nview--;
}

static void status_write(const char *line)
{
	char tmp[128], fin[128];
	FILE *f;

	if (!ready || !strcmp(line, status_last)) return;
	snprintf(tmp, sizeof tmp, "%.100s/status.tmp", dir);
	snprintf(fin, sizeof fin, "%.100s/status", dir);
	if (!(f = fopen(tmp, "w"))) return;
	fprintf(f, "%s\n", line);
	if (fclose(f) == 0 && rename(tmp, fin) == 0) snprintf(status_last, sizeof status_last, "%s", line);
}

void live_init(void)
{
	const char *e;
	int i;

	if ((e = getenv("RTSP_LIVE_DIRECT")) && *e == '0') direct = 0;
	if ((e = getenv("TC100_LIVE_DIR")) && *e) dir = e;
	if ((e = getenv("TC100_LIVE_SECONDS")) && *e) { live_seconds = 0; while (*e >= '0' && *e <= '9') live_seconds = live_seconds * 10 + (unsigned)(*e++ - '0'); }
	for (i = 0; i < LIVE_MAX; i++) V[i].fd = -1;
	if (mkdir(dir, 0755) != 0 && errno != EEXIST) return;
	{	/* FIFOs left by CGIs of an earlier run */
		DIR *dp = opendir(dir);
		struct dirent *de;

		while (dp && (de = readdir(dp))) {
			size_t n = strlen(de->d_name);
			char path[128];

			if (n < 6 || n > 40 || strcmp(de->d_name + n - 5, ".fifo")) continue;
			snprintf(path, sizeof path, "%.80s/%.40s", dir, de->d_name);
			unlink(path);
		}
		if (dp) closedir(dp);
	}
	ready = 1;
	status_write("stream=pending");
}

int live_count(void) { return nview; }
int live_wants(int si) { return nview > 0 && si == cur_si; }

void live_stream(int si, const char *name, const unsigned char *sps, int sps_len)
{
	char line[160];
	struct nal u;
	struct vinfo vi;
	int i;

	if (si < 0) {
		snprintf(line, sizeof line, "stream=%s", name);
		if (si == -1 && cur_si != -1) for (i = 0; i < LIVE_MAX; i++) if (V[i].fd >= 0) v_drop(&V[i]);	/* both are H.265 now */
		if (si == -1) cur_si = -1;
		status_write(line);
		return;
	}
	if (si != cur_si) {			/* another stream: the viewers' init segments no longer fit */
		for (i = 0; i < LIVE_MAX; i++) if (V[i].fd >= 0) v_drop(&V[i]);
		cur_si = si;
	}
	memset(&vi, 0, sizeof vi);
	u.p = sps; u.n = (uint32_t)sps_len;
	if (!sps || sps_len < 4 || sps_len > MP4_PS_MAX || (sps[0] & 31) != 7 || mp4_parse_sps264(&u, &vi) != 0) {
		snprintf(line, sizeof line, "stream=pending");
		status_write(line);
		return;
	}
	snprintf(line, sizeof line, "stream=%s codec=avc1.%02x%02x%02x width=%d height=%d", name, sps[1], sps[2], sps[3], vi.w, vi.h);
	status_write(line);
}

static int known(const char *path)
{
	for (int i = 0; i < LIVE_MAX; i++) if (V[i].fd >= 0 && !strcmp(V[i].path, path)) return 1;
	return 0;
}

/* write what the FIFO takes; 0 when the viewer is still fine, -1 when it has to go */
static int flush(struct viewer *v)
{
	while (v->off < v->tx.n) {
		ssize_t w = write(v->fd, v->tx.p + v->off, v->tx.n - v->off);

		if (w > 0) { v->off += (size_t)w; v->wrote += (uint64_t)w; continue; }
		if (w < 0 && (errno == EAGAIN || errno == EINTR)) return 0;
		return -1;
	}
	v->off = 0; v->tx.n = 0;
	return 0;
}

#ifdef TC100_HOST_TEST
/* make test_rtsp has no camera: TC100_LIVE_TEST_FILE=<Annex B H.264, access units start with an AUD, first one an IDR> feeds
 * the viewers at TC100_LIVE_TEST_FPS (15) from live_scan, which the main loop calls every 100 ms (tests/test_tc100rtsp.py) */
static void test_feed(void)
{
	static unsigned char *buf; static long len; static long au[20001]; static int nau, next, loaded;
	static uint64_t t0_us, base;
	const char *f = getenv("TC100_LIVE_TEST_FILE"), *e = getenv("TC100_LIVE_TEST_FPS");
	int fps = 0;
	uint64_t now_us = mono_ms() * 1000;

	while (e && *e >= '0' && *e <= '9') fps = fps * 10 + (*e++ - '0');
	if (fps <= 0) fps = 15;
	if (!nview) { t0_us = 0; next = 0; }	/* a viewer starts at the first access unit, in real time */
	if (!f || !nview) return;
	if (!loaded) {
		FILE *fp = fopen(f, "rb");
		long i;

		loaded = 1;
		if (!fp) return;
		buf = malloc(32u << 20); len = (long)fread(buf, 1, 32u << 20, fp); fclose(fp);
		for (i = 0; i + 4 < len; i++)
			if (buf[i] == 0 && buf[i + 1] == 0 && buf[i + 2] == 1 && (buf[i + 3] & 31) == 9 && nau < 20000) au[nau++] = i > 0 && buf[i - 1] == 0 ? i - 1 : i;
		au[nau] = len;
	}
	if (!nau) return;
	if (!t0_us) { t0_us = now_us; base = 5000000; }
	while ((uint64_t)next * 1000000 / (uint64_t)fps <= now_us - t0_us) {
		int k = next % nau, key = 0;
		long i;

		for (i = au[k]; i + 4 < au[k + 1]; i++) if (buf[i] == 0 && buf[i + 1] == 0 && buf[i + 2] == 1 && (buf[i + 3] & 31) == 5) key = 1;
		live_frame(cur_si, buf + au[k], (uint32_t)(au[k + 1] - au[k]), base + (uint64_t)next * 1000000 / (uint64_t)fps, key);
		next++;
	}
}
#endif

void live_scan(uint64_t now_ms)
{
	DIR *dp;
	struct dirent *e;
	int i;
	uint64_t t = mono_ms();

#ifdef TC100_HOST_TEST
	test_feed();
#endif
	if (!ready || now_ms - last_scan < 400) return;
	last_scan = now_ms;
	for (i = 0; i < LIVE_MAX; i++) {
		struct viewer *v = &V[i];
		int pend = 0;

		if (v->fd < 0) continue;
		if (access(v->path, F_OK) != 0) { v_drop(v); continue; }
		if (t - v->since_ms >= (uint64_t)live_seconds * 1000) { v_drop(v); continue; }
		if (!v->started && t - v->since_ms >= LIVE_START_MS) { v_drop(v); continue; }
		if (flush(v) < 0) { v_drop(v); continue; }
		if (ioctl(v->fd, FIONREAD, &pend) != 0) pend = 0;
		{	/* bytes the reader has taken: written - still in the FIFO */
			uint64_t rd = v->wrote > (uint64_t)pend ? v->wrote - (uint64_t)pend : 0;

			if (pend == 0 || rd > v->rd_last) v->read_ms = t;
			v->rd_last = rd;
		}
		if ((pend > 0 || v->off < v->tx.n) && t - v->read_ms >= LIVE_STALL_MS) v_drop(v);
	}
	if (!(dp = opendir(dir))) return;
	while ((e = readdir(dp))) {
		size_t n = strlen(e->d_name);
		char path[128];
		struct stat sb;
		int fd;

		if (n < 6 || n > 40 || strcmp(e->d_name + n - 5, ".fifo")) continue;
		snprintf(path, sizeof path, "%.80s/%.40s", dir, e->d_name);
		if (known(path)) continue;
		if (lstat(path, &sb) != 0 || !S_ISFIFO(sb.st_mode)) continue;
		fd = open(path, O_RDWR | O_NONBLOCK);
		if (fd < 0) continue;
		for (i = 0; i < LIVE_MAX && V[i].fd >= 0; i++) ;
		if (i == LIVE_MAX || cur_si < 0) { close(fd); unlink(path); continue; }	/* full, or no stream: the reader sees end of file */
		memset(&V[i], 0, sizeof V[i]);
		V[i].fd = fd; V[i].since_ms = V[i].read_ms = t;
		snprintf(V[i].path, sizeof V[i].path, "%s", path);
		nview++;
	}
	closedir(dp);
}

/* moof + mdat of one frame into the viewer's buffer. The sample is either pl (length-prefixed NALs already joined: the old
 * way) or, with pl NULL, the nn NALs in nl, each written behind its 4 byte length straight into the buffer (plen bytes in all) */
static void put_frag(struct viewer *v, const struct buf *pl, const struct nal *nl, int nn, size_t plen, uint64_t ts_us, int key)
{
	size_t moof, traf, a, doff;
	uint64_t dt;
	uint32_t dur, mdat;
	unsigned char *p;

	if (v->started == 1) {		/* first frame of this viewer (or after a hole) */
		v->t0_us = ts_us;
		v->started = 2;
		v->prev_dt = 0; v->prev_dur = 0; v->prev_ts_us = ts_us;
		dt = 0; dur = FIRST_DUR;
	} else {
		uint64_t d = ts_us > v->prev_ts_us ? (ts_us - v->prev_ts_us) * 9 / 100 : 0;

		if (v->need_key) {	/* frames were skipped: the time line goes on where it stopped */
			v->t0_us = ts_us - (v->prev_dt + v->prev_dur) * 100 / 9;
			v->need_key = 0;
			d = v->prev_dur ? v->prev_dur : FIRST_DUR;
		}
		dt = (ts_us - v->t0_us) * 9 / 100;
		if (dt <= v->prev_dt) dt = v->prev_dt + 1;
		dur = d < 900 ? 900 : d > 90000 ? 90000 : (uint32_t)d;
	}
	if (!pl) mp4_b_need(&v->tx, plen + 256);
	moof = mp4_box(&v->tx, "moof");
	a = mp4_fbox(&v->tx, "mfhd", 0, 0); mp4_b32(&v->tx, ++v->seq); mp4_end(&v->tx, a);
	traf = mp4_box(&v->tx, "traf");
	a = mp4_fbox(&v->tx, "tfhd", 0, 0x020000); mp4_b32(&v->tx, 1); mp4_end(&v->tx, a);
	a = mp4_fbox(&v->tx, "tfdt", 1, 0); mp4_b64(&v->tx, dt); mp4_end(&v->tx, a);
	a = mp4_fbox(&v->tx, "trun", 0, 0x000701); mp4_b32(&v->tx, 1);
	doff = v->tx.n; mp4_b32(&v->tx, 0);
	mp4_b32(&v->tx, dur); mp4_b32(&v->tx, (uint32_t)plen);
	mp4_b32(&v->tx, key ? 0x02000000u : 0x01010000u);
	mp4_end(&v->tx, a); mp4_end(&v->tx, traf); mp4_end(&v->tx, moof);
	if (v->tx.err) return;
	{	/* data offset: from the moof start to the first sample (8 bytes of mdat header after the moof) */
		uint32_t off = (uint32_t)(v->tx.n - moof + 8);

		p = v->tx.p + doff;
		p[0] = (unsigned char)(off >> 24); p[1] = (unsigned char)(off >> 16); p[2] = (unsigned char)(off >> 8); p[3] = (unsigned char)off;
	}
	mdat = (uint32_t)(8 + plen);
	mp4_b32(&v->tx, mdat); mp4_b_put(&v->tx, "mdat", 4);
	if (pl) mp4_b_put(&v->tx, pl->p, pl->n);
	else {
		mp4_b_need(&v->tx, plen);	/* one growth, not one per NAL */
		for (int i = 0; i < nn; i++) { mp4_b32(&v->tx, nl[i].n); mp4_b_put(&v->tx, nl[i].p, nl[i].n); }
	}
	v->prev_ts_us = ts_us; v->prev_dt = dt; v->prev_dur = dur;
}

void live_frame(int si, const unsigned char *d, uint32_t len, uint64_t ts_us, int key)
{
	struct nal u[32], sel[32];
	const struct nal *sps = NULL, *pps = NULL;
	struct buf pl = { 0 };
	size_t plen = 0;
	int n, i, ns = 0;

	if (!nview || si != cur_si || si < 0) return;
	n = mp4_split_nals(d, len, u, 32);
	for (i = 0; i < n; i++) {
		int t = u[i].p[0] & 31;

		if (t == 7) { sps = &u[i]; continue; }
		if (t == 8) { pps = &u[i]; continue; }
		if (t == 9) continue;
		if (direct) { sel[ns++] = u[i]; plen += 4 + (size_t)u[i].n; }
		else { mp4_b32(&pl, u[i].n); mp4_b_put(&pl, u[i].p, u[i].n); }
	}
	if (!direct) plen = pl.n;
	if (pl.err || !plen) { free(pl.p); return; }
	if (sps && (sps->n > MP4_PS_MAX || sps->n < 4)) sps = NULL;
	for (i = 0; i < LIVE_MAX; i++) {
		struct viewer *v = &V[i];
		size_t pending;

		if (v->fd < 0) continue;
		if (key && sps && v->started && (v->spsn != (int)sps->n || memcmp(v->sps, sps->p, sps->n))) { v_drop(v); continue; }	/* new picture size: reconnect */
		if (!v->started) {
			struct vinfo vi;

			if (!key || !sps || !pps || pps->n > MP4_PS_MAX) continue;
			memset(&vi, 0, sizeof vi);
			if (mp4_parse_sps264(sps, &vi) != 0) continue;
			mp4_init_segment(&v->tx, C_H264, &vi, NULL, sps, pps, 0);
			if (v->tx.err) { v_drop(v); continue; }
			memcpy(v->sps, sps->p, sps->n); v->spsn = (int)sps->n;
			v->started = 1;
		}
		if (flush(v) < 0) { v_drop(v); continue; }
		pending = v->tx.n - v->off;
		if (v->need_key && !key) continue;
		if (pending + plen + 256 > LIVE_OUT_MAX) {	/* the viewer cannot keep up: wait for the next keyframe */
			v->need_key = 1;
			continue;
		}
		if (v->off) { memmove(v->tx.p, v->tx.p + v->off, pending); v->tx.n = pending; v->off = 0; }
		put_frag(v, direct ? NULL : &pl, sel, ns, plen, ts_us, key);
		if (v->tx.err || flush(v) < 0) v_drop(v);
	}
	free(pl.p);
}

void live_close_all(void)
{
	for (int i = 0; i < LIVE_MAX; i++) if (V[i].fd >= 0) v_drop(&V[i]);
	if (ready) {
		char fin[128];

		snprintf(fin, sizeof fin, "%.100s/status", dir);
		unlink(fin);
	}
}
