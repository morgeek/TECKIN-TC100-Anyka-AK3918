/*
 * rtsp.c — a small RTSP server inside libtc100fix ("RTSP lite"), next to the
 * vendor v4l2rtspserver: the H.264/H.265 frames the SoC encoder already
 * produces are taken where rec.c takes them (ak_venc_get_stream_ex) and sent
 * to RTSP clients as RTP over the RTSP TCP connection (interleaved, RFC 2326
 * section 10.12). No decoding, no re-encoding, no change to the vendor server.
 *
 * TC100FIX_RTSP_PORT=8554       enable, on this TCP port (unset = off)
 * TC100FIX_RTSP_CLIENTS=3       at most this many playing clients
 * TC100FIX_RTSP_STATUS=<path>   status (default /var/run/tc100rtsp), every 10 s
 *
 * URLs: rtsp://<camera>:<port>/video0 (main encoder) and /video1 (secondary),
 * also /video0_unicast and /video1_unicast like the vendor server.
 * Authentication: HTTP Digest (MD5) with TC100FIX_RTSP_USER/TC100FIX_RTSP_PASS
 * when both are set, otherwise the user and password given to the vendor
 * server ("-U user:pass", read from the command line when the library is
 * loaded, before tc100fix hides it). No credentials at all = no
 * authentication, as with the vendor server.
 *
 * Transport: TCP interleaved only (go2rtc, ffmpeg and Frigate use it by
 * default over Wi-Fi); a SETUP asking for UDP gets 461, clients then retry
 * with TCP. RTP payloads: RFC 7798 (H.265) and RFC 6184 (H.264), with
 * fragmentation units for NAL units over 1400 bytes; RTCP sender reports
 * every 5 s on the odd channel.
 *
 * The encoder thread never waits: a frame is copied into a 768 KB ring and the
 * server thread sends it. A client whose connection cannot take a frame
 * (its 256 KB output buffer would overflow) skips frames until the next
 * keyframe instead of falling behind.
 *
 * RTSP_HOST_TEST builds a host program serving an Annex-B file in a loop
 * (tests/test_regressions.py checks it with ffprobe).
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#define TAG "[tc100fix] rtsp: "
#define MAX_CLIENTS 4
#define INBUF 4096
#define OUTBUF (256 * 1024)
#define RING (768 * 1024)
#define RTP_MAX 1400
#define STREAMS 2
#define PS_MAX 256

enum { C_NONE, C_H264, C_H265 };

/* ------------------------------------------------------------------ MD5 */

struct md5 { uint32_t a, b, c, d; uint64_t n; unsigned char buf[64]; };
static const uint32_t md5_k[64] = {
    0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501,
    0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821,
    0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa, 0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
    0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed, 0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a,
    0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70,
    0x289b7ec6, 0xeaa127fa, 0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665,
    0xf4292244, 0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
    0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391 };
static const unsigned char md5_r[64] = { 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
    5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
    4, 11, 16, 23, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21 };

static void md5_block(struct md5 *m, const unsigned char *p)
{
    uint32_t w[16], a = m->a, b = m->b, c = m->c, d = m->d, f, t;
    int i, g;
    for (i = 0; i < 16; i++)
        w[i] = (uint32_t)p[i * 4] | (uint32_t)p[i * 4 + 1] << 8 | (uint32_t)p[i * 4 + 2] << 16 | (uint32_t)p[i * 4 + 3] << 24;
    for (i = 0; i < 64; i++) {
        if (i < 16) { f = (b & c) | (~b & d); g = i; }
        else if (i < 32) { f = (d & b) | (~d & c); g = (5 * i + 1) & 15; }
        else if (i < 48) { f = b ^ c ^ d; g = (3 * i + 5) & 15; }
        else { f = c ^ (b | ~d); g = (7 * i) & 15; }
        t = d; d = c; c = b;
        f = a + f + md5_k[i] + w[g];
        b = b + ((f << md5_r[i]) | (f >> (32 - md5_r[i])));
        a = t;
    }
    m->a += a; m->b += b; m->c += c; m->d += d;
}

static void md5_init(struct md5 *m) { m->a = 0x67452301; m->b = 0xefcdab89; m->c = 0x98badcfe; m->d = 0x10325476; m->n = 0; }

static void md5_add(struct md5 *m, const void *data, size_t len)
{
    const unsigned char *p = data;
    while (len--) {
        m->buf[m->n++ & 63] = *p++;
        if (!(m->n & 63)) md5_block(m, m->buf);
    }
}

/* lowercase hex digest of the concatenation a ":" b ":" c (c may be NULL) */
static void md5_hex3(char out[33], const char *a, const char *b, const char *c)
{
    struct md5 m;
    uint64_t bits;
    unsigned char pad = 0x80, z = 0, len[8], dig[16];
    int i;
    md5_init(&m);
    md5_add(&m, a, strlen(a)); md5_add(&m, ":", 1); md5_add(&m, b, strlen(b));
    if (c) { md5_add(&m, ":", 1); md5_add(&m, c, strlen(c)); }
    bits = m.n * 8;
    md5_add(&m, &pad, 1);
    while ((m.n & 63) != 56) md5_add(&m, &z, 1);
    for (i = 0; i < 8; i++) len[i] = (unsigned char)(bits >> (8 * i));
    md5_add(&m, len, 8);
    for (i = 0; i < 4; i++) {
        uint32_t v = i == 0 ? m.a : i == 1 ? m.b : i == 2 ? m.c : m.d;
        dig[i * 4] = (unsigned char)v; dig[i * 4 + 1] = (unsigned char)(v >> 8);
        dig[i * 4 + 2] = (unsigned char)(v >> 16); dig[i * 4 + 3] = (unsigned char)(v >> 24);
    }
    for (i = 0; i < 16; i++) sprintf(out + i * 2, "%02x", dig[i]);
}

