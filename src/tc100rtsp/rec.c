/* rec.c: local recording for tc100_rtsp (Linux 6.6), the 3.0 successor of src/tc100fix/rec.c (2.x).
 *
 * The H.264 / H.265 frames the encoder already makes for RTSP are copied, with no decoding or re-encoding, into
 * fragmented MP4 files on the SD card, where the web UI's Recordings page (viewrecords.cgi) lists them:
 * <dir>/YYYY-MM-DD_HH-MM-SS.mp4 (local time of the first frame), with a JPEG of the first keyframe's picture next to
 * it: <dir>/YYYY-MM-DD_HH-MM-SS.jpg (made by the hardware JPEG engine in tc100_rtsp, no ffmpeg).
 *
 * The MP4 writer is the one of src/tc100fix/rec.c (2.x, checked on the camera): an initialisation segment (ftyp,
 * moov with avcC / hvcC and mvex), then one fragment (moof + mdat) per second at most, each one written whole: a file
 * cut by a power loss or a card removal stays playable up to its last fragment, and browsers play the files as they
 * are (H.264 everywhere, H.265 where the browser decodes it).
 *
 * Threads: the main thread (encoder loop) only copies frames into a ring (rec_frame, never blocks). A writer thread
 * of its own does all the card I/O: an SD card can stall a write() for seconds (FAT updates, a slow or failing card),
 * and the capture loop has two V4L2 buffers (130 ms at 15 fps). That is why this module has a thread. The ring is
 * single producer / single consumer, without locks (ARM926: one core; x86 host tests: total store order), so the only
 * pthread call is pthread_create.
 *
 * Modes (rec_cfg.mode): always; offline = only while nobody receives the RTSP stream (Frigate down, network cut), from
 * offline_s after it stopped (the file starts with the frames still queued: pre-roll) until postroll_s after it is back;
 * motion = while motion is detected, + postroll_s (pre-roll as well).
 *
 * Card rules: files are written only into a directory on a vfat or exfat file system (the card); RAM, flash and the
 * 16 KB tmpfs placeholder of /mnt/sd are refused. When the directory (or the target of the /mnt/DCIM link) is missing
 * and its parent is on the card, it is created. Free space: before each file and every minute the oldest recordings
 * (YYYY-MM-DD_HH-MM-SS.mp4 and its .jpg) are deleted until reserve_mb are free; below half of that the recorder
 * waits ("full"). <status>.pause (scripts/rec-storage.sh eject) closes the file and leaves the card alone.
 *
 * Status file (<status>, every 10 s and on each change), keys as on 2.x:
 *   mode= rtsp_client= state=off|standby|waiting|recording|paused|no-card|full|error|bad-sps file= files= bytes=
 *   frames= dropped= codec= size= free_mb= uptime_s= thumbs=
 *
 * REC_HOST_TEST: REC_TEST_ANY_FS=1 accepts any file system (tests on the host).
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#include "rec.h"
#include "mp4box.h"

#define RLOG(...) do { char _b[300]; int _n = snprintf(_b, sizeof _b, "rec: " __VA_ARGS__); \
	_n = _n > (int)sizeof _b - 1 ? (int)sizeof _b - 1 : _n; if (_n > 0) (void)!write(2, _b, _n); } while (0)
#define BARRIER() __asm__ __volatile__("" ::: "memory")

#define TS		MP4_TS		/* MP4 media timescale (video) */
#define ATS		MP4_ATS		/* audio timescale: 1 tick = 1 A-law sample */
#define A_MAX		128		/* audio samples (chunks) per fragment */
#define A_GAP_FILL	16000		/* a hole up to 2 s is filled with silence, a longer one starts a new run */
#define A_GAP_LATE	12000		/* late arrival beyond 1.5 s counts as a hole */
#define FRAG_US		1000000ULL	/* one fragment per second at most */
#define FRAG_MAX_SAMPLES 128		/* a whole GOP of pre-roll fits */
#define FRAG_MAX_BYTES	(384 * 1024)
#define PS_MAX		MP4_PS_MAX

static uint64_t now_us(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return (uint64_t)t.tv_sec * 1000000ULL + (uint64_t)t.tv_nsec / 1000;
}

/* ---- ring: main thread -> writer ---------------------------------------------------------------------------- */
struct qhdr { uint32_t len, flags; uint64_t ts; };
#define QF_KEY		1u
#define QF_GAP		2u	/* frames were dropped before this one */
#define QF_HEVC		4u
#define QF_THUMB	8u	/* JPEG of the keyframe with this timestamp */
#define QF_AUDIO	16u	/* A-law bytes, ts = the time the last byte was captured */
#define QF_AGAP		32u	/* audio was dropped or restarted before this chunk */
#define Q_WRAP		0xffffffffu

