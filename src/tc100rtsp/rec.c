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

#define RLOG(...) do { char _b[300]; int _n = snprintf(_b, sizeof _b, "rec: " __VA_ARGS__); \
	_n = _n > (int)sizeof _b - 1 ? (int)sizeof _b - 1 : _n; if (_n > 0) (void)!write(2, _b, _n); } while (0)
#define BARRIER() __asm__ __volatile__("" ::: "memory")

#define TS		90000ULL	/* MP4 media timescale */
#define FRAG_US		1000000ULL	/* one fragment per second at most */
#define FRAG_MAX_SAMPLES 128		/* a whole GOP of pre-roll fits */
#define FRAG_MAX_BYTES	(384 * 1024)
#define PS_MAX		256

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
#define Q_WRAP		0xffffffffu

static unsigned char *q_buf;
static size_t q_size;
static volatile size_t q_head, q_tail;		/* head: written by the producer only, tail: by the writer only */
static int p_gap;				/* producer: a frame was dropped since the last push */
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
	if (!(flags & QF_THUMB)) { if (p_gap) h.flags |= QF_GAP; p_gap = 0; }
	memcpy(q_buf + head, &h, sizeof h);
	memcpy(q_buf + head + sizeof h, d, len);
	head += need;
	if (head == q_size) head = 0;
	BARRIER();
	q_head = head;
	q_pushed++;
	return 0;
drop:
	if (!(flags & QF_THUMB)) p_gap = 1;	/* a lost picture is no hole in the video */
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

/* ---- bit stream (from src/tc100fix/rec.c) -------------------------------------------------------------------- */
enum { C_NONE, C_H264, C_H265 };
struct nal { const unsigned char *p; uint32_t n; };

static int split_nals(const unsigned char *b, uint32_t len, struct nal *out, int max)
{
	uint32_t i = 0, start = 0;
	int n = 0, in = 0;

	while (i + 2 < len) {
		if (b[i] == 0 && b[i + 1] == 0 && b[i + 2] == 1) {
			if (in && n < max) {
				uint32_t e = i;

				while (e > start && b[e - 1] == 0) e--;
				out[n].p = b + start; out[n].n = e - start; if (out[n].n) n++;
			}
			i += 3; start = i; in = 1;
			continue;
		}
		i++;
	}
	if (in && n < max && len > start) { out[n].p = b + start; out[n].n = len - start; n++; }
	return n;
}

static int nal_type(int codec, const struct nal *u) { return codec == C_H265 ? (u->p[0] >> 1) & 0x3f : u->p[0] & 0x1f; }

static int rbsp(const unsigned char *s, int n, unsigned char *d, int max)
{
	int i, o = 0, z = 0;

	for (i = 0; i < n && o < max; i++) {
		if (z >= 2 && s[i] == 3) { z = 0; continue; }
		d[o++] = s[i];
		z = s[i] ? 0 : z + 1;
	}
	return o;
}

struct bits { const unsigned char *b; int n, pos, err; };
static unsigned rb(struct bits *g, int k)
{
	unsigned v = 0;

	while (k-- > 0) {
		if (g->pos >= g->n * 8) { g->err = 1; return 0; }
		v = (v << 1) | ((g->b[g->pos >> 3] >> (7 - (g->pos & 7))) & 1);
		g->pos++;
	}
	return v;
}
static unsigned ue(struct bits *g)
{
	int z = 0;

	while (!g->err && rb(g, 1) == 0 && z < 32) z++;
	if (z >= 32) { g->err = 1; return 0; }
	return ((1u << z) - 1) + rb(g, z);
}
static int se(struct bits *g) { unsigned v = ue(g); return (v & 1) ? (int)((v + 1) / 2) : -(int)(v / 2); }

struct vinfo { int w, h, chroma, depth_l, depth_c; unsigned char ptl[12]; };

