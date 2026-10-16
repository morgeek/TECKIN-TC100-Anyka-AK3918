/*
 * rec.c — local backup recording for libtc100fix: the H.264/H.265 frames the
 * SoC encoder already produces for RTSP are copied, as they are handed to
 * v4l2rtspserver, into fragmented MP4 files. No decoding, no re-encoding.
 *
 * TC100FIX_REC_DIR=<dir>        enable; <dir> must exist and must not be in RAM
 *                               or on the flash (tmpfs, ramfs, jffs2, squashfs
 *                               are refused), e.g. the SD card
 * TC100FIX_REC_SEGMENT_SEC=300  length of one file (cut at the next keyframe)
 * TC100FIX_REC_RESERVE_MB=256   keep this much free: oldest files are deleted
 * TC100FIX_REC_STREAM=main|sub  which encoder output (largest = main)
 * TC100FIX_REC_STATUS=<path>    status line, every 10 s (default /var/run/tc100rec)
 * TC100FIX_REC_WHEN=offline     record only while the recorder is not receiving
 *                               the RTSP stream (always = all the time)
 * TC100FIX_REC_CLIENT=<ipv4>    the recorder (default: any remote client)
 * TC100FIX_REC_OFFLINE_SEC=10   start this long after the stream stops flowing
 *                               (the file starts at the keyframe before: pre-roll)
 * TC100FIX_REC_POSTROLL_SEC=30  keep recording this long after it is back
 * TC100FIX_REC_RING_KB=512      frame queue between the encoder thread and the
 *                               writer (frames are dropped, never waited for,
 *                               when the card is too slow)
 *
 * Files: <dir>/YYYYMMDD/HHMMSS.mp4 (local time). Fragmented MP4 (one fragment
 * a second): a file cut short by a power loss or a card removal stays playable
 * up to its last complete fragment. Recording pauses while <status>.pause
 * exists (e.g. before taking the card out).
 *
 * Hooks: ak_venc_open (encoder size), ak_venc_request_stream (stream ->
 * encoder), ak_venc_get_stream_ex (frames). With TC100FIX_REC_DIR unset they
 * only forward the call.
 *
 * REC_HOST_TEST builds a host program that feeds an Annex-B file through the
 * same path (tests/test_regressions.py).
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
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/types.h>
#include <sys/uio.h>
#include <time.h>
#include <unistd.h>
#ifndef REC_HOST_TEST
#include <dlfcn.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#endif

#define TAG "[tc100fix] rec: "
#define TS 90000ULL                     /* MP4 media timescale */
#define FRAG_US 1000000ULL              /* one fragment per second */
#define FRAG_MAX_SAMPLES 128            /* a whole GOP of pre-roll fits */
#define PS_MAX 256                      /* parameter set size limit */

/* ---------------------------------------------------------------- queue */

struct qhdr { uint32_t len; uint32_t gap; uint64_t ts; };
#define Q_WRAP 0xffffffffu

static unsigned char *q_buf;
static size_t q_size, q_head, q_tail;   /* head: write, tail: read */
static int q_gap;                       /* frames dropped before the next push */
static unsigned long q_dropped, q_pushed;
static pthread_mutex_t q_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t q_cond = PTHREAD_COND_INITIALIZER;

static uint64_t now_us(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000ULL + (uint64_t)t.tv_nsec / 1000;
}

/* Called from the encoder thread: never blocks on the card. 0 if queued. */
static int q_push(const unsigned char *data, uint32_t len, uint64_t ts)
{
    size_t need = sizeof(struct qhdr) + ((len + 7u) & ~7u);
    struct qhdr h;

    pthread_mutex_lock(&q_lock);
    if (need > q_size / 2)
        goto drop;
    if (q_head >= q_tail) {
        if (q_size - q_head < need || (q_size - q_head == need && q_tail == 0)) {
            if (q_tail <= need)                 /* wrapping would reach the reader */
                goto drop;
            if (q_size - q_head >= sizeof(struct qhdr)) {
                h.len = Q_WRAP; h.gap = 0; h.ts = 0;
                memcpy(q_buf + q_head, &h, sizeof(h));
            }
            q_head = 0;
        }
    } else if (q_tail - q_head <= need) {
        goto drop;
    }
    h.len = len; h.gap = (uint32_t)q_gap; h.ts = ts;
    memcpy(q_buf + q_head, &h, sizeof(h));
    memcpy(q_buf + q_head + sizeof(h), data, len);
    q_head += need;
    if (q_head == q_size)
        q_head = 0;
    q_gap = 0;
    q_pushed++;
    pthread_cond_signal(&q_cond);
    pthread_mutex_unlock(&q_lock);
    return 0;
drop:
    q_gap = 1;
    q_dropped++;
    pthread_mutex_unlock(&q_lock);
    return -1;
}