static unsigned char *q_buf;
static size_t q_size;
static volatile size_t q_head, q_tail;		/* head: written by the producer only, tail: by the writer only */
static int p_gap, p_agap;			/* producer: a frame / an audio chunk was dropped since the last push */
static volatile unsigned long q_dropped, q_pushed;

static int q_push(const unsigned char *d, uint32_t len, uint64_t ts, uint32_t flags)
{
	size_t need = sizeof(struct qhdr) + (((size_t)len + 7u) & ~(size_t)7u), head = q_head, tail = q_tail;
	struct qhdr h;

	if (!q_buf || need > q_size / 2) goto drop;
	if (head >= tail) {
		if (q_size - head < need || (q_size - head == need && tail == 0)) {
			if (tail <= need) goto drop;		/* wrapping would reach the reader */
			if (q_size - head >= sizeof h) { h.len = Q_WRAP; h.flags = 0; h.ts = 0; memcpy(q_buf + head, &h, sizeof h); }
			head = 0;
		}
	} else if (tail - head <= need) {
		goto drop;
	}
	h.len = len; h.flags = flags; h.ts = ts;
	if (flags & QF_AUDIO) { if (p_agap) h.flags |= QF_AGAP; p_agap = 0; }
	else if (!(flags & QF_THUMB)) { if (p_gap) h.flags |= QF_GAP; p_gap = 0; }
	memcpy(q_buf + head, &h, sizeof h);
	memcpy(q_buf + head + sizeof h, d, len);
	head += need;
	if (head == q_size) head = 0;
	BARRIER();
	q_head = head;
	q_pushed++;
	return 0;
drop:
	if (flags & QF_AUDIO) p_agap = 1;
	else if (!(flags & QF_THUMB)) p_gap = 1;	/* a lost picture is no hole in the video */
	q_dropped++;
	return -1;
}

static int q_peek(struct qhdr *h, const unsigned char **d)
{
	for (;;) {
		size_t tail = q_tail, head = q_head;

		BARRIER();
		if (tail == head) return 0;
		if (q_size - tail < sizeof *h) { q_tail = 0; continue; }
		memcpy(h, q_buf + tail, sizeof *h);
		if (h->len == Q_WRAP) { q_tail = 0; continue; }
		*d = q_buf + tail + sizeof *h;
		return 1;
	}
}

static void q_pop(const struct qhdr *h)
{
	size_t t = q_tail + sizeof *h + (((size_t)h->len + 7u) & ~(size_t)7u);

	BARRIER();
	q_tail = t >= q_size ? 0 : t;
}

/* standby: drop the oldest records until at most <keep> bytes are queued and the queue starts at a keyframe */
static void q_trim(size_t keep)
{
	struct qhdr h;
	const unsigned char *d;

	while (q_peek(&h, &d)) {
		size_t head = q_head, tail = q_tail, used = head >= tail ? head - tail : q_size - tail + head;

		if (used <= keep && (h.flags & QF_KEY)) break;
		q_pop(&h);
	}
}

/* ---- configuration and inputs (main thread -> writer) -------------------------------------------------------- */
static struct rec_cfg c_pub, C;		/* c_pub: written by the main thread under a sequence count; C: writer's copy */
static volatile unsigned c_seq;
static volatile int r_mode, r_watched, r_motion;
static volatile int w_run, w_stop, w_done, w_card_ok, w_paused;

static volatile int r_audio;

int rec_active(void) { return w_run && !w_stop && r_mode != REC_OFF && w_card_ok && !w_paused; }
int rec_audio_wanted(void) { return r_audio && rec_active(); }

int rec_audio(const unsigned char *d, uint32_t len, uint64_t ts_us, int gap)
{
	if (!len || !rec_audio_wanted()) return -1;
	return q_push(d, len, ts_us, QF_AUDIO | (gap ? QF_AGAP : 0));
}

int rec_frame(const unsigned char *d, uint32_t len, uint64_t ts_us, int key, int hevc)
{
	if (!rec_active()) return -1;
	return q_push(d, len, ts_us, (key ? QF_KEY : 0) | (hevc ? QF_HEVC : 0));
}

void rec_thumb(const unsigned char *jpg, uint32_t len, uint64_t key_ts_us)
{
	if (rec_active() && len) q_push(jpg, len, key_ts_us, QF_THUMB);
}

void rec_inputs(int watched, int motion) { r_watched = watched; r_motion = motion; }

int rec_idle(void) { return q_head == q_tail; }

#ifdef REC_HOST_TEST
void rec_test_drop(void);
void rec_test_drop(void) { p_gap = 1; q_dropped++; }	/* a frame lost as with a full queue */
#endif