/* ------------------------------------------------------------- helpers */

static void b64(char *out, size_t cap, const unsigned char *in, size_t n)
{
    static const char t[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    size_t i, o = 0;
    for (i = 0; i < n && o + 5 < cap; i += 3) {
        uint32_t v = (uint32_t)in[i] << 16 | (i + 1 < n ? (uint32_t)in[i + 1] << 8 : 0) | (i + 2 < n ? in[i + 2] : 0);
        out[o++] = t[(v >> 18) & 63]; out[o++] = t[(v >> 12) & 63];
        out[o++] = i + 1 < n ? t[(v >> 6) & 63] : '=';
        out[o++] = i + 2 < n ? t[v & 63] : '=';
    }
    out[o] = 0;
}

static uint64_t mono_us(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000ULL + (uint64_t)t.tv_nsec / 1000;
}

static uint32_t rnd32(void)
{
    static int fd = -2;
    uint32_t v = 0;
    if (fd == -2) fd = open("/dev/urandom", O_RDONLY);
    if (fd < 0 || read(fd, &v, sizeof(v)) != (ssize_t)sizeof(v))
        v = (uint32_t)mono_us() * 2654435761u ^ (uint32_t)getpid();
    return v;
}

/* Next NAL unit in an Annex-B buffer (start and length out), returns the offset after it or -1. */
static long next_nal(const unsigned char *b, long n, long pos, const unsigned char **nal, long *nlen)
{
    long i = pos, s;
    while (i + 3 <= n && !(b[i] == 0 && b[i + 1] == 0 && (b[i + 2] == 1 || (i + 4 <= n && b[i + 2] == 0 && b[i + 3] == 1)))) i++;
    if (i + 3 > n) return -1;
    i += b[i + 2] == 1 ? 3 : 4;
    s = i;
    while (i + 3 <= n && !(b[i] == 0 && b[i + 1] == 0 && (b[i + 2] == 1 || (i + 4 <= n && b[i + 2] == 0 && b[i + 3] == 1)))) i++;
    if (i + 3 > n) i = n;
    *nal = b + s; *nlen = i - s;
    while (*nlen > 0 && (*nal)[*nlen - 1] == 0) (*nlen)--;      /* trailing zero bytes */
    return i;
}

/* ------------------------------------------------------- stream state */

struct stream {
    int codec;
    unsigned char vps[PS_MAX], sps[PS_MAX], pps[PS_MAX];
    int vps_n, sps_n, pps_n;
    unsigned long frames;
};
static struct stream S[STREAMS];
static pthread_mutex_t s_lock = PTHREAD_MUTEX_INITIALIZER;

/* Look at a frame's NAL units: codec (first time), parameter sets, keyframe. */
static int scan_frame(int si, const unsigned char *b, long n)
{
    struct stream *s = &S[si];
    const unsigned char *nal;
    long len, pos = 0;
    int key = 0;
    while ((pos = next_nal(b, n, pos, &nal, &len)) >= 0) {
        int t;
        if (len < 2) continue;
        if (s->codec == C_NONE) {
            int t5 = (nal[0] >> 1) & 0x3f, t4 = nal[0] & 0x1f;
            if (t5 == 32 && !(nal[0] & 0x81)) s->codec = C_H265;
            else if (t4 == 7) s->codec = C_H264;
            else continue;
        }
        pthread_mutex_lock(&s_lock);
        if (s->codec == C_H265) {
            t = (nal[0] >> 1) & 0x3f;
            if (t == 32 && len <= PS_MAX) { memcpy(s->vps, nal, (size_t)len); s->vps_n = (int)len; }
            if (t == 33 && len <= PS_MAX) { memcpy(s->sps, nal, (size_t)len); s->sps_n = (int)len; }
            if (t == 34 && len <= PS_MAX) { memcpy(s->pps, nal, (size_t)len); s->pps_n = (int)len; }
            if (t >= 16 && t <= 21) key = 1;
        } else {
            t = nal[0] & 0x1f;
            if (t == 7 && len <= PS_MAX) { memcpy(s->sps, nal, (size_t)len); s->sps_n = (int)len; }
            if (t == 8 && len <= PS_MAX) { memcpy(s->pps, nal, (size_t)len); s->pps_n = (int)len; }
            if (t == 5) key = 1;
        }
        pthread_mutex_unlock(&s_lock);
    }
    return key;
}

/* ---------------------------------------------------------------- ring */
/* Frames from the encoder thread to the server thread. */

struct fhdr { uint32_t len; uint16_t stream, key; uint64_t ts; };
static unsigned char *ring;
static size_t r_head, r_tail;
static pthread_mutex_t r_lock = PTHREAD_MUTEX_INITIALIZER;
static int wake_fd[2] = { -1, -1 };
static volatile int any_playing[STREAMS];
static unsigned long r_dropped;

static void ring_push(int si, const unsigned char *d, uint32_t len, int key, uint64_t ts)
{
    size_t need = sizeof(struct fhdr) + ((len + 7u) & ~7u), freeb;
    struct fhdr h;
    pthread_mutex_lock(&r_lock);
    freeb = r_head >= r_tail ? RING - (r_head - r_tail) : r_tail - r_head;
    if (need + sizeof(struct fhdr) >= freeb) { r_dropped++; pthread_mutex_unlock(&r_lock); return; }
    if (RING - r_head < need) {                        /* wrap marker, start again at 0 */
        if (r_tail <= need || r_tail > r_head) { r_dropped++; pthread_mutex_unlock(&r_lock); return; }
        if (RING - r_head >= sizeof(h)) { h.len = 0xffffffffu; memcpy(ring + r_head, &h, sizeof(h)); }
        r_head = 0;
    }
    h.len = len; h.stream = (uint16_t)si; h.key = (uint16_t)key; h.ts = ts;
    memcpy(ring + r_head, &h, sizeof(h));
    memcpy(ring + r_head + sizeof(h), d, len);
    r_head += need;
    if (r_head == RING) r_head = 0;
    pthread_mutex_unlock(&r_lock);
    if (wake_fd[1] >= 0) { char c = 1; if (write(wake_fd[1], &c, 1)) {} }
}

/* Next frame, or 0. The data stays valid until ring_pop. */
static int ring_peek(struct fhdr *h, const unsigned char **d)
{
    int got = 0;
    pthread_mutex_lock(&r_lock);
    while (r_tail != r_head) {
        if (RING - r_tail < sizeof(*h)) { r_tail = 0; continue; }
        memcpy(h, ring + r_tail, sizeof(*h));
        if (h->len == 0xffffffffu) { r_tail = 0; continue; }
        *d = ring + r_tail + sizeof(*h); got = 1; break;
    }
    pthread_mutex_unlock(&r_lock);
    return got;
}

static void ring_pop(const struct fhdr *h)
{
    pthread_mutex_lock(&r_lock);
    r_tail += sizeof(*h) + ((h->len + 7u) & ~7u);
    if (r_tail >= RING) r_tail = 0;
    pthread_mutex_unlock(&r_lock);
}

/* ------------------------------------------------------------- clients */

struct client {
    int fd;
    char in[INBUF]; int in_n;
    unsigned char *out; size_t out_head, out_tail;
    int stream, playing, wait_key, ch;               /* ch: RTP interleaved channel */
    uint16_t seq; uint32_t ssrc, rtp_ts;
    uint64_t sr_last, sent_octets, sent_pkts, opened;
    char session[17];
    unsigned long drops;
    uint32_t addr;
};
static struct client C[MAX_CLIENTS];
static int max_clients = 3;
static int lport;
static char cred_user[64], cred_pass[64];
static char nonce[33];
static const char *status_path = "/var/run/tc100rtsp";
static unsigned long long total_bytes;

static void client_close(struct client *c)
{
    if (c->fd >= 0) close(c->fd);
    free(c->out);
    memset(c, 0, sizeof(*c));
    c->fd = -1;
}

static size_t out_free(const struct client *c) { return OUTBUF - (c->out_tail - c->out_head); }

static int out_put(struct client *c, const void *d, size_t n)
{
    if (!c->out && !(c->out = malloc(OUTBUF))) return -1;
    if (c->out_head && OUTBUF - c->out_tail < n) {
        memmove(c->out, c->out + c->out_head, c->out_tail - c->out_head);
        c->out_tail -= c->out_head; c->out_head = 0;
    }
    if (OUTBUF - c->out_tail < n) return -1;
    memcpy(c->out + c->out_tail, d, n);
    c->out_tail += n;
    return 0;
}

static void out_flush(struct client *c)
{
    while (c->out && c->out_tail > c->out_head) {
        ssize_t w = send(c->fd, c->out + c->out_head, c->out_tail - c->out_head, MSG_DONTWAIT | MSG_NOSIGNAL);
        if (w <= 0) {
            if (w < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) return;
            client_close(c); return;
        }
        c->out_head += (size_t)w;
        total_bytes += (unsigned long long)w;
    }
    if (c->out && c->out_head == c->out_tail) c->out_head = c->out_tail = 0;
}

static void reply(struct client *c, int code, const char *reason, int cseq, const char *extra, const char *body)
{
    char h[1024];
    int n;
    if (body)
        n = snprintf(h, sizeof(h), "RTSP/1.0 %d %s\r\nCSeq: %d\r\nServer: tc100-rtsp-lite\r\n%sContent-Length: %d\r\n\r\n",
                     code, reason, cseq, extra ? extra : "", (int)strlen(body));
    else
        n = snprintf(h, sizeof(h), "RTSP/1.0 %d %s\r\nCSeq: %d\r\nServer: tc100-rtsp-lite\r\n%s\r\n",
                     code, reason, cseq, extra ? extra : "");
    if (n < 0 || n >= (int)sizeof(h)) return;
    if (out_put(c, h, (size_t)n) == 0 && body) out_put(c, body, strlen(body));
}

/* ------------------------------------------------------------- RTP out */

static void rtp_hdr(unsigned char *p, struct client *c, int marker)
{
    p[0] = 0x80; p[1] = (unsigned char)(96 | (marker ? 0x80 : 0));
    p[2] = (unsigned char)(c->seq >> 8); p[3] = (unsigned char)c->seq; c->seq++;
    p[4] = (unsigned char)(c->rtp_ts >> 24); p[5] = (unsigned char)(c->rtp_ts >> 16);
    p[6] = (unsigned char)(c->rtp_ts >> 8); p[7] = (unsigned char)c->rtp_ts;
    p[8] = (unsigned char)(c->ssrc >> 24); p[9] = (unsigned char)(c->ssrc >> 16);
    p[10] = (unsigned char)(c->ssrc >> 8); p[11] = (unsigned char)c->ssrc;
}

/* One RTP packet = "$" ch len16 | RTP header | payload header(s) | data. */
static int put_packet(struct client *c, const unsigned char *ph, int phn, const unsigned char *d, long n, int marker)
{
    unsigned char f[4 + 12 + 3];
    long plen = 12 + phn + n;
    f[0] = '$'; f[1] = (unsigned char)c->ch; f[2] = (unsigned char)(plen >> 8); f[3] = (unsigned char)plen;
    rtp_hdr(f + 4, c, marker);
    memcpy(f + 16, ph, (size_t)phn);
    if (out_put(c, f, (size_t)(16 + phn)) || out_put(c, d, (size_t)n)) return -1;
    c->sent_pkts++; c->sent_octets += (uint64_t)(phn + n);
    return 0;
}

static int send_nal(struct client *c, int codec, const unsigned char *nal, long len, int last)
{
    int hn = codec == C_H265 ? 2 : 1;
    if (len <= RTP_MAX) return put_packet(c, nal, 0, nal, len, last);
    {
        unsigned char ph[3];
        const unsigned char *p = nal + hn;
        long left = len - hn;
        int first = 1;
        while (left > 0) {
            long chunk = left > RTP_MAX ? RTP_MAX : left;
            int end = chunk == left;
            if (codec == C_H265) {
                int type = (nal[0] >> 1) & 0x3f;
                ph[0] = (unsigned char)((nal[0] & 0x81) | (49 << 1)); ph[1] = nal[1];
                ph[2] = (unsigned char)((first ? 0x80 : 0) | (end ? 0x40 : 0) | type);
            } else {
                ph[0] = (unsigned char)((nal[0] & 0xe0) | 28);
                ph[1] = (unsigned char)((first ? 0x80 : 0) | (end ? 0x40 : 0) | (nal[0] & 0x1f));
            }
            if (put_packet(c, ph, hn + 1, p, chunk, last && end)) return -1;
            p += chunk; left -= chunk; first = 0;
        }
    }
    return 0;
}

static void send_frame(struct client *c, const struct fhdr *h, const unsigned char *d)
{
    const unsigned char *nal = NULL, *nn = NULL;
    long len = 0, nlen = 0, pos, npos;
    int codec = S[h->stream].codec;
    size_t need = h->len + (h->len / RTP_MAX + 8) * 20 + 64;
    if (c->wait_key && !h->key) return;
    if (out_free(c) < need) { c->wait_key = 1; c->drops++; return; }
    c->wait_key = 0;
    c->rtp_ts = (uint32_t)(h->ts * 9 / 100);         /* microseconds -> 90 kHz */
    pos = next_nal(d, h->len, 0, &nal, &len);
    while (pos >= 0) {
        npos = next_nal(d, h->len, pos, &nn, &nlen);
        if (len > 0) {
            int t = codec == C_H265 ? (nal[0] >> 1) & 0x3f : nal[0] & 0x1f;
            int aud = codec == C_H265 ? t == 35 : t == 9;
            if (!aud && send_nal(c, codec, nal, len, npos < 0)) { c->wait_key = 1; c->drops++; return; }
        }
        pos = npos; nal = nn; len = nlen;
    }
    /* RTCP sender report every 5 s (NTP from the wall clock, same RTP clock). */
    if (h->ts - c->sr_last >= 5000000ULL) {
        unsigned char sr[4 + 28];
        struct timeval tv;
        uint32_t ntp_s, ntp_f;
        c->sr_last = h->ts;
        gettimeofday(&tv, NULL);
        ntp_s = (uint32_t)tv.tv_sec + 2208988800u;
        ntp_f = (uint32_t)(((uint64_t)tv.tv_usec << 32) / 1000000ULL);
        sr[0] = '$'; sr[1] = (unsigned char)(c->ch + 1); sr[2] = 0; sr[3] = 28;
        sr[4] = 0x80; sr[5] = 200; sr[6] = 0; sr[7] = 6;
#define PUT32(o, v) do { sr[o] = (unsigned char)((v) >> 24); sr[o + 1] = (unsigned char)((v) >> 16); \
                         sr[o + 2] = (unsigned char)((v) >> 8); sr[o + 3] = (unsigned char)(v); } while (0)
        PUT32(8, c->ssrc); PUT32(12, ntp_s); PUT32(16, ntp_f); PUT32(20, c->rtp_ts);
        PUT32(24, (uint32_t)c->sent_pkts); PUT32(28, (uint32_t)c->sent_octets);
#undef PUT32
        out_put(c, sr, sizeof(sr));
    }
}