static int parse_sps264(const struct nal *u, struct vinfo *vi)
{
	unsigned char r[PS_MAX];
	struct bits g;
	unsigned prof, cf = 1, wm, hm, fmo, cl = 0, cr = 0, ct = 0, cb = 0, i, j;

	g.n = rbsp(u->p + 1, (int)u->n - 1, r, sizeof r); g.b = r; g.pos = 0; g.err = 0;
	prof = rb(&g, 8); rb(&g, 16); ue(&g);
	if (prof == 100 || prof == 110 || prof == 122 || prof == 244 || prof == 44 || prof == 83 ||
	    prof == 86 || prof == 118 || prof == 128 || prof == 138 || prof == 139 || prof == 134 || prof == 135) {
		cf = ue(&g);
		if (cf == 3) rb(&g, 1);
		ue(&g); ue(&g); rb(&g, 1);
		if (rb(&g, 1))
			for (i = 0; i < (cf != 3 ? 8u : 12u); i++)
				if (rb(&g, 1)) {
					int last = 8, next = 8, sz = i < 6 ? 16 : 64;

					for (j = 0; j < (unsigned)sz; j++) {
						if (next) next = (last + se(&g) + 256) % 256;
						last = next ? next : last;
					}
				}
	}
	ue(&g);
	i = ue(&g);
	if (i == 0) ue(&g);
	else if (i == 1) { rb(&g, 1); se(&g); se(&g); j = ue(&g); while (j-- && !g.err) se(&g); }
	ue(&g); rb(&g, 1);
	wm = ue(&g); hm = ue(&g); fmo = rb(&g, 1);
	if (!fmo) rb(&g, 1);
	rb(&g, 1);
	if (rb(&g, 1)) { cl = ue(&g); cr = ue(&g); ct = ue(&g); cb = ue(&g); }
	if (g.err) return -1;
	vi->w = (int)((wm + 1) * 16 - (cl + cr) * (cf ? 2 : 1));
	vi->h = (int)((2 - fmo) * (hm + 1) * 16 - (ct + cb) * (cf == 1 ? 2 : 1) * (2 - fmo));
	return vi->w > 0 && vi->h > 0 ? 0 : -1;
}

static int parse_sps265(const struct nal *u, struct vinfo *vi)
{
	unsigned char r[PS_MAX];
	struct bits g;
	unsigned msl, i, pp[8], lp[8], w, h, cf, sw, sh, cl = 0, cr = 0, ct = 0, cb = 0;

	if (u->n < 16) return -1;
	g.n = rbsp(u->p + 2, (int)u->n - 2, r, sizeof r); g.b = r; g.pos = 0; g.err = 0;
	if (g.n < 14) return -1;
	rb(&g, 4); msl = rb(&g, 3); rb(&g, 1);
	memcpy(vi->ptl, r + 1, 12);
	g.pos += 96;
	for (i = 0; i < msl; i++) { pp[i] = rb(&g, 1); lp[i] = rb(&g, 1); }
	if (msl > 0) for (i = msl; i < 8; i++) rb(&g, 2);
	for (i = 0; i < msl; i++) { if (pp[i]) g.pos += 88; if (lp[i]) g.pos += 8; }
	ue(&g);
	cf = ue(&g);
	if (cf == 3) rb(&g, 1);
	w = ue(&g); h = ue(&g);
	if (rb(&g, 1)) { cl = ue(&g); cr = ue(&g); ct = ue(&g); cb = ue(&g); }
	vi->depth_l = (int)ue(&g); vi->depth_c = (int)ue(&g);
	if (g.err || cf > 3) return -1;
	sw = (cf == 1 || cf == 2) ? 2 : 1; sh = cf == 1 ? 2 : 1;
	vi->chroma = (int)cf;
	vi->w = (int)(w - (cl + cr) * sw);
	vi->h = (int)(h - (ct + cb) * sh);
	return vi->w > 0 && vi->h > 0 ? 0 : -1;
}

/* ---- growable buffer and MP4 boxes (src/tc100fix/rec.c) -------------------------------------------------------- */
struct buf { unsigned char *p; size_t n, cap; int err; };