/* ---- writer state ----------------------------------------------------------------------------------------------- */
struct sample { uint32_t size, key; uint64_t ts; };

static struct {
	int fd, codec, waiting_key, thumb_done;
	struct vinfo vi;
	unsigned char ps[3][PS_MAX]; uint32_t psn[3];	/* VPS SPS PPS of the open file */
	char path[200];
	uint64_t file_t0, file_key_ts, last_ts, last_rx, last_sync;
	uint32_t seq;					/* fragment number */
	struct sample s[FRAG_MAX_SAMPLES]; int ns;	/* the fragment being filled */
	struct buf data;				/* its samples */
	int audio;					/* the open file has the A-law track */
	int a_ok, a_resync, na;				/* audio anchored in this file; samples (chunks) of the fragment */
	uint16_t asz[A_MAX];				/* their sizes (= durations, 8 kHz) */
	struct buf adata;				/* their bytes */
	uint64_t a_pos, a_tfdt;				/* audio samples since the file start: end of the last one, start of the fragment */
	unsigned long long asamples;
	unsigned long long bytes, files, thumbs;
	char state[16];
	int state_dirty, want, watched;
	uint64_t last_watched, watch_since, last_motion;
	uint64_t last_status, last_space, retry_at, next_card, next_pause;
	unsigned seen_seq;
} W = { .fd = -1 };

static void set_state(const char *s)
{
	if (strcmp(W.state, s)) { snprintf(W.state, sizeof W.state, "%s", s); W.state_dirty = 1; }
}

static int card_fs(const struct statfs *s)
{
#ifdef REC_HOST_TEST
	if (getenv("REC_TEST_ANY_FS")) return 1;
#endif
	switch ((unsigned long)s->f_type) {
	case 0x4d44UL:		/* vfat (MSDOS_SUPER_MAGIC) */
	case 0x2011bab0UL:	/* exfat */
		return 1;
	}
	return 0;
}

/* the recording directory is on the card; created when missing and its parent is on the card */
static int dir_ok(void)
{
	struct statfs s;
	char t[200], parent[200], *sl;
	const char *d = C.dir;
	ssize_t k;

	if (!C.dir[0]) return 0;
	if (statfs(C.dir, &s) == 0) return card_fs(&s);
	if (errno != ENOENT) return 0;
	k = readlink(C.dir, t, sizeof t - 1);		/* /mnt/DCIM -> /mnt/sd/DCIM (flash mode) */
	if (k > 0 && t[0] == '/') { t[k] = 0; d = t; }
	snprintf(parent, sizeof parent, "%s", d);
	sl = strrchr(parent, '/');
	if (!sl || sl == parent) return 0;
	*sl = 0;
	if (statfs(parent, &s) != 0 || !card_fs(&s)) return 0;
	if (mkdir(d, 0755) != 0 && errno != EEXIST) return 0;
	return statfs(C.dir, &s) == 0 && card_fs(&s);
}

static unsigned long free_mb(void)
{
	struct statfs s;

	if (statfs(C.dir, &s) != 0) return 0;
	return (unsigned long)((unsigned long long)s.f_bavail * s.f_bsize / (1024 * 1024));
}

/* YYYY-MM-DD_HH-MM-SS.mp4, the name the Recordings page lists */
static int rec_name(const char *s)
{
	static const char pat[] = "dddd-dd-dd_dd-dd-dd.mp4";
	int i;

	for (i = 0; pat[i]; i++)
		if (pat[i] == 'd' ? s[i] < '0' || s[i] > '9' : s[i] != pat[i]) return 0;
	return s[i] == 0;
}

/* delete the oldest recording and its picture (never the file being written); 0 when none is left */
static int delete_oldest(void)
{
	DIR *dp;
	struct dirent *e;
	char old[32] = "", p[448];

	if (!(dp = opendir(C.dir))) return 0;
	while ((e = readdir(dp)))
		if (rec_name(e->d_name) && (!old[0] || strcmp(e->d_name, old) < 0)) {
			snprintf(p, sizeof p, "%s/%.23s", C.dir, e->d_name);
			if (W.fd >= 0 && !strcmp(p, W.path)) continue;
			snprintf(old, sizeof old, "%.23s", e->d_name);
		}
	closedir(dp);
	if (!old[0]) return 0;
	snprintf(p, sizeof p, "%s/%s", C.dir, old);
	if (unlink(p) != 0) return 0;
	RLOG("card: %s deleted (keeping %d MB free)\n", old, C.reserve_mb);
	memcpy(p + strlen(p) - 3, "jpg", 3);
	unlink(p);
	return 1;
}