/* -------------------------------------------------------------- RTSP */

static int hdr_get(const char *req, const char *name, char *out, size_t cap)
{
    const char *p = req;
    size_t nl = strlen(name);
    while ((p = strchr(p, '\n'))) {
        p++;
        if (!strncasecmp(p, name, nl) && p[nl] == ':') {
            const char *v = p + nl + 1, *e;
            size_t n;
            while (*v == ' ') v++;
            e = strpbrk(v, "\r\n");
            n = e ? (size_t)(e - v) : strlen(v);
            if (n >= cap) n = cap - 1;
            memcpy(out, v, n); out[n] = 0;
            return 1;
        }
    }
    return 0;
}

static int param_get(const char *h, const char *key, char *out, size_t cap)
{
    const char *p = h;
    size_t kl = strlen(key);
    while ((p = strstr(p, key))) {
        if ((p == h || p[-1] == ' ' || p[-1] == ',') && p[kl] == '=') {
            const char *v = p + kl + 1, *e;
            size_t n;
            if (*v == '"') { v++; e = strchr(v, '"'); } else e = strpbrk(v, ", ");
            n = e ? (size_t)(e - v) : strlen(v);
            if (n >= cap) n = cap - 1;
            memcpy(out, v, n); out[n] = 0;
            return 1;
        }
        p += kl;
    }
    return 0;
}

