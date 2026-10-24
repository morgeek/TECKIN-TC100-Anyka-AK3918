/* tc100_rtsp: RTSP/H.264 or H.265 server for the TECKIN TC100 on Linux 6.6.
 *
 * Capture (V4L2, 1080p NV12) -> vendor H.264 encoder control library on the free libakuio + ak39_venc driver
 * (see src/venctest) -> RTP (RFC 6184, packetization-mode 1, FU-A) over RTSP: TCP interleaved or UDP unicast.
 * One process, one thread: a select() loop serves the V4L2 device, the listening socket and the clients.
 * The GOP being encoded is cached so that a new client starts immediately on the last IDR frame.
 *
 * usage: tc100_rtsp [-c h264|h265] [-p PORT] [-b KBPS] [-f FPS] [-q QMIN] [-Q QMAX] [-d VIDEODEV] [-L LIBDIR] [-A libakuio.so]
 *            [-u USER] [-w PASSWORD_FILE]   (Digest or Basic when the file holds a password)
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "../libakuio/ak39_venc.h"
#include "jpeg_hw.h"

#define W 1920
#define H 1080
#define SW 640		/* sub-stream, stored in the V4L2 buffer after the main picture */
#define SH 360
#define MAXCLI 4
#define RTP_PAYLOAD 1400
#define CACHE_MAX (1536 * 1024)
#define CACHE_FRAMES 128
#define QMAX (768 * 1024)	/* per-client output queue limit */

struct venc_param {
	unsigned int width, height, qpmin, qpmax, fps, gop, kbps, profile, size_class, group, rc_vbr, codec;
};
struct video_stream {
	unsigned char *data;
	unsigned int len;
	unsigned int w2[3];
	unsigned int frame_type;
	unsigned int rest[10];
};

#define LOG(...) do { char _b[300]; int _n = snprintf(_b, sizeof _b, __VA_ARGS__); if (_n > 0) (void)!write(2, _b, _n); } while (0)

static void *(*p_open)(const struct venc_param *);
static int (*p_send)(void *, unsigned char *, unsigned int, struct video_stream *);
static int (*p_release)(void *, struct video_stream *);
static int (*p_close)(void *);
static unsigned long (*p_alloc)(int);
static int (*p_pinit)(void);
static volatile int run = 1;

static void on_sig(int s) { (void)s; run = 0; }

/* ---- web UI pictures from the hardware JPEG engine (same files as tc100_streamer) ---- */
#define JSTREAM 0x7e900
static int (*p_v2p)(unsigned long);
static void (*p_wait)(unsigned long);
static uint8_t *jbuf;
static uint32_t jpaddr;
static int jpeg_ok, jpeg_inited;

static int jpeg_init(void)
{
	const char *dv = getenv("AKUIO_DEV") ? getenv("AKUIO_DEV") : "/dev/uio0";
	struct ak39_venc_pool_info info;
	int fd = open(dv, O_RDWR | O_SYNC);

	if (fd < 0 || ioctl(fd, AK39_VENC_POOL_INFO, &info) < 0) return -1;
	regs = mmap(NULL, info.regs_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, AK39_VENC_MMAP_REGS);
	if (regs == MAP_FAILED) { regs = NULL; return -1; }
	p_v2p = dlsym(RTLD_DEFAULT, "akuio_vaddr2paddr");
	p_wait = dlsym(RTLD_DEFAULT, "akuio_wait_irq");
	jbuf = (uint8_t *)p_alloc(JSTREAM + AUX_SIZE);
	if (!p_v2p || !p_wait || !jbuf) return -1;
	jpaddr = (uint32_t)p_v2p((unsigned long)jbuf);
	return jpaddr ? 0 : -1;
}

/* encode one NV12 picture (physical addresses) -> jbuf + TABLES_SIZE, returns the length or 0 */
static uint32_t jpeg_run(uint32_t y, uint32_t uv, int w, int h, int q)
{
	uint32_t c[11], st[3];

	build_tables(jbuf + JSTREAM, q);
	ctrl_words(c, w, h, y, uv, jpaddr + JSTREAM, jpaddr, JSTREAM);
	{ FILE *df = w < 1000 ? fopen("/tmp/c2", "r") : NULL; unsigned v;	/* debug: control word 2 override */
	  if (df) { if (fscanf(df, "%x", &v) == 1) c[2] = v; fclose(df); } }
	if (!jpeg_inited) { hw_init(); jpeg_inited = 1; }
	hw_encode(c);
	p_wait(0);
	st[0] = RD(R_JPEG_STATUS); st[1] = RD(R_JPEG_STATUS + 4); st[2] = RD(R_JPEG_STATUS + 8);
	(void)RD(R_STAT); (void)RD(R_ACK); WR(R_ACK, 0x10001);
	WR(R_IRQ_EN, 0x1000007); WR(0x822c, 0);
	WR(R_CLK, (RD(R_CLK) & 0xffff7fff) | 0xe00);
	if (getenv("RTSP_DEBUG")) LOG("JPEG %dx%d status %08x %08x %08x\n", w, h, st[0], st[1], st[2]);
	if (st[1] < 4 || st[1] > JSTREAM - TABLES_SIZE || jbuf[TABLES_SIZE] != 0xff || jbuf[TABLES_SIZE + 1] != 0xd8) return 0;
	return st[1];
}

static void wfile(const char *name, const void *d, size_t n)
{
	char tmp[96];
	int f;

	snprintf(tmp, sizeof tmp, "%s.tmp", name);
	f = open(tmp, O_WRONLY | O_CREAT | O_TRUNC, 0644);
	if (f < 0) return;
	if (write(f, d, n) == (ssize_t)n) { close(f); rename(tmp, name); }
	else { close(f); unlink(tmp); }
}

/* The 6.6 ISP driver does not fill the sub-channel of the V4L2 buffer: make the 640x360 picture from the main one
 * (3x3 decimation, a 3-sample average along the line). */
static void sub_scale(const unsigned char *src, unsigned char *dst)
{
	const unsigned char *uv = src + W * H;
	unsigned char *duv = dst + SW * SH;

	for (int y = 0; y < SH; y++) {
		const unsigned char *r = src + (3 * y + 1) * W;
		unsigned char *o = dst + y * SW;

		for (int x = 0; x < SW; x++)
			o[x] = (r[3 * x] + r[3 * x + 1] + r[3 * x + 2]) / 3;
	}
	for (int y = 0; y < SH / 2; y++) {
		const unsigned char *r = uv + (3 * y + 1) * W;
		unsigned char *o = duv + y * SW;

		for (int x = 0; x < SW / 2; x++) {
			o[2 * x] = r[(3 * x + 1) * 2];
			o[2 * x + 1] = r[(3 * x + 1) * 2 + 1];
		}
	}
}

static double now_s(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec + t.tv_nsec / 1e9;
}