static void make_room(void)
{
	int n = 0;

	while (free_mb() < (unsigned long)C.reserve_mb && n++ < 50)
		if (!delete_oldest()) break;
}

static int write_all(int fd, const void *p, size_t n)
{
	const unsigned char *c = p;

	while (n) {
		ssize_t k = write(fd, c, n);

		if (k < 0) { if (errno == EINTR) continue; return -1; }
		if (k == 0) { errno = ENOSPC; return -1; }
		c += k; n -= (size_t)k;
	}
	return 0;
}

static void frag_reset(void) { W.data.n = 0; W.data.err = 0; W.ns = 0; W.adata.n = 0; W.adata.err = 0; W.na = 0; }

static void close_fd(void)
{
	if (W.fd >= 0) { fsync(W.fd); close(W.fd); W.fd = -1; }
	W.path[0] = 0;
	frag_reset();
}

static void fail(const char *what)
{
	RLOG("%s %s: %s, retry in 30 s\n", what, W.path, strerror(errno));
	close_fd();
	set_state("error");
	W.retry_at = now_us() + 30000000ULL;
	W.waiting_key = 1;
}

/* write the pending fragment (moof + mdat); its last sample lasts until next_ts (0: the average duration) */
static void flush_frag(uint64_t next_ts)
{
	struct buf m = { 0 };
	size_t moof, traf, a, trun_off, atrun_off = 0;
	unsigned char mh[8];
	int na = W.audio ? W.na : 0;
	uint32_t mdat, off;
	int i;

	if (W.fd < 0) { frag_reset(); return; }
	if (W.ns == 0) return;				/* audio waits for the next picture */
	if (W.data.err || W.adata.err) { frag_reset(); W.waiting_key = 1; return; }
	mdat = (uint32_t)(8 + W.data.n + (na ? W.adata.n : 0));
	if (next_ts <= W.s[W.ns - 1].ts) {
		uint64_t d = W.ns > 1 ? (W.s[W.ns - 1].ts - W.s[0].ts) / (uint64_t)(W.ns - 1) : 66000;

		next_ts = W.s[W.ns - 1].ts + (d ? d : 66000);
	}
	moof = mp4_box(&m, "moof");
	a = mp4_fbox(&m, "mfhd", 0, 0); mp4_b32(&m, ++W.seq); mp4_end(&m, a);
	traf = mp4_box(&m, "traf");
	a = mp4_fbox(&m, "tfhd", 0, 0x020000); mp4_b32(&m, 1); mp4_end(&m, a);
	a = mp4_fbox(&m, "tfdt", 1, 0); mp4_b64(&m, (W.s[0].ts - W.file_t0) * 9 / 100); mp4_end(&m, a);
	a = mp4_fbox(&m, "trun", 0, 0x000701); mp4_b32(&m, (uint32_t)W.ns);
	trun_off = m.n; mp4_b32(&m, 0);
	for (i = 0; i < W.ns; i++) {
		uint64_t t1 = i + 1 < W.ns ? W.s[i + 1].ts : next_ts;
		uint64_t d = ((t1 - W.file_t0) * 9 / 100) - ((W.s[i].ts - W.file_t0) * 9 / 100);

		mp4_b32(&m, (uint32_t)d); mp4_b32(&m, W.s[i].size);
		mp4_b32(&m, W.s[i].key ? 0x02000000u : 0x01010000u);
	}
	mp4_end(&m, a); mp4_end(&m, traf);
	if (na) {					/* the audio of the same stretch, track 2 */
		traf = mp4_box(&m, "traf");
		a = mp4_fbox(&m, "tfhd", 0, 0x020000); mp4_b32(&m, 2); mp4_end(&m, a);
		a = mp4_fbox(&m, "tfdt", 1, 0); mp4_b64(&m, W.a_tfdt); mp4_end(&m, a);
		a = mp4_fbox(&m, "trun", 0, 0x000301); mp4_b32(&m, (uint32_t)na);
		atrun_off = m.n; mp4_b32(&m, 0);
		for (i = 0; i < na; i++) { mp4_b32(&m, W.asz[i]); mp4_b32(&m, W.asz[i]); }
		mp4_end(&m, a); mp4_end(&m, traf);
	}
	mp4_end(&m, moof);
	if (m.err) { free(m.p); frag_reset(); W.waiting_key = 1; return; }
	off = (uint32_t)(m.n + 8);			/* data offset: from the moof start to the first sample */
	m.p[trun_off] = (unsigned char)(off >> 24); m.p[trun_off + 1] = (unsigned char)(off >> 16);
	m.p[trun_off + 2] = (unsigned char)(off >> 8); m.p[trun_off + 3] = (unsigned char)off;
	if (na) {
		off += (uint32_t)W.data.n;
		m.p[atrun_off] = (unsigned char)(off >> 24); m.p[atrun_off + 1] = (unsigned char)(off >> 16);
		m.p[atrun_off + 2] = (unsigned char)(off >> 8); m.p[atrun_off + 3] = (unsigned char)off;
	}
	mh[0] = (unsigned char)(mdat >> 24); mh[1] = (unsigned char)(mdat >> 16);
	mh[2] = (unsigned char)(mdat >> 8); mh[3] = (unsigned char)mdat; memcpy(mh + 4, "mdat", 4);
	if (write_all(W.fd, m.p, m.n) != 0 || write_all(W.fd, mh, 8) != 0 || write_all(W.fd, W.data.p, W.data.n) != 0 ||
	    (na && write_all(W.fd, W.adata.p, W.adata.n) != 0)) {
		free(m.p);
		fail("write");
		return;
	}
	W.bytes += m.n + mdat;
	if (W.s[W.ns - 1].ts - W.last_sync >= 10000000ULL) {	/* on the card every 10 s */
		fdatasync(W.fd);
		W.last_sync = W.s[W.ns - 1].ts;
	}
	free(m.p);
	frag_reset();
}