static int authorized(const char *req, const char *method)
{
    char a[512], user[64], uri[256], resp[40], rnonce[40], ha1[33], ha2[33], want[33];
    if (!cred_user[0]) return 1;
    if (!hdr_get(req, "Authorization", a, sizeof(a)) || strncasecmp(a, "Digest ", 7)) return 0;
    if (!param_get(a, "username", user, sizeof(user)) || !param_get(a, "uri", uri, sizeof(uri)) ||
        !param_get(a, "response", resp, sizeof(resp)) || !param_get(a, "nonce", rnonce, sizeof(rnonce)))
        return 0;
    if (strcmp(user, cred_user) || strcmp(rnonce, nonce)) return 0;
    md5_hex3(ha1, cred_user, "TC100", cred_pass);
    md5_hex3(ha2, method, uri, NULL);
    md5_hex3(want, ha1, nonce, ha2);
    return !strcasecmp(want, resp);
}

/* "/video0", "/video0_unicast", "/video1"... at the end of the URL path -> stream or -1 */
static int url_stream(const char *url)
{
    const char *p = strstr(url, "://");
    p = p ? strchr(p + 3, '/') : url;
    if (!p) return -1;
    if (!strncmp(p, "/video0", 7) && (!p[7] || p[7] == '/' || !strncmp(p + 7, "_unicast", 8))) return 0;
    if (!strncmp(p, "/video1", 7) && (!p[7] || p[7] == '/' || !strncmp(p + 7, "_unicast", 8))) return 1;
    return -1;
}