static void b_need(struct buf *b, size_t k)
{
	size_t c;
	unsigned char *np;

	if (b->err || b->n + k <= b->cap) return;
	c = b->cap ? b->cap : 4096;
	while (c < b->n + k) c *= 2;
	np = realloc(b->p, c);
	if (!np) { b->err = 1; return; }
	b->p = np; b->cap = c;
}
static void b_put(struct buf *b, const void *d, size_t k) { b_need(b, k); if (!b->err) { memcpy(b->p + b->n, d, k); b->n += k; } }
static void b8(struct buf *b, unsigned v) { unsigned char c = (unsigned char)v; b_put(b, &c, 1); }
static void b16(struct buf *b, unsigned v) { b8(b, v >> 8); b8(b, v); }
static void b32(struct buf *b, uint32_t v) { b16(b, v >> 16); b16(b, v & 0xffff); }
static void b64(struct buf *b, uint64_t v) { b32(b, (uint32_t)(v >> 32)); b32(b, (uint32_t)v); }
static void bzero_(struct buf *b, size_t k) { while (k--) b8(b, 0); }
static size_t box(struct buf *b, const char *t) { size_t at = b->n; b32(b, 0); b_put(b, t, 4); return at; }
static size_t fbox(struct buf *b, const char *t, unsigned v, uint32_t f) { size_t at = box(b, t); b32(b, (v << 24) | f); return at; }
static void end(struct buf *b, size_t at)
{
	uint32_t s = (uint32_t)(b->n - at);

	if (b->err) return;
	b->p[at] = (unsigned char)(s >> 24); b->p[at + 1] = (unsigned char)(s >> 16);
	b->p[at + 2] = (unsigned char)(s >> 8); b->p[at + 3] = (unsigned char)s;
}

static const uint32_t matrix[9] = { 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000 };