/* close the file: a fragmented MP4 needs nothing after its last fragment */
static void finish_file(void)
{
	if (W.fd >= 0) flush_frag(0);
	close_fd();
}

static int open_file(const struct nal *vps, const struct nal *sps, const struct nal *pps, uint64_t ts, uint64_t key_ts)
{
	struct buf b = { 0 };
	struct tm tm;
	time_t t;
	int k;
	uint64_t now = now_us();

	if (!dir_ok()) { set_state("no-card"); w_card_ok = 0; errno = ENODEV; return -1; }
	make_room();
	if (free_mb() < (unsigned long)C.reserve_mb / 2 + 8) { set_state("full"); errno = ENOSPC; return -1; }
	t = time(NULL) - (time_t)(now > ts ? (now - ts) / 1000000ULL : 0);	/* wall time of the first frame */
	for (k = 0; k < 5; k++, t++) {		/* never overwrite: next second if taken */
		localtime_r(&t, &tm);
		snprintf(W.path, sizeof W.path, "%s/%04d-%02d-%02d_%02d-%02d-%02d.mp4", C.dir, tm.tm_year + 1900, tm.tm_mon + 1,
			 tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec);
		W.fd = open(W.path, O_WRONLY | O_CREAT | O_EXCL, 0644);
		if (W.fd >= 0 || errno != EEXIST) break;
	}
	if (W.fd < 0) return -1;
	W.audio = C.audio;
	mp4_init_segment(&b, W.codec, &W.vi, vps, sps, pps, W.audio);
	if (b.err || write_all(W.fd, b.p, b.n) != 0) {
		int e = errno;

		free(b.p); close(W.fd); W.fd = -1; unlink(W.path); W.path[0] = 0; errno = e ? e : ENOMEM;
		return -1;
	}
	W.bytes += b.n;
	free(b.p);
	W.file_t0 = ts; W.file_key_ts = key_ts; W.last_sync = ts; W.files++; W.thumb_done = 0; W.seq = 0;
	W.a_ok = W.a_resync = 0; W.a_pos = W.a_tfdt = 0;
	frag_reset();
	W.psn[0] = vps ? vps->n : 0; if (vps) memcpy(W.ps[0], vps->p, vps->n);
	W.psn[1] = sps->n; memcpy(W.ps[1], sps->p, sps->n);
	W.psn[2] = pps->n; memcpy(W.ps[2], pps->p, pps->n);
	set_state("recording");
	RLOG("%s (%s %dx%d)\n", W.path, W.codec == C_H265 ? "H.265" : "H.264", W.vi.w, W.vi.h);
	return 0;
}

static int same_ps(int i, const struct nal *u)
{
	if (!u) return W.psn[i] == 0;
	return u->n == W.psn[i] && !memcmp(u->p, W.ps[i], u->n);
}

/* one access unit as a sample of the current fragment (4-byte NAL lengths, parameter sets and AUDs left out) */
static void append_sample(const struct nal *u, int n, int key, uint64_t ts)
{
	size_t size = 0;
	int i;

	for (i = 0; i < n; i++) {
		int t = mp4_nal_type(W.codec, &u[i]);

		if (W.codec == C_H265 ? (t >= 32 && t <= 35) : (t == 7 || t == 8 || t == 9)) continue;
		mp4_b32(&W.data, u[i].n); mp4_b_put(&W.data, u[i].p, u[i].n);
		size += 4 + u[i].n;
	}
	if (W.data.err) { frag_reset(); W.waiting_key = 1; return; }
	if (!size) return;
	W.s[W.ns].size = (uint32_t)size; W.s[W.ns].key = (uint32_t)key; W.s[W.ns].ts = ts;
	W.ns++;
}