/* Writer side: next record, in place (the producer never overwrites it). */
static int q_peek(struct qhdr *h, const unsigned char **data, int wait_ms)
{
    int got = 0;
    pthread_mutex_lock(&q_lock);
    for (;;) {
        if (q_tail != q_head) {
            if (q_size - q_tail < sizeof(struct qhdr)) { q_tail = 0; continue; }
            memcpy(h, q_buf + q_tail, sizeof(*h));
            if (h->len == Q_WRAP) { q_tail = 0; continue; }
            *data = q_buf + q_tail + sizeof(*h);
            got = 1;
            break;
        }
        if (wait_ms <= 0)
            break;
        {
            struct timespec t;
            clock_gettime(CLOCK_REALTIME, &t);
            t.tv_sec += wait_ms / 1000;
            t.tv_nsec += (long)(wait_ms % 1000) * 1000000L;
            if (t.tv_nsec >= 1000000000L) { t.tv_sec++; t.tv_nsec -= 1000000000L; }
            if (pthread_cond_timedwait(&q_cond, &q_lock, &t) == ETIMEDOUT)
                wait_ms = 0;
        }
    }
    pthread_mutex_unlock(&q_lock);
    return got;
}

static void q_pop(const struct qhdr *h)
{
    pthread_mutex_lock(&q_lock);
    q_tail += sizeof(*h) + ((h->len + 7u) & ~7u);
    if (q_tail >= q_size)
        q_tail = 0;
    pthread_mutex_unlock(&q_lock);
}

/* ------------------------------------------------------------ bitstream */

enum { C_NONE, C_H264, C_H265 };

struct nal { const unsigned char *p; uint32_t n; };

/* Split an Annex-B access unit into NAL units (start codes removed). */
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
    if (in && n < max && len > start) {
        out[n].p = b + start; out[n].n = len - start; n++;
    }
    return n;
}

static int nal_type(int codec, const struct nal *u)
{
    return codec == C_H265 ? (u->p[0] >> 1) & 0x3f : u->p[0] & 0x1f;
}

static int detect_codec(const struct nal *u, int n)
{
    int i;
    for (i = 0; i < n; i++) {
        if (u[i].n >= 2 && u[i].p[0] == 0x40 && u[i].p[1] == 0x01)
            return C_H265;                       /* VPS */
        if (u[i].n >= 4 && (u[i].p[0] & 0x9f) == 0x07)
            return C_H264;                       /* SPS */
    }
    return C_NONE;
}

/* RBSP: remove emulation prevention bytes. */
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
    g.n = rbsp(u->p + 1, (int)u->n - 1, r, sizeof(r)); g.b = r; g.pos = 0; g.err = 0;
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
    unsigned msl, i, pp[8], lp[8], w, h, cf, sw, sh;
    unsigned cl = 0, cr = 0, ct = 0, cb = 0;
    if (u->n < 16) return -1;
    g.n = rbsp(u->p + 2, (int)u->n - 2, r, sizeof(r)); g.b = r; g.pos = 0; g.err = 0;
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

/* ------------------------------------------------------------ MP4 boxes */