static void sdp(char *out, size_t cap, int si, const char *myip)
{
    struct stream *s = &S[si];
    char a[400], b[400], c[400], fmtp[1300];
    pthread_mutex_lock(&s_lock);
    fmtp[0] = 0;
    if (s->codec == C_H265) {
        b64(a, sizeof(a), s->vps, (size_t)s->vps_n); b64(b, sizeof(b), s->sps, (size_t)s->sps_n); b64(c, sizeof(c), s->pps, (size_t)s->pps_n);
        if (s->vps_n && s->sps_n && s->pps_n)
            snprintf(fmtp, sizeof(fmtp), "a=fmtp:96 sprop-vps=%s;sprop-sps=%s;sprop-pps=%s\r\n", a, b, c);
    } else {
        b64(b, sizeof(b), s->sps, (size_t)s->sps_n); b64(c, sizeof(c), s->pps, (size_t)s->pps_n);
        if (s->sps_n >= 4 && s->pps_n)
            snprintf(fmtp, sizeof(fmtp), "a=fmtp:96 packetization-mode=1;profile-level-id=%02X%02X%02X;sprop-parameter-sets=%s,%s\r\n",
                     s->sps[1], s->sps[2], s->sps[3], b, c);
        else
            snprintf(fmtp, sizeof(fmtp), "a=fmtp:96 packetization-mode=1\r\n");
    }
    snprintf(out, cap, "v=0\r\no=- %u 1 IN IP4 %s\r\ns=TC100\r\nc=IN IP4 0.0.0.0\r\nt=0 0\r\na=control:*\r\n"
             "m=video 0 RTP/AVP 96\r\na=rtpmap:96 %s/90000\r\n%sa=control:trackID=0\r\n",
             (unsigned)rnd32(), myip, s->codec == C_H265 ? "H265" : "H264", fmtp);
    pthread_mutex_unlock(&s_lock);
}