/* A-law bytes captured up to h->ts. The track is a running sample count: placed on the video clock at the start of the file
 * (and after a hole), then continuous, so arrival jitter does not move it. A short hole (arecord restarted, a dropped chunk)
 * is filled with A-law silence, a long one starts the track again at the right time. */
static void audio_discard(void) { W.na = 0; W.adata.n = 0; W.adata.err = 0; }

static void put_audio(const unsigned char *d, uint32_t n)
{
	if (W.na >= A_MAX) {
		if (W.ns) flush_frag(0); else audio_discard();
		if (W.fd < 0) return;
	}
	if (!W.na) W.a_tfdt = W.a_pos;
	mp4_b_put(&W.adata, d, n);
	if (W.adata.err) { audio_discard(); return; }
	W.asz[W.na++] = (uint16_t)n;
	W.a_pos += n; W.asamples += n;
}

static void append_audio(const struct qhdr *h, const unsigned char *d)
{
	uint64_t dur = (uint64_t)h->len * 1000000ULL / ATS, start, wanted;
	uint32_t i, n;

	uint32_t fl = h->flags;

	if (!W.audio || W.fd < 0 || !h->len) return;
	if (W.waiting_key) { W.a_resync = 1; return; }		/* no file content until the next keyframe: the hole is filled later */
	if (W.a_resync) { fl |= QF_AGAP; W.a_resync = 0; }
	start = h->ts > dur ? h->ts - dur : 0;			/* when its first byte was captured */
	if (h->ts <= W.file_t0) return;				/* before the first picture of the file */
	wanted = start > W.file_t0 ? (start - W.file_t0) * ATS / 1000000ULL : 0;
	if (!W.a_ok) {
		W.a_ok = 1; W.a_pos = wanted;
	} else if (wanted > W.a_pos && (wanted - W.a_pos > A_GAP_LATE || ((fl & QF_AGAP) && wanted - W.a_pos > 400))) {
		uint64_t gap = wanted - W.a_pos;

		if (gap <= A_GAP_FILL) {
			static const unsigned char sil[160] = { [0 ... 159] = 0xd5 };

			while (gap) {
				uint32_t k = gap > sizeof sil ? (uint32_t)sizeof sil : (uint32_t)gap;

				put_audio(sil, k); gap -= k;
				if (W.fd < 0) return;
			}
		} else {					/* too long a hole: the run restarts at its own time */
			if (W.ns) flush_frag(0);
			if (W.fd < 0) return;
			audio_discard();
			W.a_pos = wanted;
		}
	}
	for (i = 0; i < h->len; i += n) {			/* chunks of at most 160 bytes (20 ms) */
		n = h->len - i > 160 ? 160 : h->len - i;
		put_audio(d + i, n);
		if (W.fd < 0) return;
	}
}

static void thumb(const struct qhdr *h, const unsigned char *d)
{
	char p[200];
	size_t l = strlen(W.path);
	int fd;

	if (W.fd < 0 || W.thumb_done || h->ts != W.file_key_ts || l < 4 || l >= sizeof p) return;
	memcpy(p, W.path, l - 3); memcpy(p + l - 3, "jpg", 4);
	fd = open(p, O_WRONLY | O_CREAT | O_TRUNC, 0644);
	if (fd < 0) return;
	if (write_all(fd, d, h->len) == 0) { W.thumbs++; W.thumb_done = 1; }
	close(fd);
}