static void *ld(const char *dir, const char *name, int must)
{
	char p[300];
	void *h;

	snprintf(p, sizeof p, "%s/%s", dir, name);
	h = dlopen(p, RTLD_LAZY | RTLD_GLOBAL);
	if (!h) {
		LOG("dlopen %s: %s\n", p, dlerror());
		if (must) exit(2);
	}
	return h;
}

static int num(const char *s)
{
	int v = 0;

	while (*s >= '0' && *s <= '9') v = v * 10 + (*s++ - '0');
	return v;
}

/* ---- H.264 bit stream bookkeeping ---- */
static unsigned char sps[128], pps[64], vps[64];
static int vps_len;
static int hevc;		/* -c h265: RFC 7798 packetization, VPS/SPS/PPS */
static char sprop_v[100];
#define NT(b) (hevc ? ((b) >> 1) & 63 : (b) & 31)
#define HAVE_PS (sps_len && pps_len && (!hevc || vps_len))
static int sps_len, pps_len;
static char sprop[400], plid[8];

static const char b64t[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static int b64(char *o, const unsigned char *d, int n)
{
	int i, k = 0;

	for (i = 0; i + 2 < n; i += 3) {
		o[k++] = b64t[d[i] >> 2];
		o[k++] = b64t[((d[i] & 3) << 4) | (d[i + 1] >> 4)];
		o[k++] = b64t[((d[i + 1] & 15) << 2) | (d[i + 2] >> 6)];
		o[k++] = b64t[d[i + 2] & 63];
	}
	if (n - i == 1) {
		o[k++] = b64t[d[i] >> 2];
		o[k++] = b64t[(d[i] & 3) << 4];
		o[k++] = '='; o[k++] = '=';
	} else if (n - i == 2) {
		o[k++] = b64t[d[i] >> 2];
		o[k++] = b64t[((d[i] & 3) << 4) | (d[i + 1] >> 4)];
		o[k++] = b64t[(d[i + 1] & 15) << 2];
		o[k++] = '=';
	}
	o[k] = 0;
	return k;
}

/* next NAL unit in an Annex B buffer: returns its start (after the start code), sets *len; -1 at the end */
static int next_nal(const unsigned char *d, int n, int from, int *len)
{
	int i = from, s = -1;

	for (; i + 3 <= n; i++)
		if (d[i] == 0 && d[i + 1] == 0 && d[i + 2] == 1) {
			if (s >= 0) {
				int e = i;

				while (e > s && d[e - 1] == 0) e--;
				*len = e - s;
				return s;
			}
			s = i + 3;
			i += 2;
		}
	if (s < 0) return -1;
	*len = n - s;
	return s;
}

static void learn_params(const unsigned char *d, int n)
{
	int pos = 0, l, s;

	while ((s = next_nal(d, n, pos, &l)) >= 0) {
		int t = NT(d[s]);

		if (hevc) {
			if (t == 32 && l < (int)sizeof vps) { memcpy(vps, d + s, l); vps_len = l; }
			if (t == 33 && l < (int)sizeof sps) { memcpy(sps, d + s, l); sps_len = l; }
			if (t == 34 && l < (int)sizeof pps) { memcpy(pps, d + s, l); pps_len = l; }
		} else {
			if (t == 7 && l < (int)sizeof sps) { memcpy(sps, d + s, l); sps_len = l; }
			if (t == 8 && l < (int)sizeof pps) { memcpy(pps, d + s, l); pps_len = l; }
		}
		pos = s + l;
	}
	if (!HAVE_PS) return;
	{
		char a[200], c[100];

		b64(a, sps, sps_len);
		b64(c, pps, pps_len);
		if (hevc) {
			b64(sprop_v, vps, vps_len);
			snprintf(sprop, sizeof sprop, "sprop-vps=%s;sprop-sps=%s;sprop-pps=%s", sprop_v, a, c);
		} else if (sps_len > 3) {
			snprintf(sprop, sizeof sprop, "%s,%s", a, c);
			snprintf(plid, sizeof plid, "%02x%02x%02x", sps[1], sps[2], sps[3]);
		}
	}
}

/* ---- GOP cache: the last IDR and the frames after it ---- */
struct cframe { unsigned char *d; int len; uint32_t ts; };
static struct cframe cache[CACHE_FRAMES];
static int ncache, cache_ok;
static int cache_bytes;

static void cache_reset(void)
{
	for (int i = 0; i < ncache; i++) free(cache[i].d);
	ncache = 0; cache_bytes = 0; cache_ok = 1;
}

static void cache_add(const unsigned char *d, int len, uint32_t ts, int idr)
{
	if (idr) cache_reset();
	if (!cache_ok) return;
	if (ncache >= CACHE_FRAMES || cache_bytes + len > CACHE_MAX) { cache_ok = 0; return; }
	cache[ncache].d = malloc(len);
	if (!cache[ncache].d) { cache_ok = 0; return; }
	memcpy(cache[ncache].d, d, len);
	cache[ncache].len = len; cache[ncache].ts = ts;
	ncache++; cache_bytes += len;
}


/* ---- MD5 (for RTSP Digest) and Base64 decoding (for Basic) ---- */
struct md5 { uint32_t a, b, c, d; uint64_t n; unsigned char buf[64]; };

static const uint32_t K5[64] = {
	0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501,
	0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821,
	0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa, 0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
	0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed, 0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a,
	0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70,
	0x289b7ec6, 0xeaa127fa, 0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665,
	0xf4292244, 0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
	0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391 };
static const unsigned char R5[64] = {
	7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
	4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21 };

static void md5_block(struct md5 *m, const unsigned char *p)
{
	uint32_t w[16], a = m->a, b = m->b, c = m->c, d = m->d;
	int i;

	for (i = 0; i < 16; i++) w[i] = p[i * 4] | p[i * 4 + 1] << 8 | p[i * 4 + 2] << 16 | (uint32_t)p[i * 4 + 3] << 24;
	for (i = 0; i < 64; i++) {
		uint32_t f, t;
		int g;

		if (i < 16) { f = (b & c) | (~b & d); g = i; }
		else if (i < 32) { f = (d & b) | (~d & c); g = (5 * i + 1) & 15; }
		else if (i < 48) { f = b ^ c ^ d; g = (3 * i + 5) & 15; }
		else { f = c ^ (b | ~d); g = (7 * i) & 15; }
		t = d; d = c; c = b;
		f = a + f + K5[i] + w[g];
		b = b + ((f << R5[i]) | (f >> (32 - R5[i])));
		a = t;
	}
	m->a += a; m->b += b; m->c += c; m->d += d;
}

static void md5_init(struct md5 *m) { m->a = 0x67452301; m->b = 0xefcdab89; m->c = 0x98badcfe; m->d = 0x10325476; m->n = 0; }

static void md5_add(struct md5 *m, const void *d, size_t n)
{
	const unsigned char *p = d;

	while (n--) {
		m->buf[m->n++ & 63] = *p++;
		if (!(m->n & 63)) md5_block(m, m->buf);
	}
}

static void md5_hex(struct md5 *m, char *out)
{
	uint64_t bits = m->n * 8;
	unsigned char z = 0x80, pad = 0, r[16];
	uint32_t v[4];
	int i;

	md5_add(m, &z, 1);
	while ((m->n & 63) != 56) md5_add(m, &pad, 1);
	for (i = 0; i < 8; i++) { unsigned char c = bits >> (8 * i); md5_add(m, &c, 1); }
	v[0] = m->a; v[1] = m->b; v[2] = m->c; v[3] = m->d;
	for (i = 0; i < 16; i++) r[i] = v[i / 4] >> (8 * (i % 4));
	for (i = 0; i < 16; i++) { out[i * 2] = "0123456789abcdef"[r[i] >> 4]; out[i * 2 + 1] = "0123456789abcdef"[r[i] & 15]; }
	out[32] = 0;
}

static void md5s(char *out, int n, const char *a, const char *b, const char *c)
{
	struct md5 m;
	const char *p[3] = { a, b, c };

	md5_init(&m);
	for (int i = 0; i < n; i++) {
		if (i) md5_add(&m, ":", 1);
		md5_add(&m, p[i], strlen(p[i]));
	}
	md5_hex(&m, out);
}

static int b64dec(char *o, int osz, const char *s)
{
	int k = 0, acc = 0, bits = 0;

	for (; *s && *s != '='; s++) {
		const char *q = strchr(b64t, *s);

		if (!q) continue;
		acc = acc << 6 | (int)(q - b64t); bits += 6;
		if (bits >= 8) { bits -= 8; if (k < osz - 1) o[k++] = (acc >> bits) & 255; }
	}
	o[k] = 0;
	return k;
}

/* ---- authentication: user and password from a file (one password for the camera); none = open ---- */
static char au_user[64] = "root", au_pass[128];
static int au_on;

static const char *hdr(const char *req, const char *name, char *o, int osz);

static int field(const char *h, const char *key, char *o, int osz)
{
	const char *p = strstr(h, key);
	int n = 0;

	if (!p) return 0;
	p += strlen(key);
	if (*p == '"') { p++; while (*p && *p != '"' && n < osz - 1) o[n++] = *p++; }
	else while (*p && *p != ',' && *p != ' ' && *p != '\r' && n < osz - 1) o[n++] = *p++;
	o[n] = 0;
	return 1;
}

static int auth_ok(const char *req, const char *method, const char *nonce)
{
	char a[512];

	if (!au_on) return 1;
	if (!hdr(req, "Authorization", a, sizeof a)) return 0;
	if (!strncasecmp(a, "Basic ", 6)) {
		char d[200], want[200];

		b64dec(d, sizeof d, a + 6);
		snprintf(want, sizeof want, "%s:%s", au_user, au_pass);
		return !strcmp(d, want);
	}
	if (!strncasecmp(a, "Digest ", 7)) {
		char u[64], n[64], uri[256], resp[40], ha1[33], ha2[33], exp[33];

		if (!field(a, "username=", u, sizeof u) || !field(a, "nonce=", n, sizeof n) ||
		    !field(a, "uri=", uri, sizeof uri) || !field(a, "response=", resp, sizeof resp))
			return 0;
		if (strcmp(u, au_user) || strcmp(n, nonce)) return 0;
		md5s(ha1, 3, au_user, "TC100", au_pass);
		md5s(ha2, 2, method, uri, "");
		{
			struct md5 m;

			md5_init(&m);
			md5_add(&m, ha1, 32); md5_add(&m, ":", 1); md5_add(&m, n, strlen(n)); md5_add(&m, ":", 1); md5_add(&m, ha2, 32);
			md5_hex(&m, exp);
		}
		return !strcmp(exp, resp);
	}
	return 0;
}

/* ---- RTSP clients ---- */
struct cli {
	int fd;
	int playing, wait_idr;
	int tcp;			/* interleaved over the RTSP connection */
	int ch;				/* RTP channel when interleaved */
	struct sockaddr_in udp;		/* client RTP address */
	uint16_t seq;
	int a_ok, a_ch;			/* audio track set up, its interleaved channel */
	struct sockaddr_in a_udp;	/* client audio RTP address */
	uint16_t a_seq;
	char sess[16];
	char nonce[24];
	char buf[4096];
	int blen;
	time_t last;
	unsigned char *q;		/* output queue (non-blocking socket) */
	int qlen, qpos, qcap;
	time_t qprog;
	unsigned long dropped;
};
static struct cli cl[MAXCLI];
static int udpfd = -1;
static uint16_t srv_rtp = 5004;
static const uint32_t SSRC = 0x54433130;	/* "TC10" */

static void cli_close(struct cli *c)
{
	if (c->fd >= 0) close(c->fd);
	free(c->q);
	memset(c, 0, sizeof *c);
	c->fd = -1;
}

/* output queue: the socket is non-blocking; a slow client never stalls the encoder, it just skips to the next IDR */
static int qfree(struct cli *c) { return QMAX - (c->qlen - c->qpos); }

static int qsend(struct cli *c, const void *p, int n)
{
	if (c->qpos && c->qpos == c->qlen) c->qpos = c->qlen = 0;
	if (c->qlen + n > c->qcap) {
		int nc = c->qcap ? c->qcap : 16384;
		unsigned char *nq;

		if (c->qpos) {			/* compact first */
			memmove(c->q, c->q + c->qpos, c->qlen - c->qpos);
			c->qlen -= c->qpos; c->qpos = 0;
		}
		while (nc < c->qlen + n) nc *= 2;
		if (nc > QMAX + 4096) nc = QMAX + 4096;
		if (c->qlen + n > nc) return -1;
		if (nc > c->qcap) {
			nq = realloc(c->q, nc);
			if (!nq) return -1;
			c->q = nq; c->qcap = nc;
		}
	}
	memcpy(c->q + c->qlen, p, n);
	c->qlen += n;
	return 0;
}

/* push the queue out; returns -1 when the connection is gone */
static int qflush(struct cli *c)
{
	while (c->qpos < c->qlen) {
		int r = send(c->fd, c->q + c->qpos, c->qlen - c->qpos, MSG_NOSIGNAL);

		if (r < 0) {
			if (errno == EINTR) continue;
			if (errno == EAGAIN || errno == EWOULDBLOCK) return 0;
			return -1;
		}
		c->qpos += r;
		c->qprog = time(NULL);
	}
	c->qpos = c->qlen = 0;
	c->qprog = time(NULL);
	return 0;
}

static int rtp_out(struct cli *c, const unsigned char *hdr12, const unsigned char *pl, int n)
{
	unsigned char pk[16 + RTP_PAYLOAD + 64];

	memcpy(pk + 4, hdr12, 12);
	memcpy(pk + 16, pl, n);
	if (c->tcp) {
		pk[0] = '$'; pk[1] = c->ch; pk[2] = (12 + n) >> 8; pk[3] = (12 + n) & 255;
		return qsend(c, pk, 16 + n);
	}
	return sendto(udpfd, pk + 4, 12 + n, 0, (struct sockaddr *)&c->udp, sizeof c->udp) < 0 ? -1 : 0;
}

/* ---- audio: microphone (ALSA, via arecord) -> G.711 A-law -> RTP PT 8, 8 kHz mono, 20 ms per packet ---- */
static int audio_on;
static FILE *aud_f;
static int aud_fd = -1;
static time_t aud_retry;
static uint32_t aud_ts = 0x1234;
static unsigned char aud_buf[160 * 2];
static int aud_n;

static unsigned char alaw(int s)
{
	int mask = 0xD5, e, m;

	if (s < 0) { mask = 0x55; s = -s - 1; }
	if (s > 32767) s = 32767;
	if (s < 256) return ((s >> 4) ^ mask) & 0xff;
	for (e = 1; e < 7 && s >= (512 << (e - 1)); e++) ;
	m = (s >> (e + 3)) & 0x0f;
	return (((e << 4) | m) ^ mask) & 0xff;
}

static void aud_open(void)
{
	aud_retry = time(NULL) + 5;
	aud_f = popen("exec arecord -q -D hw:0,0 -f S16_LE -r 8000 -c 1 -t raw -F 32000 -B 128000 2>/dev/null", "r");
	if (!aud_f) { LOG("audio: arecord failed\n"); return; }
	aud_fd = fileno(aud_f);
	fcntl(aud_fd, F_SETFL, fcntl(aud_fd, F_GETFL) | O_NONBLOCK);
	aud_n = 0;
}

static void aud_send(const unsigned char *pl, int n)
{
	for (int i = 0; i < MAXCLI; i++) {
		struct cli *c = &cl[i];
		unsigned char pk[4 + 12 + 160];

		if (c->fd < 0 || !c->playing || !c->a_ok) continue;
		pk[4] = 0x80; pk[5] = 8;
		pk[6] = c->a_seq >> 8; pk[7] = c->a_seq & 255; c->a_seq++;
		pk[8] = aud_ts >> 24; pk[9] = aud_ts >> 16; pk[10] = aud_ts >> 8; pk[11] = aud_ts;
		pk[12] = (SSRC + 1) >> 24; pk[13] = (SSRC + 1) >> 16; pk[14] = (SSRC + 1) >> 8; pk[15] = (SSRC + 1);
		memcpy(pk + 16, pl, n);
		if (c->tcp) {
			if (qfree(c) < 4096) continue;	/* congested: audio is dropped before video is */
			pk[0] = '$'; pk[1] = c->a_ch; pk[2] = (12 + n) >> 8; pk[3] = (12 + n) & 255;
			if (qsend(c, pk, 16 + n) || qflush(c)) cli_close(c);
		} else {
			sendto(udpfd, pk + 4, 12 + n, 0, (struct sockaddr *)&c->a_udp, sizeof c->a_udp);
		}
	}
	aud_ts += n;
}

static void aud_pump(void)
{
	unsigned char raw[1024];
	int r;

	while ((r = read(aud_fd, raw, sizeof raw)) > 0) {
		static int odd = -1;

		for (int i = 0; i < r; i++) {
			if (odd < 0) { odd = raw[i]; continue; }
			aud_buf[aud_n++] = alaw((int16_t)(odd | (raw[i] << 8)));
			odd = -1;
			if (aud_n == 160) { aud_send(aud_buf, 160); aud_n = 0; }
		}
	}
	if (r == 0 || (r < 0 && errno != EAGAIN && errno != EINTR)) {
		pclose(aud_f); aud_f = NULL; aud_fd = -1;
	}
}

static int send_pkt(struct cli *c, uint32_t ts, int marker, const unsigned char *pl, int n)
{
	unsigned char h[12];

	h[0] = 0x80; h[1] = (marker ? 0x80 : 0) | 96;
	h[2] = c->seq >> 8; h[3] = c->seq & 255; c->seq++;
	h[4] = ts >> 24; h[5] = ts >> 16; h[6] = ts >> 8; h[7] = ts;
	h[8] = SSRC >> 24; h[9] = SSRC >> 16; h[10] = SSRC >> 8; h[11] = SSRC;
	return rtp_out(c, h, pl, n);
}

/* one NAL unit as one packet or FU fragments (FU-A for H.264, RFC 7798 FU for H.265) */
static int send_nal(struct cli *c, uint32_t ts, const unsigned char *nal, int len, int last)
{
	if (len <= RTP_PAYLOAD)
		return send_pkt(c, ts, last, nal, len);
	{
		unsigned char fu[RTP_PAYLOAD + 3];
		int hl = hevc ? 2 : 1, ph = hevc ? 3 : 2, off = hl, first = 1;

		while (off < len) {
			int n = len - off > RTP_PAYLOAD - ph ? RTP_PAYLOAD - ph : len - off;
			int end = off + n >= len;

			if (hevc) {
				fu[0] = (nal[0] & 0x81) | (49 << 1);
				fu[1] = nal[1];
				fu[2] = (first ? 0x80 : 0) | (end ? 0x40 : 0) | ((nal[0] >> 1) & 63);
			} else {
				fu[0] = (nal[0] & 0xe0) | 28;
				fu[1] = (first ? 0x80 : 0) | (end ? 0x40 : 0) | (nal[0] & 31);
			}
			memcpy(fu + ph, nal + off, n);
			if (send_pkt(c, ts, last && end, fu, n + ph)) return -1;
			off += n; first = 0;
		}
	}
	return 0;
}

/* VPS (H.265), SPS and PPS in band */
static int send_ps(struct cli *c, uint32_t ts)
{
	if (hevc && send_nal(c, ts, vps, vps_len, 0)) return -1;
	return send_nal(c, ts, sps, sps_len, 0) || send_nal(c, ts, pps, pps_len, 0);
}

static int send_frame(struct cli *c, const unsigned char *d, int n, uint32_t ts)
{
	int pos = 0, l, s;
	struct { int s, l; } nl[16];
	int k = 0, i;

	while (k < 16 && (s = next_nal(d, n, pos, &l)) >= 0) {
		int t = NT(d[s]);

		pos = s + l;
		if (t == (hevc ? 35 : 9)) continue;		/* access unit delimiter */
		nl[k].s = s; nl[k].l = l; k++;
	}
	for (i = 0; i < k; i++)
		if (send_nal(c, ts, d + nl[i].s, nl[i].l, i == k - 1)) return -1;
	return 0;
}

/* queue space a frame needs: payload, RTP/interleave headers per packet, parameter sets */
static int frame_need(int n) { return n + (n / (RTP_PAYLOAD - 2) + 12) * 18 + 400; }

static void bcast(const unsigned char *d, int n, uint32_t ts, int idr)
{
	for (int i = 0; i < MAXCLI; i++) {
		struct cli *c = &cl[i];

		if (c->fd < 0 || !c->playing) continue;
		if (c->wait_idr && !idr) continue;
		if (c->tcp && qfree(c) < frame_need(n)) {	/* congested: skip this frame, resume at the next IDR */
			c->wait_idr = 1;
			c->dropped++;
			continue;
		}
		c->wait_idr = 0;
		if (idr && HAVE_PS) {	/* parameter sets in band before every IDR that lacks them */
			if (send_ps(c, ts)) { cli_close(c); continue; }
		}
		if (send_frame(c, d, n, ts) || (c->tcp && qflush(c))) cli_close(c);
	}
}

static void reply(struct cli *c, int code, const char *txt, int cseq, const char *extra, const char *body)
{
	char b[2048];
	int n = snprintf(b, sizeof b, "RTSP/1.0 %d %s\r\nCSeq: %d\r\nServer: tc100-rtsp\r\n%s", code, txt, cseq, extra ? extra : "");

	if (body)
		n += snprintf(b + n, sizeof b - n, "Content-Type: application/sdp\r\nContent-Length: %d\r\n\r\n%s", (int)strlen(body), body);
	else
		n += snprintf(b + n, sizeof b - n, "\r\n");
	if (qsend(c, b, n) || qflush(c)) cli_close(c);
}

static const char *hdr(const char *req, const char *name, char *o, int osz)
{
	const char *p = req;
	int nl = strlen(name);

	while ((p = strstr(p, "\r\n")) != NULL) {
		p += 2;
		if (!strncasecmp(p, name, nl) && p[nl] == ':') {
			const char *v = p + nl + 1, *e;

			while (*v == ' ') v++;
			e = strstr(v, "\r\n");
			if (!e) e = v + strlen(v);
			snprintf(o, osz, "%.*s", (int)(e - v), v);
			return o;
		}
	}
	return NULL;
}

static void play_burst(struct cli *c)
{
	int need = 400;

	for (int i = 0; i < ncache; i++) need += frame_need(cache[i].len);
	if (cache_ok && ncache && (!c->tcp || qfree(c) > need)) {
		if (HAVE_PS && send_ps(c, cache[0].ts)) { cli_close(c); return; }
		for (int i = 0; i < ncache; i++)
			if (send_frame(c, cache[i].d, cache[i].len, cache[i].ts)) { cli_close(c); return; }
		if (c->tcp && qflush(c)) { cli_close(c); return; }
		c->wait_idr = 0;
	} else {
		c->wait_idr = 1;
	}
}

static void handle(struct cli *c, char *req, int cseq_default)
{
	char m[16] = "", url[256] = "", v[300], ex[512];
	int cseq = cseq_default;
	struct sockaddr_in me;
	socklen_t ml = sizeof me;
	char host[32] = "0.0.0.0";

	{	/* "METHOD URL RTSP/1.0" */
		int i = 0, j = 0;

		while (req[i] && req[i] != ' ' && i < 15) { m[i] = req[i]; i++; }
		m[i] = 0;
		while (req[i] == ' ') i++;
		while (req[i] && req[i] != ' ' && req[i] != '\r' && j < 255) url[j++] = req[i++];
		url[j] = 0;
	}
	if (hdr(req, "CSeq", v, sizeof v)) cseq = num(v);
	if (!getsockname(c->fd, (struct sockaddr *)&me, &ml)) inet_ntop(AF_INET, &me.sin_addr, host, sizeof host);
	c->last = time(NULL);

	if (au_on && strcmp(m, "OPTIONS") && !auth_ok(req, m, c->nonce)) {
		char ch[400];

		if (!c->nonce[0]) snprintf(c->nonce, sizeof c->nonce, "%08x%08x", (unsigned)time(NULL), (unsigned)(c - cl) * 2654435761u ^ (unsigned)(uintptr_t)c);
		snprintf(ch, sizeof ch, "WWW-Authenticate: Digest realm=\"TC100\", nonce=\"%s\"\r\nWWW-Authenticate: Basic realm=\"TC100\"\r\n", c->nonce);
		reply(c, 401, "Unauthorized", cseq, ch, NULL);
		return;
	}
	if (!strcmp(m, "OPTIONS")) {
		reply(c, 200, "OK", cseq, "Public: OPTIONS, DESCRIBE, SETUP, PLAY, PAUSE, TEARDOWN, GET_PARAMETER\r\n", NULL);
	} else if (!strcmp(m, "DESCRIBE")) {
		char sdp[1536], base[300], fm[600];

		if (!HAVE_PS) { reply(c, 503, "Service Unavailable", cseq, NULL, NULL); return; }
		if (hevc) snprintf(fm, sizeof fm, "%s", sprop);
		else snprintf(fm, sizeof fm, "packetization-mode=1;profile-level-id=%s;sprop-parameter-sets=%s", plid, sprop);
		snprintf(base, sizeof base, "Content-Base: %s%s\r\n", url, url[strlen(url) - 1] == '/' ? "" : "/");
		snprintf(sdp, sizeof sdp,
			 "v=0\r\no=- 1 1 IN IP4 %s\r\ns=TC100\r\nc=IN IP4 0.0.0.0\r\nt=0 0\r\na=control:*\r\n"
			 "m=video 0 RTP/AVP 96\r\na=rtpmap:96 %s/90000\r\n"
			 "a=fmtp:96 %s\r\na=control:track1\r\n",
			 host, hevc ? "H265" : "H264", fm);
		if (audio_on) strncat(sdp, "m=audio 0 RTP/AVP 8\r\na=rtpmap:8 PCMA/8000\r\na=control:track2\r\n", sizeof sdp - strlen(sdp) - 1);
		reply(c, 200, "OK", cseq, base, sdp);
	} else if (!strcmp(m, "SETUP")) {
		char tr[300];

		if (!hdr(req, "Transport", tr, sizeof tr)) { reply(c, 461, "Unsupported Transport", cseq, NULL, NULL); return; }
		if (!c->sess[0]) snprintf(c->sess, sizeof c->sess, "%08x", (unsigned)(time(NULL) ^ (c - cl) * 7919));
		if (audio_on && strstr(url, "track2")) {	/* audio track */
			if (strstr(tr, "TCP")) {
				char *q = strstr(tr, "interleaved=");

				c->tcp = 1; c->a_ch = q ? num(q + 12) : 2;
				snprintf(ex, sizeof ex, "Transport: RTP/AVP/TCP;unicast;interleaved=%d-%d\r\nSession: %s;timeout=60\r\n", c->a_ch, c->a_ch + 1, c->sess);
			} else {
				char *q = strstr(tr, "client_port=");
				struct sockaddr_in pe;
				socklen_t pl = sizeof pe;

				if (!q || getpeername(c->fd, (struct sockaddr *)&pe, &pl)) { reply(c, 461, "Unsupported Transport", cseq, NULL, NULL); return; }
				c->tcp = 0; c->a_udp = pe; c->a_udp.sin_port = htons(num(q + 12));
				snprintf(ex, sizeof ex, "Transport: RTP/AVP;unicast;client_port=%d-%d;server_port=%d-%d\r\nSession: %s;timeout=60\r\n",
					 num(q + 12), num(q + 12) + 1, srv_rtp, srv_rtp + 1, c->sess);
			}
			c->a_seq = (uint16_t)(time(NULL) * 17);
			c->a_ok = 1;
			reply(c, 200, "OK", cseq, ex, NULL);
			return;
		}
		if (strstr(tr, "TCP")) {
			char *q = strstr(tr, "interleaved=");

			c->tcp = 1; c->ch = q ? num(q + 12) : 0;
			snprintf(ex, sizeof ex, "Transport: RTP/AVP/TCP;unicast;interleaved=%d-%d\r\nSession: %s;timeout=60\r\n", c->ch, c->ch + 1, c->sess);
		} else {
			char *q = strstr(tr, "client_port=");
			struct sockaddr_in pe;
			socklen_t pl = sizeof pe;

			if (!q || getpeername(c->fd, (struct sockaddr *)&pe, &pl)) { reply(c, 461, "Unsupported Transport", cseq, NULL, NULL); return; }
			c->tcp = 0; c->udp = pe; c->udp.sin_port = htons(num(q + 12));
			snprintf(ex, sizeof ex, "Transport: RTP/AVP;unicast;client_port=%d-%d;server_port=%d-%d\r\nSession: %s;timeout=60\r\n",
				 num(q + 12), num(q + 12) + 1, srv_rtp, srv_rtp + 1, c->sess);
		}
		c->seq = (uint16_t)(time(NULL) * 31);
		reply(c, 200, "OK", cseq, ex, NULL);
	} else if (!strcmp(m, "PLAY")) {
		snprintf(ex, sizeof ex, "Range: npt=0.000-\r\nSession: %s\r\n", c->sess);
		reply(c, 200, "OK", cseq, ex, NULL);
		if (c->fd >= 0) { c->playing = 1; play_burst(c); }
	} else if (!strcmp(m, "PAUSE")) {
		c->playing = 0;
		snprintf(ex, sizeof ex, "Session: %s\r\n", c->sess);
		reply(c, 200, "OK", cseq, ex, NULL);
	} else if (!strcmp(m, "GET_PARAMETER") || !strcmp(m, "SET_PARAMETER")) {
		snprintf(ex, sizeof ex, "Session: %s\r\n", c->sess);
		reply(c, 200, "OK", cseq, ex, NULL);
	} else if (!strcmp(m, "TEARDOWN")) {
		reply(c, 200, "OK", cseq, NULL, NULL);
		cli_close(c);
	} else {
		reply(c, 501, "Not Implemented", cseq, NULL, NULL);
	}
}

/* read what the client sent: RTSP requests, interleaved RTCP frames are skipped */
static void cli_read(struct cli *c)
{
	int r = recv(c->fd, c->buf + c->blen, sizeof c->buf - 1 - c->blen, 0);

	if (r <= 0) {
		if (r < 0 && (errno == EAGAIN || errno == EINTR)) return;
		cli_close(c);
		return;
	}
	c->blen += r;
	c->buf[c->blen] = 0;
	for (;;) {
		char *e;
		int used;

		if (c->blen >= 4 && (unsigned char)c->buf[0] == '$') {
			int len = 4 + ((unsigned char)c->buf[2] << 8 | (unsigned char)c->buf[3]);

			if (c->blen < len) return;
			memmove(c->buf, c->buf + len, c->blen - len);
			c->blen -= len;
			continue;
		}
		e = strstr(c->buf, "\r\n\r\n");
		if (!e) {
			if (c->blen >= (int)sizeof c->buf - 1) cli_close(c);
			return;
		}
		used = e + 4 - c->buf;
		*e = 0;
		strcat(c->buf, "\r\n");	/* keeps the header scanner happy on the last line */
		handle(c, c->buf, 1);
		if (c->fd < 0) return;
		memmove(c->buf, c->buf + used, c->blen - used);
		c->blen -= used;
		c->buf[c->blen] = 0;
	}
}

int main(int argc, char **argv)
{
	const char *akuio = "/mnt/sd/tc100test/libakuio.so", *dev = "/dev/video0", *dir = "/mnt/sd/lib";
	const char *pwfile = NULL;
	int o, kbps = 2000, fps = 15, qmin = 25, qmax = 48, port = 554;

	for (o = 1; o + 1 < argc; o += 2) {
		const char *a = argv[o], *v = argv[o + 1];

		if (!strcmp(a, "-p")) port = num(v);
		else if (!strcmp(a, "-c")) hevc = !strcmp(v, "h265");
		else if (!strcmp(a, "-b")) kbps = num(v);
		else if (!strcmp(a, "-f")) fps = num(v);
		else if (!strcmp(a, "-q")) qmin = num(v);
		else if (!strcmp(a, "-Q")) qmax = num(v);
		else if (!strcmp(a, "-d")) dev = v;
		else if (!strcmp(a, "-u")) snprintf(au_user, sizeof au_user, "%s", v);
		else if (!strcmp(a, "-w")) pwfile = v;
		else if (!strcmp(a, "-L")) dir = v;
		else if (!strcmp(a, "-A")) akuio = v;
		else if (!strcmp(a, "-a")) audio_on = num(v) != 0;
		else { LOG("usage: tc100_rtsp [-p PORT] [-b KBPS] [-f FPS] [-c h264|h265] [-q QMIN] [-Q QMAX] [-d DEV] [-L LIBDIR] [-A libakuio.so] [-a 0|1 audio]\n"); return 2; }
	}
	if (pwfile) {	/* first line of the file is the password; an empty or missing file leaves the stream open */
		FILE *pf = fopen(pwfile, "r");

		if (pf) {
			if (fgets(au_pass, sizeof au_pass, pf)) {
				au_pass[strcspn(au_pass, "\r\n")] = 0;
				au_on = au_pass[0] != 0;
			}
			fclose(pf);
		}
	}
	signal(SIGINT, on_sig); signal(SIGTERM, on_sig); signal(SIGPIPE, SIG_IGN);

	if (access("/etc/jffs2/venc.cfg", F_OK)) {
		FILE *f;

		(void)!mkdir("/etc/jffs2", 0755);
		f = fopen("/etc/jffs2/venc.cfg", "w");
		if (f) fclose(f);
	}
	if (!dlopen(akuio, RTLD_LAZY | RTLD_GLOBAL)) { LOG("dlopen %s: %s\n", akuio, dlerror()); return 2; }
	ld(dir, "libplat_common.so", 0);
	ld(dir, "libplat_thread.so", 1);
	ld(dir, "libplat_drv.so", 0);
	ld(dir, "libplat_ipcsrv.so", 0);
	ld(dir, "libplat_venc_cb.so", 1);
	ld(dir, "libakv_encode.so", 1);
	{
		void *m = ld(dir, "libmpi_venc_ex.so", 1);

		p_open = dlsym(m, "ak_venc_open");
		p_send = dlsym(m, "ak_venc_send_frame");
		p_release = dlsym(m, "ak_venc_release_stream");
		p_close = dlsym(m, "ak_venc_close");
		p_alloc = dlsym(RTLD_DEFAULT, "akuio_alloc_pmem");
		p_pinit = dlsym(RTLD_DEFAULT, "akuio_pmem_init");
		if (!p_open || !p_send || !p_release || !p_alloc) { LOG("missing encoder symbols\n"); return 2; }
	}
	if (p_pinit && p_pinit()) { LOG("akuio_pmem_init failed\n"); return 2; }

	/* capture */
	int fd = open(dev, O_RDWR | O_NONBLOCK);
	if (fd < 0) { LOG("%s: %s\n", dev, strerror(errno)); return 1; }
	struct v4l2_format fmt;
	memset(&fmt, 0, sizeof fmt);
	fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	fmt.fmt.pix.width = W; fmt.fmt.pix.height = H;
	fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_NV12; fmt.fmt.pix.field = V4L2_FIELD_NONE;
	ioctl(fd, VIDIOC_S_FMT, &fmt);
	struct v4l2_requestbuffers rq;
	memset(&rq, 0, sizeof rq);
	rq.count = 2; rq.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; rq.memory = V4L2_MEMORY_MMAP;
	if (ioctl(fd, VIDIOC_REQBUFS, &rq) < 0) { LOG("REQBUFS: %s\n", strerror(errno)); return 1; }
	void *vb[4];
	for (unsigned i = 0; i < rq.count && i < 4; i++) {
		struct v4l2_buffer b;

		memset(&b, 0, sizeof b);
		b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; b.memory = V4L2_MEMORY_MMAP; b.index = i;
		if (ioctl(fd, VIDIOC_QUERYBUF, &b) < 0) { LOG("QUERYBUF: %s\n", strerror(errno)); return 1; }
		vb[i] = mmap(NULL, b.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd, b.m.offset);
		if (vb[i] == MAP_FAILED) { LOG("mmap: %s\n", strerror(errno)); return 1; }
		ioctl(fd, VIDIOC_QBUF, &b);
	}
	enum v4l2_buf_type bt = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	if (ioctl(fd, VIDIOC_STREAMON, &bt) < 0) { LOG("STREAMON: %s\n", strerror(errno)); return 1; }

	unsigned int flen = W * H * 3 / 2, ftot = flen + SW * SH * 3 / 2;
	unsigned char *pf = (unsigned char *)p_alloc(ftot);
	double t_luma = 0, t_str = 0, t_snap = 0;
	if (!getenv("NO_JPEG")) jpeg_ok = jpeg_init() == 0;
	LOG("web pictures: hardware JPEG %s\n", jpeg_ok ? "on" : "off");
	if (!pf) { LOG("no DMA memory for the frame\n"); return 1; }

	struct venc_param pa;
	memset(&pa, 0, sizeof pa);
	pa.width = W; pa.height = H; pa.qpmin = qmin; pa.qpmax = qmax;
	pa.fps = fps; pa.gop = fps * 2; pa.kbps = kbps;
	if (hevc) { pa.codec = 2; pa.profile = 3; }
	/* H.265 as the very first use of the encoder after power-up corrupts kernel memory (seen on 6.6: oops within
	 * seconds, repeatable); after one H.264 session it is stable. So an H.265 server first runs one H.264 frame. */
	int prime = hevc && !getenv("NO_PRIME");
	struct venc_param p0 = pa;

	if (prime) { p0.codec = 0; p0.profile = 0; }
	void *enc = p_open(prime ? &p0 : &pa);
	if (!enc) { LOG("ak_venc_open failed\n"); return 1; }
	{ unsigned long (*gf)(void) = dlsym(RTLD_DEFAULT, "akuio_get_free_pmem"); LOG("encoder open, pool free %lu\n", gf ? gf() : 0UL); }

	/* network */
	int ls = socket(AF_INET, SOCK_STREAM, 0), one = 1;
	struct sockaddr_in sa;

	setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
	memset(&sa, 0, sizeof sa);
	sa.sin_family = AF_INET; sa.sin_addr.s_addr = htonl(INADDR_ANY); sa.sin_port = htons(port);
	if (bind(ls, (struct sockaddr *)&sa, sizeof sa) || listen(ls, 4)) { LOG("port %d: %s\n", port, strerror(errno)); return 1; }
	udpfd = socket(AF_INET, SOCK_DGRAM, 0);
	sa.sin_port = htons(srv_rtp);
	if (bind(udpfd, (struct sockaddr *)&sa, sizeof sa)) LOG("udp %d: %s\n", srv_rtp, strerror(errno));
	for (int i = 0; i < MAXCLI; i++) cl[i].fd = -1;
	LOG("tc100_rtsp: rtsp://<ip>:%d/  %dx%d %d fps %d kbit/s\n", port, W, H, fps, kbps);

	int active = 1;		/* encoding: at start (parameter sets) and while somebody watches */
	struct timespec t0;
	clock_gettime(CLOCK_MONOTONIC, &t0);
	unsigned long nfr = 0, ncap = 0, nbytes = 0;
	struct timespec tl = t0;
	long enc_us = 0, snd_us = 0;

	while (run) {
		fd_set fs, ws;
		struct timeval tv = { 1, 0 };
		int mx = fd > ls ? fd : ls, i, nplay = 0;

		FD_ZERO(&fs); FD_ZERO(&ws); FD_SET(fd, &fs); FD_SET(ls, &fs);
		if (audio_on && !aud_f && time(NULL) >= aud_retry) aud_open();
		if (aud_fd >= 0) { FD_SET(aud_fd, &fs); if (aud_fd > mx) mx = aud_fd; }
		for (i = 0; i < MAXCLI; i++)
			if (cl[i].fd >= 0) {
				FD_SET(cl[i].fd, &fs);
				if (cl[i].qpos < cl[i].qlen) FD_SET(cl[i].fd, &ws);
				if (cl[i].fd > mx) mx = cl[i].fd;
			}
		if (select(mx + 1, &fs, &ws, NULL, &tv) < 0) continue;
		{
			struct timespec tn;

			clock_gettime(CLOCK_MONOTONIC, &tn);
			if (tn.tv_sec - tl.tv_sec >= 5) {
				{ unsigned long dr = 0; for (int k = 0; k < MAXCLI; k++) dr += cl[k].dropped; LOG("STAT cap %lu enc %lu bytes %lu enc_ms %ld snd_ms %ld clients %d dropped %lu\n", ncap, nfr, nbytes, enc_us / 1000, snd_us / 1000, nplay, dr); }
				ncap = nfr = nbytes = 0; enc_us = snd_us = 0; tl = tn;
			}
		}

		if (aud_fd >= 0 && FD_ISSET(aud_fd, &fs)) aud_pump();
		if (FD_ISSET(ls, &fs)) {
			int s = accept(ls, NULL, NULL);

			if (s >= 0) {
				for (i = 0; i < MAXCLI && cl[i].fd >= 0; i++) ;
				if (i == MAXCLI) { close(s); }
				else {
					memset(&cl[i], 0, sizeof cl[i]);
					cl[i].fd = s; cl[i].last = time(NULL); cl[i].qprog = time(NULL);
					fcntl(s, F_SETFL, fcntl(s, F_GETFL) | O_NONBLOCK);
					setsockopt(s, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
				}
			}
		}
		for (i = 0; i < MAXCLI; i++) {
			if (cl[i].fd >= 0 && FD_ISSET(cl[i].fd, &ws) && qflush(&cl[i])) cli_close(&cl[i]);
			if (cl[i].fd >= 0 && cl[i].qpos < cl[i].qlen && time(NULL) - cl[i].qprog > 20) cli_close(&cl[i]);
			if (cl[i].fd >= 0 && FD_ISSET(cl[i].fd, &fs)) cli_read(&cl[i]);
			if (cl[i].fd >= 0 && !cl[i].tcp && time(NULL) - cl[i].last > 90) cli_close(&cl[i]);
			if (cl[i].fd >= 0 && cl[i].playing) nplay++;
		}

		if (FD_ISSET(fd, &fs)) {
			struct v4l2_buffer b;
			struct timespec t1;
			struct video_stream st;
			uint32_t ts;
			int r, idr;

			memset(&b, 0, sizeof b);
			b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; b.memory = V4L2_MEMORY_MMAP;
			if (ioctl(fd, VIDIOC_DQBUF, &b) < 0) continue;
			ncap++;
			if (prime) {
				struct video_stream ps;

				memcpy(pf, vb[b.index], flen);
				ioctl(fd, VIDIOC_QBUF, &b);
				memset(&ps, 0, sizeof ps);
				if (!p_send(enc, pf, flen, &ps) && ps.data) p_release(enc, &ps);
				p_close(enc);
				enc = p_open(&pa);
				if (!enc) { LOG("ak_venc_open failed\n"); break; }
				prime = 0;
				continue;
			}
			/* encode while someone watches, and until the parameter sets are known.
			 * Idle: the encoder state moves on without a viewer, so the next viewer gets a new encoder:
			 * its first frame is an IDR. */
			if (active && !nplay && HAVE_PS) {
				active = 0;
				cache_reset();
			} else if (!active && nplay) {
				p_close(enc);
				enc = p_open(&pa);
				if (!enc) { LOG("ak_venc_open failed\n"); break; }
				active = 1;
				cache_reset();
				for (i = 0; i < MAXCLI; i++) if (cl[i].fd >= 0 && cl[i].playing) cl[i].wait_idr = 1;
			}
			double tn = now_s();
			int d_luma = tn - t_luma >= 0.5, d_str = jpeg_ok && tn - t_str >= 0.25;
			int d_snap = jpeg_ok && (tn - t_snap >= 2.0 || !access("/tmp/snapshot_request", F_OK));

			if (d_luma) {	/* mean of the sub-stream luma samples, like tc100_streamer */
				const unsigned char *sy = vb[b.index];	/* main luma at sub-stream coordinates x3 */
				unsigned sum = 0, ns = 0;
				char lb[16];
				int ln;

				for (int y = 10; y < SH - 10; y += 16)
					for (int x = 10; x < SW - 10; x += 16) { sum += sy[(y * 3) * W + x * 3]; ns++; }
				ln = snprintf(lb, sizeof lb, "%u\n", ns ? sum / ns : 50);
				wfile("/tmp/cam_luma", lb, ln);
				t_luma = tn;
			}
			if (active || d_snap) memcpy(pf, vb[b.index], flen);
			if (d_str) sub_scale(vb[b.index], pf + flen);
			ioctl(fd, VIDIOC_QBUF, &b);
			if (active) {
				clock_gettime(CLOCK_MONOTONIC, &t1);
				ts = (uint32_t)(((t1.tv_sec - t0.tv_sec) * 1000000ULL + (t1.tv_nsec - t0.tv_nsec) / 1000) * 9 / 100);
				memset(&st, 0, sizeof st);
				{ struct timespec ta, tb; clock_gettime(CLOCK_MONOTONIC, &ta);
				r = p_send(enc, pf, flen, &st);
				clock_gettime(CLOCK_MONOTONIC, &tb); enc_us += (tb.tv_sec - ta.tv_sec) * 1000000L + (tb.tv_nsec - ta.tv_nsec) / 1000; }
				if (!r && st.data && st.len) {
					idr = 0;
					{
						int pos = 0, l, s;

						while ((s = next_nal(st.data, st.len, pos, &l)) >= 0) {
							{ int t = NT(st.data[s]); if (hevc ? (t >= 16 && t <= 21) : t == 5) idr = 1; }
							pos = s + l;
						}
					}
					if (idr) learn_params(st.data, st.len);
					if (getenv("RTSP_DEBUG")) LOG("FRAME %s len %u\n", idr ? "IDR" : "P", st.len);
					if (st.len > 10 || idr) {	/* skip frames still count in the timeline */
						cache_add(st.data, st.len, ts, idr);
						{ struct timespec ta, tb; clock_gettime(CLOCK_MONOTONIC, &ta);
						bcast(st.data, st.len, ts, idr);
						clock_gettime(CLOCK_MONOTONIC, &tb); snd_us += (tb.tv_sec - ta.tv_sec) * 1000000L + (tb.tv_nsec - ta.tv_nsec) / 1000; }
						nbytes += st.len;
					}
					nfr++;
					p_release(enc, &st);
				}
			}
			if (d_str || d_snap) {
				uint32_t py = (uint32_t)p_v2p((unsigned long)pf), n;

				if (d_str && !access("/tmp/dump_sub", F_OK)) { unlink("/tmp/dump_sub"); wfile("/tmp/sub.nv12", pf + flen, SW * SH * 3 / 2); }
					if (d_str && (n = jpeg_run(py + flen, py + flen + SW * SH, SW, SH, 40))) {
					wfile("/tmp/stream.jpg", jbuf + TABLES_SIZE, n);
					wfile("/tmp/frame_ch0.jpg", jbuf + TABLES_SIZE, n);
					t_str = tn;
				}
				if (d_snap) {
					unlink("/tmp/snapshot_request");
					if ((n = jpeg_run(py, py + W * H, W, H, 35))) {
						char ts[24];

						wfile("/tmp/currentpic.cache.jpg", jbuf + TABLES_SIZE, n);
						wfile("/tmp/currentpic.cache.ts", ts, snprintf(ts, sizeof ts, "%ld\n", (long)time(NULL)));
					}
					t_snap = tn;
				}
			}
		}
	}
	if (p_close) p_close(enc);
	LOG("tc100_rtsp: stopped after %lu frames\n", nfr);
	return 0;
}