static void handle_request(struct client *c, char *req)
{
    char method[16], url[300], v[64], extra[600], cs[16], body[2048], myip[48];
    int cseq = 0;
    struct sockaddr_in me;
    socklen_t ml = sizeof(me);

    if (sscanf(req, "%15s %299s", method, url) != 2) { client_close(c); return; }
    if (hdr_get(req, "CSeq", cs, sizeof(cs))) cseq = atoi(cs);
    strcpy(myip, "0.0.0.0");
    if (getsockname(c->fd, (struct sockaddr *)&me, &ml) == 0) inet_ntop(AF_INET, &me.sin_addr, myip, sizeof(myip));

    if (!strcmp(method, "OPTIONS")) {
        reply(c, 200, "OK", cseq, "Public: OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN, GET_PARAMETER, SET_PARAMETER\r\n", NULL);
        return;
    }
    if (strcmp(method, "TEARDOWN") && strcmp(method, "GET_PARAMETER") && strcmp(method, "SET_PARAMETER") &&
        !authorized(req, method)) {
        snprintf(extra, sizeof(extra), "WWW-Authenticate: Digest realm=\"TC100\", nonce=\"%s\"\r\n", nonce);
        reply(c, 401, "Unauthorized", cseq, extra, NULL);
        return;
    }
    if (!strcmp(method, "DESCRIBE")) {
        int si = url_stream(url), i;
        if (si < 0) { reply(c, 404, "Not Found", cseq, NULL, NULL); return; }
        for (i = 0; i < 30 && S[si].codec == C_NONE; i++) usleep(100000);   /* first frames after start */
        if (S[si].codec == C_NONE) { reply(c, 503, "Service Unavailable", cseq, NULL, NULL); return; }
        c->stream = si;
        sdp(body, sizeof(body), si, myip);
        snprintf(extra, sizeof(extra), "Content-Base: %s/\r\nContent-Type: application/sdp\r\n", url);
        reply(c, 200, "OK", cseq, extra, body);
        return;
    }
    if (!strcmp(method, "SETUP")) {
        char tr[256];
        int a = 0, b = 1, si = url_stream(url);
        if (si >= 0) c->stream = si;
        if (!hdr_get(req, "Transport", tr, sizeof(tr)) || !strstr(tr, "TCP")) {
            reply(c, 461, "Unsupported Transport", cseq, NULL, NULL); return;
        }
        if (strstr(tr, "interleaved=")) sscanf(strstr(tr, "interleaved=") + 12, "%d-%d", &a, &b);
        if (a < 0 || a > 250) a = 0;
        c->ch = a;
        c->ssrc = rnd32();
        c->seq = (uint16_t)rnd32();
        snprintf(c->session, sizeof(c->session), "%08X%08X", rnd32(), rnd32());
        snprintf(extra, sizeof(extra), "Transport: RTP/AVP/TCP;unicast;interleaved=%d-%d;ssrc=%08X\r\nSession: %s;timeout=60\r\n",
                 a, a + 1, (unsigned)c->ssrc, c->session);
        reply(c, 200, "OK", cseq, extra, NULL);
        return;
    }
    if (!strcmp(method, "PLAY")) {
        int i, n = 0;
        if (!c->session[0]) { reply(c, 455, "Method Not Valid In This State", cseq, NULL, NULL); return; }
        for (i = 0; i < MAX_CLIENTS; i++) if (C[i].fd >= 0 && C[i].playing) n++;
        if (!c->playing && n >= max_clients) { reply(c, 453, "Not Enough Bandwidth", cseq, NULL, NULL); return; }
        c->playing = 1; c->wait_key = 1;
        any_playing[c->stream] = 1;
        snprintf(extra, sizeof(extra), "Session: %s\r\nRange: npt=0.000-\r\n", c->session);
        reply(c, 200, "OK", cseq, extra, NULL);
        fprintf(stderr, TAG "client %u.%u.%u.%u plays video%d\n", c->addr & 255, (c->addr >> 8) & 255,
                (c->addr >> 16) & 255, c->addr >> 24, c->stream);
        return;
    }
    if (!strcmp(method, "TEARDOWN")) {
        reply(c, 200, "OK", cseq, NULL, NULL);
        out_flush(c);
        client_close(c);
        return;
    }
    if (!strcmp(method, "GET_PARAMETER") || !strcmp(method, "SET_PARAMETER")) {
        snprintf(v, sizeof(v), "Session: %s\r\n", c->session);
        reply(c, 200, "OK", cseq, c->session[0] ? v : NULL, NULL);
        return;
    }
    reply(c, 501, "Not Implemented", cseq, NULL, NULL);
}

/* Requests and (ignored) interleaved RTCP from a client. */
static void client_read(struct client *c)
{
    ssize_t r = recv(c->fd, c->in + c->in_n, (size_t)(INBUF - 1 - c->in_n), MSG_DONTWAIT);
    if (r <= 0) {
        if (r < 0 && (errno == EAGAIN || errno == EINTR)) return;
        client_close(c); return;
    }
    c->in_n += (int)r;
    for (;;) {
        char *end, cl[16];
        int used, body = 0;
        if (c->in_n <= 0) break;
        if (c->in[0] == '$') {                          /* interleaved packet from the client */
            int n;
            if (c->in_n < 4) break;
            n = 4 + ((unsigned char)c->in[2] << 8 | (unsigned char)c->in[3]);
            if (n > INBUF - 1) { client_close(c); return; }
            if (c->in_n < n) break;
            memmove(c->in, c->in + n, (size_t)(c->in_n - n)); c->in_n -= n;
            continue;
        }
        c->in[c->in_n] = 0;
        end = strstr(c->in, "\r\n\r\n");
        if (!end) { if (c->in_n >= INBUF - 1) client_close(c); break; }
        *end = 0;
        if (hdr_get(c->in, "Content-Length", cl, sizeof(cl))) body = atoi(cl);
        used = (int)(end - c->in) + 4 + (body > 0 ? body : 0);
        if (used > c->in_n) { *end = '\r'; break; }
        handle_request(c, c->in);
        if (c->fd < 0) return;
        memmove(c->in, c->in + used, (size_t)(c->in_n - used)); c->in_n -= used;
    }
}

static void write_status(void)
{
    char tmp[200];
    FILE *f;
    int i, n = 0;
    snprintf(tmp, sizeof(tmp), "%s.tmp", status_path);
    if (!(f = fopen(tmp, "w"))) return;
    for (i = 0; i < MAX_CLIENTS; i++) if (C[i].fd >= 0 && C[i].playing) n++;
    fprintf(f, "port=%d\nclients=%d\nbytes=%llu\nring_dropped=%lu\n", lport, n, total_bytes, r_dropped);
    for (i = 0; i < STREAMS; i++)
        fprintf(f, "video%d=%s frames=%lu\n", i, S[i].codec == C_H265 ? "h265" : S[i].codec == C_H264 ? "h264" : "none", S[i].frames);
    for (i = 0; i < MAX_CLIENTS; i++)
        if (C[i].fd >= 0 && C[i].playing)
            fprintf(f, "client=%u.%u.%u.%u video%d drops=%lu\n", C[i].addr & 255, (C[i].addr >> 8) & 255,
                    (C[i].addr >> 16) & 255, C[i].addr >> 24, C[i].stream, C[i].drops);
    fclose(f);
    rename(tmp, status_path);
}