/* ftyp + moov: one video track, sample entry avc1 / hvc1 with the parameter sets, fragments announced by mvex */
static void init_segment(struct buf *b, int codec, const struct vinfo *vi,
			 const struct nal *vps, const struct nal *sps, const struct nal *pps)
{
	size_t moov, trak, mdia, minf, stbl, stsd, se_, cfg, dinf, dref, mvex, a;
	int i;

	a = box(b, "ftyp"); b_put(b, "isom", 4); b32(b, 0x200);
	b_put(b, "isomiso6mp41", 12); b_put(b, codec == C_H265 ? "hvc1" : "avc1", 4); end(b, a);

	moov = box(b, "moov");
	a = fbox(b, "mvhd", 0, 0); b32(b, 0); b32(b, 0); b32(b, 1000); b32(b, 0);
	b32(b, 0x10000); b16(b, 0x100); bzero_(b, 10);
	for (i = 0; i < 9; i++) b32(b, matrix[i]);
	bzero_(b, 24); b32(b, 2); end(b, a);

	trak = box(b, "trak");
	a = fbox(b, "tkhd", 0, 3); b32(b, 0); b32(b, 0); b32(b, 1); b32(b, 0); b32(b, 0);
	bzero_(b, 8); b16(b, 0); b16(b, 0); b16(b, 0); b16(b, 0);
	for (i = 0; i < 9; i++) b32(b, matrix[i]);
	b32(b, (uint32_t)vi->w << 16); b32(b, (uint32_t)vi->h << 16); end(b, a);

	mdia = box(b, "mdia");
	a = fbox(b, "mdhd", 0, 0); b32(b, 0); b32(b, 0); b32(b, (uint32_t)TS); b32(b, 0);
	b16(b, 0x55c4); b16(b, 0); end(b, a);
	a = fbox(b, "hdlr", 0, 0); b32(b, 0); b_put(b, "vide", 4); bzero_(b, 12);
	b_put(b, "VideoHandler", 13); end(b, a);
	minf = box(b, "minf");
	a = fbox(b, "vmhd", 0, 1); bzero_(b, 8); end(b, a);
	dinf = box(b, "dinf"); dref = fbox(b, "dref", 0, 0); b32(b, 1);
	a = fbox(b, "url ", 0, 1); end(b, a); end(b, dref); end(b, dinf);

	stbl = box(b, "stbl");
	stsd = fbox(b, "stsd", 0, 0); b32(b, 1);
	se_ = box(b, codec == C_H265 ? "hvc1" : "avc1");
	bzero_(b, 6); b16(b, 1); bzero_(b, 16);
	b16(b, (unsigned)vi->w); b16(b, (unsigned)vi->h);
	b32(b, 0x480000); b32(b, 0x480000); b32(b, 0); b16(b, 1);
	bzero_(b, 32); b16(b, 0x18); b16(b, 0xffff);
	if (codec == C_H265) {
		const struct nal *arr[3];
		int t[3] = { 32, 33, 34 };

		arr[0] = vps; arr[1] = sps; arr[2] = pps;
		cfg = box(b, "hvcC");
		b8(b, 1); b_put(b, vi->ptl, 12);
		b16(b, 0xf000); b8(b, 0xfc); b8(b, 0xfc | (vi->chroma & 3));
		b8(b, 0xf8 | (vi->depth_l & 7)); b8(b, 0xf8 | (vi->depth_c & 7));
		b16(b, 0); b8(b, 0x0f); b8(b, 3);
		for (i = 0; i < 3; i++) { b8(b, 0x80 | t[i]); b16(b, 1); b16(b, arr[i]->n); b_put(b, arr[i]->p, arr[i]->n); }
		end(b, cfg);
	} else {
		cfg = box(b, "avcC");
		b8(b, 1); b8(b, sps->p[1]); b8(b, sps->p[2]); b8(b, sps->p[3]); b8(b, 0xff);
		b8(b, 0xe1); b16(b, sps->n); b_put(b, sps->p, sps->n);
		b8(b, 1); b16(b, pps->n); b_put(b, pps->p, pps->n);
		end(b, cfg);
	}
	end(b, se_); end(b, stsd);
	a = fbox(b, "stts", 0, 0); b32(b, 0); end(b, a);
	a = fbox(b, "stsc", 0, 0); b32(b, 0); end(b, a);
	a = fbox(b, "stsz", 0, 0); b32(b, 0); b32(b, 0); end(b, a);
	a = fbox(b, "stco", 0, 0); b32(b, 0); end(b, a);
	end(b, stbl); end(b, minf); end(b, mdia); end(b, trak);

	mvex = box(b, "mvex");
	a = fbox(b, "trex", 0, 0); b32(b, 1); b32(b, 1); b32(b, 0); b32(b, 0); b32(b, 0); end(b, a);
	end(b, mvex);
	end(b, moov);
}

/* ---- configuration and inputs (main thread -> writer) -------------------------------------------------------- */
static struct rec_cfg c_pub, C;		/* c_pub: written by the main thread under a sequence count; C: writer's copy */
static volatile unsigned c_seq;
static volatile int r_mode, r_watched, r_motion;
static volatile int w_run, w_stop, w_done, w_card_ok, w_paused;

int rec_active(void) { return w_run && !w_stop && r_mode != REC_OFF && w_card_ok && !w_paused; }

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