static void handle(struct qhdr *h, const unsigned char *d)
{
	struct nal u[32];
	const struct nal *vps = NULL, *sps = NULL, *pps = NULL;
	int n, i, codec, key = (h->flags & QF_KEY) != 0;
	uint64_t ts = h->ts;

	if (h->flags & QF_THUMB) { thumb(h, d); return; }
	if (h->flags & QF_AUDIO) { append_audio(h, d); return; }
	codec = (h->flags & QF_HEVC) ? C_H265 : C_H264;
	if (codec != W.codec) { finish_file(); W.codec = codec; W.waiting_key = 1; }
	n = mp4_split_nals(d, h->len, u, 32);
	if (n <= 0) return;
	for (i = 0; i < n; i++) {
		int t = mp4_nal_type(codec, &u[i]);

		if (codec == C_H265) { if (t == 32) vps = &u[i]; else if (t == 33) sps = &u[i]; else if (t == 34) pps = &u[i]; }
		else { if (t == 7) sps = &u[i]; else if (t == 8) pps = &u[i]; }
	}
	/* frames can leave the encoder in a burst: at least 10 ms between blocks, the clock catches up afterwards */
	if (W.last_ts && ts < W.last_ts + 10000 && !(h->flags & QF_GAP)) ts = W.last_ts + 10000;
	if (h->flags & QF_GAP) { flush_frag(0); W.waiting_key = 1; }
	if (W.waiting_key && !key) return;
	if (key && sps && pps && (codec == C_H264 || vps) && sps->n <= PS_MAX && pps->n <= PS_MAX && (!vps || vps->n <= PS_MAX)) {
		int changed = W.fd >= 0 && (!same_ps(0, vps) || !same_ps(1, sps) || !same_ps(2, pps));
		int rotate = W.fd >= 0 && ts - W.file_t0 >= (uint64_t)C.segment_s * 1000000ULL;

		if (changed || rotate) { flush_frag(ts); finish_file(); }
		if (W.fd < 0) {
			uint64_t now = now_us();

			if (now < W.retry_at) return;
			memset(&W.vi, 0, sizeof W.vi); W.vi.chroma = 1;
			if ((codec == C_H265 ? mp4_parse_sps265(sps, &W.vi) : mp4_parse_sps264(sps, &W.vi)) != 0) {
				set_state("bad-sps"); W.retry_at = now + 30000000ULL; return;
			}
			W.last_ts = ts;
			if (open_file(vps, sps, pps, ts, h->ts) != 0) {
				if (errno == ENODEV || errno == ENOSPC) W.retry_at = now + 30000000ULL; else fail("open");
				W.waiting_key = 1;
				return;
			}
		}
		W.waiting_key = 0;
	}
	if (W.fd < 0) { W.waiting_key = 1; return; }
	W.last_ts = ts;
	if (W.ns && (key || ts - W.s[0].ts >= FRAG_US || W.ns >= FRAG_MAX_SAMPLES || W.data.n > FRAG_MAX_BYTES)) flush_frag(ts);
	if (W.fd < 0) return;
	append_sample(u, n, key, ts);
}

static int paused(void)
{
	char p[128];

	if (!C.status[0]) return 0;
	snprintf(p, sizeof p, "%s.pause", C.status);
	return access(p, F_OK) == 0;
}

static void write_status(uint64_t now)
{
	char tmp[128], b[640];
	int fd, n;
	static const char *mn[] = { "off", "always", "offline", "motion" };

	if (!C.status[0]) return;
	n = snprintf(b, sizeof b,
		     "mode=%s\nrtsp_client=%d\nstate=%s\nfile=%s\nfiles=%llu\nbytes=%llu\nframes=%lu\ndropped=%lu\ncodec=%s\n"
		     "size=%dx%d\nfree_mb=%lu\nuptime_s=%llu\nthumbs=%llu\naudio=%s\nasamples=%llu\n",
		     mn[C.mode & 3], W.watched, W.state, W.path, W.files, W.bytes, (unsigned long)q_pushed,
		     (unsigned long)q_dropped, W.codec == C_H265 ? "h265" : W.codec == C_H264 ? "h264" : "none", W.vi.w, W.vi.h,
		     w_card_ok && !w_paused ? free_mb() : 0UL, (unsigned long long)(now / 1000000ULL), W.thumbs,
		     C.audio ? "alaw" : "off", W.asamples);
	if (n <= 0 || n >= (int)sizeof b) return;
	snprintf(tmp, sizeof tmp, "%s.tmp", C.status);
	fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC, 0644);
	if (fd < 0) return;
	if (write_all(fd, b, (size_t)n) == 0) { close(fd); rename(tmp, C.status); } else { close(fd); unlink(tmp); }
	W.state_dirty = 0;
}

/* configuration from the main thread (sequence count: odd while it is being written) */
static void cfg_pull(void)
{
	unsigned s1, s2;
	struct rec_cfg t;

	if (c_seq == W.seen_seq) return;
	for (;;) {
		s1 = c_seq; BARRIER();
		t = c_pub; BARRIER();
		s2 = c_seq;
		if (s1 == s2 && !(s1 & 1)) break;
		usleep(1000);
	}
	W.seen_seq = s1;
	if (strcmp(t.dir, C.dir) || t.mode != C.mode || t.audio != C.audio) { finish_file(); W.waiting_key = 1; W.next_card = 0; }
	if (t.segment_s < 30) t.segment_s = 30;
	if (t.reserve_mb < 16) t.reserve_mb = 16;
	if (t.offline_s < 0) t.offline_s = 0;
	if (t.postroll_s < 0) t.postroll_s = 0;
	C = t;
}