static void *server(void *arg)
{
    int ls = (int)(intptr_t)arg, i;
    uint64_t last_status = 0;
    for (i = 0; i < MAX_CLIENTS; i++) C[i].fd = -1;
    for (;;) {
        fd_set rf, wf;
        struct timeval tv = { 1, 0 };
        int mx = ls > wake_fd[0] ? ls : wake_fd[0], playing[STREAMS] = { 0, 0 };
        struct fhdr h;
        const unsigned char *d = NULL;
        uint64_t now;

        FD_ZERO(&rf); FD_ZERO(&wf);
        FD_SET(ls, &rf); FD_SET(wake_fd[0], &rf);
        for (i = 0; i < MAX_CLIENTS; i++) {
            if (C[i].fd < 0) continue;
            FD_SET(C[i].fd, &rf);
            if (C[i].out && C[i].out_tail > C[i].out_head) FD_SET(C[i].fd, &wf);
            if (C[i].fd > mx) mx = C[i].fd;
            if (C[i].playing) playing[C[i].stream] = 1;
        }
        any_playing[0] = playing[0]; any_playing[1] = playing[1];
        if (select(mx + 1, &rf, &wf, NULL, &tv) < 0) { if (errno != EINTR) usleep(100000); continue; }
        if (FD_ISSET(wake_fd[0], &rf)) { char b[64]; if (read(wake_fd[0], b, sizeof(b))) {} }
        if (FD_ISSET(ls, &rf)) {
            struct sockaddr_in a;
            socklen_t al = sizeof(a);
            int fd = accept(ls, (struct sockaddr *)&a, &al);
            if (fd >= 0) {
                for (i = 0; i < MAX_CLIENTS && C[i].fd >= 0; i++) ;
                if (i == MAX_CLIENTS) close(fd);
                else {
                    int one = 1, sb = 128 * 1024;
                    memset(&C[i], 0, sizeof(C[i]));
                    C[i].fd = fd; C[i].addr = a.sin_addr.s_addr; C[i].opened = mono_us();
                    fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK);
                    fcntl(fd, F_SETFD, FD_CLOEXEC);
                    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
                    setsockopt(fd, SOL_SOCKET, SO_SNDBUF, &sb, sizeof(sb));
                    setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, &one, sizeof(one));
                }
            }
        }
        for (i = 0; i < MAX_CLIENTS; i++) {
            if (C[i].fd >= 0 && FD_ISSET(C[i].fd, &rf)) client_read(&C[i]);
            /* never got to PLAY within 30 s: drop the connection */
            if (C[i].fd >= 0 && !C[i].playing && mono_us() - C[i].opened > 30000000ULL) client_close(&C[i]);
        }
        while (ring_peek(&h, &d)) {
            if (h.stream < STREAMS)
                for (i = 0; i < MAX_CLIENTS; i++)
                    if (C[i].fd >= 0 && C[i].playing && C[i].stream == h.stream) send_frame(&C[i], &h, d);
            ring_pop(&h);
        }
        for (i = 0; i < MAX_CLIENTS; i++) if (C[i].fd >= 0) out_flush(&C[i]);
        now = mono_us();
        if (now - last_status >= 10000000ULL) { last_status = now; write_status(); }
    }
    return NULL;
}

static int rtsp_state;     /* 0 not started, 1 running, -1 off */

/* Credentials from "-U user:pass" on the command line, read when the
 * library is loaded (tc100fix hides them from the process list later). */
#ifndef RTSP_HOST_TEST
static void read_cred(void)
{
    char buf[2048], *p, *end;
    int fd = open("/proc/self/cmdline", O_RDONLY);
    ssize_t n;
    if (fd < 0) return;
    n = read(fd, buf, sizeof(buf) - 1);
    close(fd);
    if (n <= 0) return;
    buf[n] = 0; end = buf + n;
    for (p = buf; p < end; p += strlen(p) + 1) {
        const char *v = NULL;
        if (!strcmp(p, "-U") && p + strlen(p) + 1 < end) v = p + strlen(p) + 1;
        else if (!strncmp(p, "-U", 2) && p[2]) v = p + 2;
        if (v) {
            const char *colon = strchr(v, ':');
            if (colon && (size_t)(colon - v) < sizeof(cred_user) && strlen(colon + 1) < sizeof(cred_pass)) {
                memcpy(cred_user, v, (size_t)(colon - v)); cred_user[colon - v] = 0;
                strcpy(cred_pass, colon + 1);
            }
            break;
        }
    }
}

__attribute__((constructor)) static void rtsp_ctor(void)
{
    const char *u = getenv("TC100FIX_RTSP_USER"), *p = getenv("TC100FIX_RTSP_PASS");
    if (!getenv("TC100FIX_RTSP_PORT")) return;
    /* Its own account (RTSP_LITE_USER/RTSP_LITE_PASS), else the main server's. */
    if (u && p && u[0] && p[0] && strlen(u) < sizeof(cred_user) && strlen(p) < sizeof(cred_pass)) {
        strcpy(cred_user, u); strcpy(cred_pass, p);
    } else
        read_cred();
}
#endif