struct buf { unsigned char *p; size_t n, cap; int err; };
static void b_need(struct buf *b, size_t k)
{
    if (b->err || b->n + k <= b->cap) return;
    {
        size_t c = b->cap ? b->cap : 4096;
        unsigned char *np;
        while (c < b->n + k) c *= 2;
        np = realloc(b->p, c);
        if (!np) { b->err = 1; return; }
        b->p = np; b->cap = c;
    }
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
        const struct nal *arr[3]; int t[3] = { 32, 33, 34 };
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

/* ---------------------------------------------------------------- writer */

static const char *r_dir, *r_status;
static unsigned r_segment_us_sec = 300, r_reserve_mb = 256;

/* TC100FIX_REC_WHEN=offline: record only while nobody (or not the recorder
 * TC100FIX_REC_CLIENT, an IPv4 address) is receiving the RTSP stream. */
static int r_offline;                    /* 0: always record */
static unsigned r_client;                /* /proc/net/tcp byte order, 0 = any */
static unsigned r_rtsp_port = 554;
static uint64_t r_offline_us = 10000000ULL, r_postroll_us = 30000000ULL;
static const char *r_tcp = "/proc/net/tcp";

struct sample { uint32_t size; uint32_t key; uint64_t ts; };

static struct {
    int fd, codec, waiting_key;
    struct vinfo vi;
    unsigned char ps[3][PS_MAX]; uint32_t psn[3];   /* VPS SPS PPS of the open file */
    char path[200];
    uint64_t file_t0, frag_base;
    uint32_t seq;
    struct sample s[FRAG_MAX_SAMPLES]; int ns;
    struct buf data;                                 /* fragment payload */
    uint64_t last_sync, last_ts;
    unsigned long long bytes, files;
    char state[32];
    /* offline mode */
    int want, watched, pre_ok;
    uint64_t last_check, last_watched, watch_since;
    unsigned char pre_ps[3][PS_MAX]; uint32_t pre_psn[3];
    uint64_t last_status, last_space, retry_at;
} W = { .fd = -1 };

static int fs_ok(const char *dir)
{
    struct statfs s;
    if (statfs(dir, &s) != 0) return 0;
#ifdef REC_HOST_TEST
    if (getenv("REC_TEST_ANY_FS")) return 1;   /* CI temp dirs are often tmpfs */
#endif
    switch ((unsigned long)s.f_type) {
    case 0x01021994UL: /* tmpfs */ case 0x858458f6UL: /* ramfs */
    case 0x72b6UL: /* jffs2 */ case 0x73717368UL: /* squashfs */
    case 0x28cd3d45UL: /* cramfs */
        return 0;
    }
    return 1;
}

static unsigned long free_mb(const char *dir)
{
    struct statfs s;
    if (statfs(dir, &s) != 0) return 0;
    return (unsigned long)((unsigned long long)s.f_bavail * s.f_bsize / (1024 * 1024));
}

static int all_digits(const char *s, int n)
{
    int i;
    for (i = 0; i < n; i++) if (s[i] < '0' || s[i] > '9') return 0;
    return s[n] == 0 || s[n] == '.';
}

/* Delete the oldest recording (never the file being written). 0 if none left. */
static int delete_oldest(void)
{
    DIR *d;
    struct dirent *e;
    char day[16] = "", file[32] = "", p[256];
    int found;

    for (;;) {
        day[0] = 0;
        if (!(d = opendir(r_dir))) return 0;
        while ((e = readdir(d)))
            if (strlen(e->d_name) == 8 && all_digits(e->d_name, 8) && (!day[0] || strcmp(e->d_name, day) < 0))
                strcpy(day, e->d_name);
        closedir(d);
        if (!day[0]) return 0;
        snprintf(p, sizeof(p), "%s/%s", r_dir, day);
        file[0] = 0; found = 0;
        if ((d = opendir(p))) {
            while ((e = readdir(d))) {
                size_t l = strlen(e->d_name);
                if (l == 10 && !strcmp(e->d_name + 6, ".mp4") && all_digits(e->d_name, 6)) {
                    found++;
                    if (!file[0] || strcmp(e->d_name, file) < 0) strcpy(file, e->d_name);
                }
            }
            closedir(d);
        }
        if (!file[0]) { rmdir(p); continue; }      /* empty day: drop it, look again */
        snprintf(p, sizeof(p), "%s/%s/%s", r_dir, day, file);
        if (W.fd >= 0 && !strcmp(p, W.path)) return 0;
        if (unlink(p) != 0) return 0;
        if (found == 1) { snprintf(p, sizeof(p), "%s/%s", r_dir, day); rmdir(p); }
        return 1;
    }
}

static void make_room(void)
{
    int n = 0;
    while (free_mb(r_dir) < r_reserve_mb && n++ < 50)
        if (!delete_oldest()) break;
}

static void set_state(const char *s) { snprintf(W.state, sizeof(W.state), "%s", s); }

static int write_all(int fd, struct iovec *iov, int n)
{
    while (n > 0) {
        ssize_t k = writev(fd, iov, n);
        if (k < 0) { if (errno == EINTR) continue; return -1; }
        while (n > 0 && (size_t)k >= iov->iov_len) { k -= (ssize_t)iov->iov_len; iov++; n--; }
        if (n > 0) { iov->iov_base = (char *)iov->iov_base + k; iov->iov_len -= (size_t)k; }
    }
    return 0;
}

static void close_file(void)
{
    if (W.fd >= 0) { fsync(W.fd); close(W.fd); W.fd = -1; }
    W.path[0] = 0;
    W.ns = 0; W.data.n = 0;
}

static void fail(const char *what)
{
    fprintf(stderr, TAG "%s %s: %s, retry in 30 s\n", what, W.path, strerror(errno));
    close_file();
    set_state("error");
    W.retry_at = now_us() + 30000000ULL;
    W.waiting_key = 1;
}

/* Write the pending fragment; last sample lasts until next_ts. */
static void flush_frag(uint64_t next_ts)
{
    struct buf m = { 0 };
    size_t moof, traf, a, trun_off;
    struct iovec iov[3];
    unsigned char mh[8];
    int i;
    uint32_t mdat = (uint32_t)(8 + W.data.n);

    if (W.ns == 0 || W.fd < 0) { W.ns = 0; W.data.n = 0; return; }
    if (next_ts <= W.s[W.ns - 1].ts) {        /* unknown end: average duration */
        uint64_t d = W.ns > 1 ? (W.s[W.ns - 1].ts - W.s[0].ts) / (uint64_t)(W.ns - 1) : 100000;
        next_ts = W.s[W.ns - 1].ts + (d ? d : 100000);
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
    if (m.err) { free(m.p); W.ns = 0; W.data.n = 0; return; }
    {
        uint32_t off = (uint32_t)(m.n + 8);
        m.p[trun_off] = (unsigned char)(off >> 24); m.p[trun_off + 1] = (unsigned char)(off >> 16);
        m.p[trun_off + 2] = (unsigned char)(off >> 8); m.p[trun_off + 3] = (unsigned char)off;
    }
    mh[0] = (unsigned char)(mdat >> 24); mh[1] = (unsigned char)(mdat >> 16);
    mh[2] = (unsigned char)(mdat >> 8); mh[3] = (unsigned char)mdat; memcpy(mh + 4, "mdat", 4);
    iov[0].iov_base = m.p; iov[0].iov_len = m.n;
    iov[1].iov_base = mh; iov[1].iov_len = 8;
    iov[2].iov_base = W.data.p; iov[2].iov_len = W.data.n;
    if (write_all(W.fd, iov, 3) != 0)
        fail("write");
    else {
        W.bytes += m.n + mdat;
        if (W.s[W.ns - 1].ts - W.last_sync >= 10000000ULL) {   /* size on the card every 10 s */
            fdatasync(W.fd);
            W.last_sync = W.s[W.ns - 1].ts;
        }
    }
    free(m.p);
    W.ns = 0; W.data.n = 0;
}

#ifdef REC_HOST_TEST
static int host_finished(void);
static time_t rec_time(uint64_t ts) { return (time_t)1760000000 + (time_t)(ts / 1000000ULL); }
#else
static time_t rec_time(uint64_t ts) { (void)ts; return time(NULL); }
#endif

static int open_file(const struct nal *vps, const struct nal *sps, const struct nal *pps, uint64_t ts)
{
    struct buf b = { 0 };
    struct iovec iov;
    char day[160];
    time_t t = rec_time(ts);
    struct tm tm;
    int k;

    if (!fs_ok(r_dir)) { set_state("no-card"); errno = ENODEV; return -1; }
    make_room();
    if (free_mb(r_dir) < r_reserve_mb / 2 + 8) { set_state("full"); errno = ENOSPC; return -1; }
    for (k = 0; k < 5; k++, t++) {     /* never overwrite: next second if taken */
        localtime_r(&t, &tm);
        snprintf(day, sizeof(day), "%s/%04d%02d%02d", r_dir, tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday);
        mkdir(day, 0755);
        snprintf(W.path, sizeof(W.path), "%s/%02d%02d%02d.mp4", day, tm.tm_hour, tm.tm_min, tm.tm_sec);
        W.fd = open(W.path, O_WRONLY | O_CREAT | O_EXCL, 0644);
        if (W.fd >= 0 || errno != EEXIST) break;
    }
    if (W.fd < 0) return -1;
    init_segment(&b, W.codec, &W.vi, vps, sps, pps);
    iov.iov_base = b.p; iov.iov_len = b.n;
    if (b.err || write_all(W.fd, &iov, 1) != 0) { free(b.p); return -1; }
    W.bytes += b.n;
    free(b.p);
    W.file_t0 = ts; W.seq = 0; W.last_sync = ts; W.files++;
    W.psn[0] = vps ? vps->n : 0; if (vps) memcpy(W.ps[0], vps->p, vps->n);
    W.psn[1] = sps->n; memcpy(W.ps[1], sps->p, sps->n);
    W.psn[2] = pps->n; memcpy(W.ps[2], pps->p, pps->n);
    set_state("recording");
    fprintf(stderr, TAG "%s (%s %dx%d)\n", W.path, W.codec == C_H265 ? "H.265" : "H.264", W.vi.w, W.vi.h);
    return 0;
}

static int same_ps(int i, const struct nal *u)
{
    if (!u) return W.psn[i] == 0;
    return u->n == W.psn[i] && !memcmp(u->p, W.ps[i], u->n);
}

static void write_status(uint64_t now)
{
    char tmp[160];
    FILE *f;
    unsigned long dr, pu;
    if (!r_status) return;
    pthread_mutex_lock(&q_lock); dr = q_dropped; pu = q_pushed; pthread_mutex_unlock(&q_lock);
    snprintf(tmp, sizeof(tmp), "%s.tmp", r_status);
    if (!(f = fopen(tmp, "w"))) return;
    fprintf(f, "mode=%s\nrtsp_client=%d\n", r_offline ? "offline" : "always", W.watched);
    fprintf(f, "state=%s\nfile=%s\nfiles=%llu\nbytes=%llu\nframes=%lu\ndropped=%lu\ncodec=%s\nsize=%dx%d\nfree_mb=%lu\nuptime_s=%llu\n",
            W.state, W.path, W.files, W.bytes, pu, dr,
            W.codec == C_H265 ? "h265" : W.codec == C_H264 ? "h264" : "none", W.vi.w, W.vi.h,
            free_mb(r_dir), (unsigned long long)(now / 1000000ULL));
    fclose(f);
    rename(tmp, r_status);
}

static int paused(void)
{
    char p[160];
    if (!r_status) return 0;
    snprintf(p, sizeof(p), "%s.pause", r_status);
    return access(p, F_OK) == 0;
}

/* A client receiving the RTSP stream: an established connection to the RTSP
 * port from a remote address (from r_client when set) whose data flows: an
 * unacknowledged send queue under 256 KB and no retransmission timeouts. A
 * recorder that lost the network keeps its socket "established" for many
 * minutes on the camera; its queue and timeouts give it away. */
#ifdef REC_HOST_TEST
/* REC_TEST_WATCH="from-to,from-to" (seconds of stream time): a client is
 * watching during those ranges. */
static uint64_t t_watch_ts;
static int rtsp_watched(void)
{
    const char *v = getenv("REC_TEST_WATCH");
    double a, b;
    int k;
    while (v && *v) {
        if (sscanf(v, "%lf-%lf%n", &a, &b, &k) != 2) break;
        if (t_watch_ts >= (uint64_t)(a * 1e6) + 5000000ULL && t_watch_ts < (uint64_t)(b * 1e6) + 5000000ULL) return 1;
        v += k; if (*v == ',') v++;
    }
    return 0;
}
#else
static int rtsp_watched(void)
{
    FILE *f = fopen(r_tcp, "r");
    char line[256];
    int seen = 0;
    if (!f) return 0;
    while (fgets(line, sizeof(line), f)) {
        unsigned lip, lport, rip, rport, st, txq, rxq, tr, retr;
        unsigned long when;
        if (sscanf(line, " %*d: %8X:%4X %8X:%4X %2X %8X:%8X %2X:%8lX %8X",
                   &lip, &lport, &rip, &rport, &st, &txq, &rxq, &tr, &when, &retr) != 10)
            continue;
        if (lport != r_rtsp_port || st != 1 || (rip & 0xff) == 127) continue;
        if (r_client && rip != r_client) continue;
        if (txq < 256 * 1024 && retr == 0) { seen = 1; break; }
    }
    fclose(f);
    return seen;
}
#endif

/* Decide, on the stream clock, whether frames go to a file. */
static void update_want(uint64_t ts)
{
    if (!r_offline) { W.want = 1; return; }
    if (!W.last_check) { W.last_check = ts; W.last_watched = ts; }   /* grace at start */
    if (ts - W.last_check >= 2000000ULL || W.last_check == ts) {
        W.last_check = ts;
#ifdef REC_HOST_TEST
        t_watch_ts = ts;
#endif
        W.watched = rtsp_watched();
        if (W.watched) { W.last_watched = ts; if (!W.watch_since) W.watch_since = ts; }
        else W.watch_since = 0;
    }
    if (ts - W.last_watched >= r_offline_us) W.want = 1;
    else if (W.want && W.watch_since && ts - W.watch_since >= r_postroll_us) W.want = 0;
}

static void append_sample(const struct nal *u, int n, int key, uint64_t ts)
{
    size_t size = 0;
    int i;
    for (i = 0; i < n; i++) {          /* length-prefixed, parameter sets and AUDs left out */
        int t = nal_type(W.codec, &u[i]);
        if (W.codec == C_H265 ? (t >= 32 && t <= 35) : (t == 7 || t == 8 || t == 9)) continue;
        b32(&W.data, u[i].n); b_put(&W.data, u[i].p, u[i].n);
        size += 4 + u[i].n;
    }
    if (W.data.err) { W.data.err = 0; W.data.n = 0; W.ns = 0; W.waiting_key = 1; W.pre_ok = 0; return; }
    if (!size) return;
    W.s[W.ns].size = (uint32_t)size; W.s[W.ns].key = (uint32_t)key; W.s[W.ns].ts = ts;
    W.ns++;
}

static void handle_frame(struct qhdr *h, const unsigned char *data)
{
    struct nal u[24];
    const struct nal *vps = NULL, *sps = NULL, *pps = NULL;
    int n, i, key = 0;

    n = split_nals(data, h->len, u, 24);
    if (n <= 0) return;
    /* Frames can come out of the encoder in a burst (two within microseconds):
     * keep at least 10 ms between samples, the clock catches up afterwards. */
    if (W.last_ts && h->ts < W.last_ts + 10000 && !h->gap)
        h->ts = W.last_ts + 10000;
    W.last_ts = h->ts;
    if (W.codec == C_NONE && (W.codec = detect_codec(u, n)) == C_NONE) return;
    for (i = 0; i < n; i++) {
        int t = nal_type(W.codec, &u[i]);
        if (W.codec == C_H265) {
            if (t == 32) vps = &u[i]; else if (t == 33) sps = &u[i]; else if (t == 34) pps = &u[i];
            else if (t >= 16 && t <= 21) key = 1;
        } else {
            if (t == 7) sps = &u[i]; else if (t == 8) pps = &u[i]; else if (t == 5) key = 1;
        }
    }
    if (h->gap) {                     /* frames were dropped: resume at a keyframe */
        flush_frag(0);
        W.waiting_key = 1;
    }
    update_want(h->ts);
    if (!W.want) {
        /* Standby: keep the frames since the last keyframe as pre-roll. */
        if (W.fd >= 0) { flush_frag(h->ts); close_file(); }
        set_state("standby");
        W.waiting_key = 1;
        if (key && sps && pps && (W.codec == C_H264 || vps) && sps->n <= PS_MAX && pps->n <= PS_MAX && (!vps || vps->n <= PS_MAX)) {
            W.ns = 0; W.data.n = 0; W.pre_ok = 1;
            W.pre_psn[0] = vps ? vps->n : 0; if (vps) memcpy(W.pre_ps[0], vps->p, vps->n);
            W.pre_psn[1] = sps->n; memcpy(W.pre_ps[1], sps->p, sps->n);
            W.pre_psn[2] = pps->n; memcpy(W.pre_ps[2], pps->p, pps->n);
        }
        if (!W.pre_ok || h->gap) { W.pre_ok = 0; W.ns = 0; W.data.n = 0; return; }
        if (W.ns >= FRAG_MAX_SAMPLES || W.data.n > 768 * 1024) { W.pre_ok = 0; W.ns = 0; W.data.n = 0; return; }
        append_sample(u, n, key, h->ts);
        return;
    }
    if (W.fd < 0 && W.pre_ok && W.ns > 0 && !h->gap) {
        /* Recording starts: the file begins with the pre-roll GOP. */
        struct nal pv, ps_, pp;
        uint64_t now = now_us();
        pv.p = W.pre_ps[0]; pv.n = W.pre_psn[0]; ps_.p = W.pre_ps[1]; ps_.n = W.pre_psn[1];
        pp.p = W.pre_ps[2]; pp.n = W.pre_psn[2];
        W.pre_ok = 0;
        memset(&W.vi, 0, sizeof(W.vi)); W.vi.chroma = 1;
        if (now >= W.retry_at && (W.codec == C_H265 ? parse_sps265(&ps_, &W.vi) : parse_sps264(&ps_, &W.vi)) == 0
            && open_file(W.codec == C_H265 ? &pv : NULL, &ps_, &pp, W.s[0].ts) == 0) {
            W.waiting_key = 0;
        } else {
            if (W.fd >= 0) fail("open"); else close_file();
            W.ns = 0; W.data.n = 0;
        }
    }
    W.pre_ok = 0;
    if (W.waiting_key && !key) return;

    if (key && sps && pps && (W.codec == C_H264 || vps) && sps->n <= PS_MAX && pps->n <= PS_MAX && (!vps || vps->n <= PS_MAX)) {
        int changed = W.fd >= 0 && (!same_ps(0, vps) || !same_ps(1, sps) || !same_ps(2, pps));
        int rotate = W.fd >= 0 && h->ts - W.file_t0 >= (uint64_t)r_segment_us_sec * 1000000ULL;
        if (changed || rotate) { flush_frag(h->ts); close_file(); }
        if (W.fd < 0) {
            uint64_t now = now_us();
            if (now < W.retry_at) return;
            memset(&W.vi, 0, sizeof(W.vi)); W.vi.chroma = 1;
            if ((W.codec == C_H265 ? parse_sps265(sps, &W.vi) : parse_sps264(sps, &W.vi)) != 0) {
                set_state("bad-sps"); W.retry_at = now + 30000000ULL; return;
            }
            if (open_file(vps, sps, pps, h->ts) != 0) {
                if (W.fd >= 0 || errno != ENODEV) fail("open"); else { close_file(); W.retry_at = now + 30000000ULL; }
                W.waiting_key = 1;
                return;
            }
        }
        W.waiting_key = 0;
    }
    if (W.fd < 0) { W.waiting_key = 1; return; }

    if (W.ns > 0 && (h->ts - W.s[0].ts >= FRAG_US || W.ns >= FRAG_MAX_SAMPLES || W.data.n > 384 * 1024))
        flush_frag(h->ts);
    if (W.fd < 0) return;
    if (W.ns == 0) W.frag_base = h->ts;
    append_sample(u, n, key, h->ts);
}

static void *writer(void *arg)
{
    struct qhdr h;
    const unsigned char *d = NULL;
    (void)arg;
#ifndef REC_HOST_TEST
    setpriority(PRIO_PROCESS, (id_t)syscall(SYS_gettid), 10);
#endif
    W.waiting_key = 1;
    set_state("waiting");
    for (;;) {
        uint64_t now;
        int got = q_peek(&h, &d, 1000);
        if (got) {
            if (paused()) {
                if (W.fd >= 0) { flush_frag(0); close_file(); }
                set_state("paused"); W.waiting_key = 1;
            } else
                handle_frame(&h, d);
            q_pop(&h);
        }
        now = now_us();
#ifndef REC_HOST_TEST
        if (!got && W.fd >= 0 && W.ns && now - W.s[W.ns - 1].ts > 3000000ULL) {
            flush_frag(0);              /* no frames for 3 s: stream stopped */
            close_file(); set_state("waiting"); W.waiting_key = 1;
        }
#endif
        if (W.fd >= 0 && now - W.last_space >= 60000000ULL) {
            W.last_space = now;
            make_room();
        }
        if (now - W.last_status >= 10000000ULL) { W.last_status = now; write_status(now); }
#ifdef REC_HOST_TEST
        if (!got && host_finished()) { flush_frag(0); close_file(); write_status(now); return NULL; }
#endif
    }
    return NULL;
}

static int rec_setup(void)
{
    const char *v;
    size_t ring = 512;
    r_dir = getenv("TC100FIX_REC_DIR");
    if (!r_dir || !r_dir[0] || strlen(r_dir) > 140) return -1;
    r_status = getenv("TC100FIX_REC_STATUS");
    if (!r_status || !r_status[0]) r_status = "/var/run/tc100rec";
    if ((v = getenv("TC100FIX_REC_SEGMENT_SEC")) && atoi(v) >= 30) r_segment_us_sec = (unsigned)atoi(v);
    if ((v = getenv("TC100FIX_REC_RESERVE_MB")) && atoi(v) >= 16) r_reserve_mb = (unsigned)atoi(v);
    if ((v = getenv("TC100FIX_REC_RING_KB")) && atoi(v) >= 128 && atoi(v) <= 4096) ring = (size_t)atoi(v);
    if ((v = getenv("TC100FIX_REC_WHEN")) && !strcmp(v, "offline")) r_offline = 1;
    if ((v = getenv("TC100FIX_REC_CLIENT")) && v[0]) {
        unsigned a, b, c, d;
        if (sscanf(v, "%u.%u.%u.%u", &a, &b, &c, &d) == 4 && a < 256 && b < 256 && c < 256 && d < 256)
            r_client = (d << 24) | (c << 16) | (b << 8) | a;
    }
    if ((v = getenv("TC100FIX_REC_RTSP_PORT")) && atoi(v) > 0 && atoi(v) < 65536) r_rtsp_port = (unsigned)atoi(v);
    if ((v = getenv("TC100FIX_REC_OFFLINE_SEC")) && atoi(v) >= 0) r_offline_us = (uint64_t)atoi(v) * 1000000ULL;
    if ((v = getenv("TC100FIX_REC_POSTROLL_SEC")) && atoi(v) >= 0) r_postroll_us = (uint64_t)atoi(v) * 1000000ULL;
#ifdef REC_HOST_TEST
    if ((v = getenv("REC_TEST_TCP"))) r_tcp = v;
#endif
    q_size = ring * 1024;
    q_buf = malloc(q_size);
    if (!q_buf) return -1;
    return 0;
}

#ifndef REC_HOST_TEST
/* ----------------------------------------------------------------- hooks */

struct enc_info { void *enc; unsigned long w, h; };
static struct enc_info encs[4];
static struct { void *user, *enc; } users[4];
static void *rec_user;
static int rec_state;                   /* 0 unknown, 1 enabled, -1 disabled */
static pthread_mutex_t h_lock = PTHREAD_MUTEX_INITIALIZER;

void *ak_venc_open(const void *param)
{
    static void *(*real)(const void *);
    void *r;
    int i;
    if (!real) real = (void *(*)(const void *))dlsym(RTLD_NEXT, "ak_venc_open");
    if (!real) return NULL;
    r = real(param);
    if (r && param) {
        pthread_mutex_lock(&h_lock);
        for (i = 0; i < 4; i++)
            if (!encs[i].enc) {
                encs[i].enc = r;
                encs[i].w = ((const unsigned long *)param)[0];
                encs[i].h = ((const unsigned long *)param)[1];
                break;
            }
        pthread_mutex_unlock(&h_lock);
    }
    return r;
}

void *ak_venc_request_stream(void *vi, void *enc)
{
    static void *(*real)(void *, void *);
    void *r;
    int i;
    if (!real) real = (void *(*)(void *, void *))dlsym(RTLD_NEXT, "ak_venc_request_stream");
    if (!real) return NULL;
    r = real(vi, enc);
    if (r) {
        pthread_mutex_lock(&h_lock);
        for (i = 0; i < 4; i++)
            if (!users[i].user) { users[i].user = r; users[i].enc = enc; break; }
        rec_user = NULL;                /* choose again on the next frame */
        pthread_mutex_unlock(&h_lock);
    }
    return r;
}

static void choose_user(void)
{
    int i, j, sub = 0;
    unsigned long best = 0, worst = ~0UL;
    const char *s = getenv("TC100FIX_REC_STREAM");
    if (s && !strcmp(s, "sub")) sub = 1;
    rec_user = users[0].user;
    for (i = 0; i < 4; i++) {
        if (!users[i].user) continue;
        for (j = 0; j < 4; j++)
            if (encs[j].enc == users[i].enc && encs[j].w <= 4096 && encs[j].h <= 4096) {
                unsigned long a = encs[j].w * encs[j].h;
                if (!sub && a > best) { best = a; rec_user = users[i].user; }
                if (sub && a < worst) { worst = a; rec_user = users[i].user; }
            }
    }
    for (j = 0; j < 4; j++)
        if (users[j].user == rec_user)
            for (i = 0; i < 4; i++)
                if (encs[i].enc && encs[i].enc == users[j].enc)
                    fprintf(stderr, TAG "recording the %lux%lu encoder output\n", encs[i].w, encs[i].h);
}

int ak_venc_get_stream_ex(void *user, unsigned char *buf, unsigned int size, unsigned int *len)
{
    static int (*real)(void *, unsigned char *, unsigned int, unsigned int *);
    int r;
    if (!real) real = (int (*)(void *, unsigned char *, unsigned int, unsigned int *))dlsym(RTLD_NEXT, "ak_venc_get_stream_ex");
    if (!real) return -1;
    r = real(user, buf, size, len);
    if (r != 0 || rec_state < 0 || !buf || !len || !*len || *len > size)
        return r;
    if (rec_state == 0) {
        pthread_mutex_lock(&h_lock);
        if (rec_state == 0) {
            pthread_t th;
            pthread_attr_t at;
            rec_state = -1;
            if (rec_setup() == 0) {
                pthread_attr_init(&at);
                pthread_attr_setdetachstate(&at, PTHREAD_CREATE_DETACHED);
                pthread_attr_setstacksize(&at, 64 * 1024);
                if (pthread_create(&th, &at, writer, NULL) == 0) {
                    rec_state = 1;
                    fprintf(stderr, TAG "local recording to %s (%u s files, keep %u MB free)\n",
                            r_dir, r_segment_us_sec, r_reserve_mb);
                }
                pthread_attr_destroy(&at);
            }
        }
        pthread_mutex_unlock(&h_lock);
        if (rec_state < 0) return r;
    }
    if (!rec_user) {
        pthread_mutex_lock(&h_lock);
        if (!rec_user) choose_user();
        pthread_mutex_unlock(&h_lock);
    }
    if (user == rec_user)
        q_push(buf, *len, now_us());
    return r;
}

#else
/* ------------------------------------------------------------ host test */
/* TC100FIX_REC_DIR=dir rec-test <annexb file> <fps>: one access unit per AUD,
 * timestamps at <fps>; REC_TEST_DROP=n drops (as a full queue would) frame n. */
static volatile int t_done;
static uint64_t t_clock;
static int host_finished(void)
{
    int empty;
    pthread_mutex_lock(&q_lock); empty = q_head == q_tail; pthread_mutex_unlock(&q_lock);
    return t_done && empty;
}

int main(int argc, char **argv)
{
    FILE *f;
    unsigned char *all;
    long n, i, start = -1, frame = 0, drop_at = -1;
    int fps, codec = C_NONE;
    uint64_t ts = 5000000;
    pthread_t th;

    if (argc < 3 || rec_setup() != 0) { fprintf(stderr, "usage: TC100FIX_REC_DIR=dir rec-test file fps\n"); return 2; }
    fps = atoi(argv[2]);
    if (getenv("REC_TEST_DROP")) drop_at = atol(getenv("REC_TEST_DROP"));
    if (!(f = fopen(argv[1], "rb"))) return 2;
    fseek(f, 0, SEEK_END); n = ftell(f); fseek(f, 0, SEEK_SET);
    all = malloc((size_t)n + 4);
    if (!all || fread(all, 1, (size_t)n, f) != (size_t)n) return 2;
    fclose(f);
    if (pthread_create(&th, NULL, writer, NULL) != 0) return 2;
    for (i = 0; i <= n; i++) {
        int aud = 0;
        if (i + 4 < n && all[i] == 0 && all[i + 1] == 0 && all[i + 2] == 1) {
            unsigned char b = all[i + 3];
            if (codec == C_NONE) codec = (b == 0x40 || b == 0x46) ? C_H265 : C_H264;
            aud = codec == C_H265 ? ((b >> 1) & 0x3f) == 35 : (b & 0x1f) == 9;
        }
        if (aud || i == n) {
            long s = (aud && i > 0 && all[i - 1] == 0) ? i - 1 : i;
            if (start >= 0) {
                if (frame == drop_at) {
                    pthread_mutex_lock(&q_lock); q_gap = 1; q_dropped++; pthread_mutex_unlock(&q_lock);
                } else
                    while (q_push(all + start, (uint32_t)(s - start), ts) != 0) {
                        pthread_mutex_lock(&q_lock); q_dropped--; q_gap = 0; pthread_mutex_unlock(&q_lock);
                        usleep(1000);
                    }
                frame++;
                t_clock = ts;
                ts += 1000000ULL / (uint64_t)fps;
            }
            start = s;
        }
    }
    t_done = 1;
    pthread_join(th, NULL);
    printf("files=%llu bytes=%llu frames=%lu dropped=%lu\n", W.files, W.bytes, q_pushed, q_dropped);
    return 0;
}
#endif