/* record now? (stream clock: the monotonic clock) */
static void update_want(uint64_t now)
{
	int watched = r_watched, motion = r_motion;

	W.watched = watched;
	switch (C.mode) {
	case REC_ALWAYS:
		W.want = 1;
		break;
	case REC_OFFLINE:
		if (!W.last_watched) W.last_watched = now;	/* grace at start: the recorder connects */
		if (watched) { W.last_watched = now; if (!W.watch_since) W.watch_since = now; }
		else W.watch_since = 0;
		if (now - W.last_watched >= (uint64_t)C.offline_s * 1000000ULL) W.want = 1;
		else if (W.want && W.watch_since && now - W.watch_since >= (uint64_t)C.postroll_s * 1000000ULL) W.want = 0;
		break;
	case REC_MOTION:
		if (motion) W.last_motion = now;
		W.want = W.last_motion && now - W.last_motion < (uint64_t)C.postroll_s * 1000000ULL + 1000000ULL;
		break;
	default:
		W.want = 0;
	}
}

static void *writer(void *arg)
{
	(void)arg;
	setpriority(PRIO_PROCESS, 0, 10);	/* this thread only (Linux): the encoder loop goes first */
	W.waiting_key = 1;
	set_state("waiting");
	while (!w_stop) {
		uint64_t now = now_us();
		struct qhdr h;
		const unsigned char *d;
		int got;

		cfg_pull();
		if (now >= W.next_pause) { W.next_pause = now + 500000; w_paused = C.mode != REC_OFF && paused(); }
		if (C.mode != REC_OFF && !w_paused && now >= W.next_card) {	/* card check: 30 s when fine, 10 s when not */
			w_card_ok = dir_ok();
			W.next_card = now + (w_card_ok ? 30000000ULL : 10000000ULL);
		}
		if (C.mode == REC_OFF || w_paused || !w_card_ok) {
			finish_file();
			W.waiting_key = 1; W.want = 0; W.last_watched = W.watch_since = 0;
			set_state(C.mode == REC_OFF ? "off" : w_paused ? "paused" : "no-card");
			q_trim(0);
			if (W.state_dirty || now - W.last_status >= 10000000ULL) { W.last_status = now; write_status(now); }
			usleep(200000);
			continue;
		}
		update_want(now);
		if (!W.want) {			/* standby: nothing written, the queue keeps a few seconds as pre-roll */
			finish_file();
			W.waiting_key = 1;
			set_state("standby");
			q_trim(q_size * 6 / 10);
			if (W.state_dirty || now - W.last_status >= 10000000ULL) { W.last_status = now; write_status(now); }
			usleep(200000);
			continue;
		}
		got = q_peek(&h, &d);
		if (got) {
			if (!(h.flags & QF_AUDIO)) W.last_rx = now;	/* the pictures decide when the stream stopped */
			handle(&h, d);
			q_pop(&h);
		} else {
			if (W.fd >= 0 && now - W.last_rx > 3000000ULL) {	/* no frames for 3 s: stream stopped */
				finish_file(); set_state("waiting"); W.waiting_key = 1;
			} else if (W.fd < 0 && strcmp(W.state, "error") && strcmp(W.state, "full") && strcmp(W.state, "bad-sps")) {
				set_state("waiting");
			}
			usleep(40000);
		}
		if (W.fd >= 0 && now - W.last_space >= 60000000ULL) {
			W.last_space = now;
			make_room();
		}
		if (W.state_dirty || now - W.last_status >= 10000000ULL) { W.last_status = now; write_status(now); }
	}
	finish_file();
	set_state("off");
	write_status(now_us());
	w_done = 1;
	return NULL;
}

int rec_config(const struct rec_cfg *c)
{
	c_seq++; BARRIER();
	c_pub = *c; BARRIER();
	c_seq++;
	r_mode = c->mode;
	r_audio = c->audio != 0;
	if (c->mode != REC_OFF && !w_run && !w_stop) {
		size_t kb = c->ring_kb >= 128 && c->ring_kb <= 8192 ? (size_t)c->ring_kb : 1024;
		pthread_t th;

		if (!q_buf) {
			q_buf = malloc(kb * 1024);
			if (!q_buf) { RLOG("no memory for a %u KB queue: not recording\n", (unsigned)kb); return -1; }
			q_size = kb * 1024; q_head = q_tail = 0;
		}
		if (pthread_create(&th, NULL, writer, NULL) != 0) { RLOG("no writer thread: not recording\n"); return -1; }
		w_run = 1;
		RLOG("recorder started: %s, %u KB queue\n", c->dir, (unsigned)kb);
	}
	return 0;
}

void rec_shutdown(void)
{
	int i;

	if (!w_run) return;
	w_stop = 1;
	for (i = 0; i < 60 && !w_done; i++) usleep(50000);
}