static int rtsp_start(void)
{
    const char *v = getenv("TC100FIX_RTSP_PORT");
    struct sockaddr_in a;
    int ls, one = 1;
    pthread_t th;
    pthread_attr_t at;

    if (!v || atoi(v) <= 0 || atoi(v) > 65535) return -1;
    lport = atoi(v);
    if ((v = getenv("TC100FIX_RTSP_CLIENTS")) && atoi(v) >= 1 && atoi(v) <= MAX_CLIENTS) max_clients = atoi(v);
    if ((v = getenv("TC100FIX_RTSP_STATUS")) && v[0]) status_path = v;
    snprintf(nonce, sizeof(nonce), "%08x%08x%08x%08x", rnd32(), rnd32(), rnd32(), rnd32());
    if (!(ring = malloc(RING))) return -1;
    if (pipe(wake_fd)) return -1;
    fcntl(wake_fd[0], F_SETFL, O_NONBLOCK); fcntl(wake_fd[1], F_SETFL, O_NONBLOCK);
    fcntl(wake_fd[0], F_SETFD, FD_CLOEXEC); fcntl(wake_fd[1], F_SETFD, FD_CLOEXEC);
    signal(SIGPIPE, SIG_IGN);
    if ((ls = socket(AF_INET, SOCK_STREAM, 0)) < 0) return -1;
    setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    fcntl(ls, F_SETFD, FD_CLOEXEC);
    memset(&a, 0, sizeof(a));
    a.sin_family = AF_INET; a.sin_port = htons((uint16_t)lport); a.sin_addr.s_addr = htonl(INADDR_ANY);
    if (bind(ls, (struct sockaddr *)&a, sizeof(a)) || listen(ls, 4)) {
        fprintf(stderr, TAG "port %d: %s\n", lport, strerror(errno));
        close(ls); return -1;
    }
    pthread_attr_init(&at);
    pthread_attr_setdetachstate(&at, PTHREAD_CREATE_DETACHED);
    pthread_attr_setstacksize(&at, 64 * 1024);
    if (pthread_create(&th, &at, server, (void *)(intptr_t)ls)) { close(ls); pthread_attr_destroy(&at); return -1; }
    pthread_attr_destroy(&at);
    fprintf(stderr, TAG "serving on port %d (%s)\n", lport, cred_user[0] ? "digest authentication" : "no authentication");
    return 0;
}

/* From the encoder hook (rec.c): one access unit of stream 0 (main) or 1 (sub). */
void tc100fix_rtsp_frame(int si, const unsigned char *d, unsigned int len)
{
    int key;
    if (rtsp_state < 0 || si < 0 || si >= STREAMS || !d || !len) return;
    if (rtsp_state == 0) {
        static pthread_mutex_t once = PTHREAD_MUTEX_INITIALIZER;
        pthread_mutex_lock(&once);
        if (rtsp_state == 0) rtsp_state = rtsp_start() == 0 ? 1 : -1;
        pthread_mutex_unlock(&once);
        if (rtsp_state < 0) return;
    }
    key = scan_frame(si, d, (long)len);
    S[si].frames++;
    if (any_playing[si]) ring_push(si, d, len, key, mono_us());
}

#ifdef RTSP_HOST_TEST
/* TC100FIX_RTSP_PORT=n [RTSP_TEST_CRED=user:pass] rtsp-test <annexb> <fps> [<seconds>]:
 * serves the file as video0 in a loop. */
int main(int argc, char **argv)
{
    FILE *f;
    unsigned char *all;
    long n, i, start = -1;
    int fps, codec = C_NONE;
    double secs;
    uint64_t t0;
    const char *cr = getenv("RTSP_TEST_CRED");
    if (argc < 3) return 2;
    if (cr && strchr(cr, ':')) {
        snprintf(cred_user, sizeof(cred_user), "%.*s", (int)(strchr(cr, ':') - cr), cr);
        snprintf(cred_pass, sizeof(cred_pass), "%s", strchr(cr, ':') + 1);
    }
    fps = atoi(argv[2]); secs = argc > 3 ? atof(argv[3]) : 20;
    if (!(f = fopen(argv[1], "rb"))) return 2;
    fseek(f, 0, SEEK_END); n = ftell(f); fseek(f, 0, SEEK_SET);
    all = malloc((size_t)n + 4);
    if (!all || fread(all, 1, (size_t)n, f) != (size_t)n) return 2;
    fclose(f);
    t0 = mono_us();
    while (mono_us() - t0 < (uint64_t)(secs * 1e6)) {
        for (i = 0, start = -1; i <= n; i++) {
            int aud = 0;
            if (i + 4 < n && all[i] == 0 && all[i + 1] == 0 && all[i + 2] == 1) {
                unsigned char b = all[i + 3];
                if (codec == C_NONE) codec = (b == 0x40 || b == 0x46) ? C_H265 : C_H264;
                aud = codec == C_H265 ? ((b >> 1) & 0x3f) == 35 : (b & 0x1f) == 9;
            }
            if (aud || i == n) {
                long s = (aud && i > 0 && all[i - 1] == 0) ? i - 1 : i;
                if (start >= 0) {
                    tc100fix_rtsp_frame(0, all + start, (unsigned)(s - start));
                    usleep(1000000 / fps);
                }
                start = s;
            }
        }
    }
    write_status();
    printf("bytes=%llu ring_dropped=%lu frames=%lu\n", total_bytes, r_dropped, S[0].frames);
    return 0;
}
#endif