static void frag_reset(void) { W.data.n = 0; W.data.err = 0; W.ns = 0; }

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
	size_t moof, traf, a, trun_off;
	unsigned char mh[8];
	uint32_t mdat = (uint32_t)(8 + W.data.n), off;
	int i;

	if (W.ns == 0 || W.fd < 0) { frag_reset(); return; }
	if (W.data.err) { frag_reset(); W.waiting_key = 1; return; }
	if (next_ts <= W.s[W.ns - 1].ts) {
		uint64_t d = W.ns > 1 ? (W.s[W.ns - 1].ts - W.s[0].ts) / (uint64_t)(W.ns - 1) : 66000;

		next_ts = W.s[W.ns - 1].ts + (d ? d : 66000);
	}
	moof = box(&m, "moof");
	a = fbox(&m, "mfhd", 0, 0); b32(&m, ++W.seq); end(&m, a);
	traf = box(&m, "traf");
	a = fbox(&m, "tfhd", 0, 0x020000); b32(&m, 1); end(&m, a);
	a = fbox(&m, "tfdt", 1, 0); b64(&m, (W.s[0].ts - W.file_t0) * 9 / 100); end(&m, a);
	a = fbox(&m, "trun", 0, 0x000701); b32(&m, (uint32_t)W.ns);
	trun_off = m.n; b32(&m, 0);
	for (i = 0; i < W.ns; i++) {
		uint64_t t1 = i + 1 < W.ns ? W.s[i + 1].ts : next_ts;
		uint64_t d = ((t1 - W.file_t0) * 9 / 100) - ((W.s[i].ts - W.file_t0) * 9 / 100);

		b32(&m, (uint32_t)d); b32(&m, W.s[i].size);
		b32(&m, W.s[i].key ? 0x02000000u : 0x01010000u);
	}
	end(&m, a); end(&m, traf); end(&m, moof);
	if (m.err) { free(m.p); frag_reset(); W.waiting_key = 1; return; }
	off = (uint32_t)(m.n + 8);			/* data offset: from the moof start to the first sample */
	m.p[trun_off] = (unsigned char)(off >> 24); m.p[trun_off + 1] = (unsigned char)(off >> 16);
	m.p[trun_off + 2] = (unsigned char)(off >> 8); m.p[trun_off + 3] = (unsigned char)off;
	mh[0] = (unsigned char)(mdat >> 24); mh[1] = (unsigned char)(mdat >> 16);
	mh[2] = (unsigned char)(mdat >> 8); mh[3] = (unsigned char)mdat; memcpy(mh + 4, "mdat", 4);
	if (write_all(W.fd, m.p, m.n) != 0 || write_all(W.fd, mh, 8) != 0 || write_all(W.fd, W.data.p, W.data.n) != 0) {
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
	init_segment(&b, W.codec, &W.vi, vps, sps, pps);
	if (b.err || write_all(W.fd, b.p, b.n) != 0) {
		int e = errno;

		free(b.p); close(W.fd); W.fd = -1; unlink(W.path); W.path[0] = 0; errno = e ? e : ENOMEM;
		return -1;
	}
	W.bytes += b.n;
	free(b.p);
	W.file_t0 = ts; W.file_key_ts = key_ts; W.last_sync = ts; W.files++; W.thumb_done = 0; W.seq = 0;
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
		int t = nal_type(W.codec, &u[i]);

		if (W.codec == C_H265 ? (t >= 32 && t <= 35) : (t == 7 || t == 8 || t == 9)) continue;
		b32(&W.data, u[i].n); b_put(&W.data, u[i].p, u[i].n);
		size += 4 + u[i].n;
	}
	if (W.data.err) { frag_reset(); W.waiting_key = 1; return; }
	if (!size) return;
	W.s[W.ns].size = (uint32_t)size; W.s[W.ns].key = (uint32_t)key; W.s[W.ns].ts = ts;
	W.ns++;
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
	codec = (h->flags & QF_HEVC) ? C_H265 : C_H264;
	if (codec != W.codec) { finish_file(); W.codec = codec; W.waiting_key = 1; }
	n = split_nals(d, h->len, u, 32);
	if (n <= 0) return;
	for (i = 0; i < n; i++) {
		int t = nal_type(codec, &u[i]);

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
			if ((codec == C_H265 ? parse_sps265(sps, &W.vi) : parse_sps264(sps, &W.vi)) != 0) {
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
		     "size=%dx%d\nfree_mb=%lu\nuptime_s=%llu\nthumbs=%llu\n",
		     mn[C.mode & 3], W.watched, W.state, W.path, W.files, W.bytes, (unsigned long)q_pushed,
		     (unsigned long)q_dropped, W.codec == C_H265 ? "h265" : W.codec == C_H264 ? "h264" : "none", W.vi.w, W.vi.h,
		     w_card_ok && !w_paused ? free_mb() : 0UL, (unsigned long long)(now / 1000000ULL), W.thumbs);
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
	if (strcmp(t.dir, C.dir) || t.mode != C.mode) { finish_file(); W.waiting_key = 1; W.next_card = 0; }
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
			W.last_rx = now;
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
