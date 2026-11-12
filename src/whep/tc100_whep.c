/* tc100-whep: WebRTC (WHEP) gateway of the camera, item 35 (design: docs/linux-port/whep-design.md).
 *
 * A browser (or any WHEP client) POSTs an SDP offer; we answer with ICE-lite (one host candidate on the LAN
 * interface), a DTLS 1.2 server (mbedTLS, use_srtp SRTP_AES128_CM_HMAC_SHA1_80, self-signed ECDSA P-256 certificate
 * kept in /mnt/config) and SRTP (srtp.h). The media is not made here: for each viewer we open an RTSP session
 * (TCP interleaved, on the loopback) to tc100_rtsp, the secondary stream by default, and send its RTP packets on,
 * with the payload type and SSRC of the answer (H.264: SPS and PPS are put in front of every IDR, the browsers
 * need them in the stream). A crash in the TLS code never stops tc100_rtsp.
 *
 * HTTP: the daemon listens on the loopback only (127.0.0.1:8889); www/cgi-bin/whep.cgi forwards to it behind the
 * web login (httpfront + busybox httpd). POST /whep (SDP) -> 201 + SDP + Location: /whep/<id>; DELETE /whep/<id>;
 * GET /status. A viewer that stops sending authenticated ICE consent checks is dropped after 30 s (RFC 7675).
 *
 *   tc100-whep [-i wlan0[,eth0]] [-p 8889] [-u 8189] [-s sub|main] [-m 2] [-a 1] [-r 554] [-U user] [-w pwfile]
 *              [-c /mnt/config] [-d]
 * Build: Buildroot package v3/buildroot/package/tc100-whep (musl, system mbedTLS 2.28 with MBEDTLS_SSL_DTLS_SRTP);
 * on a host: see tests/docker/whep-interop.sh. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <time.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <net/if.h>
#include <netinet/in.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>	/* struct timeval: glibc brings it in through other headers, musl (the camera) does not */
#include "mbedtls/ctr_drbg.h"
#include "mbedtls/entropy.h"
#include "mbedtls/md.h"
#include "mbedtls/pk.h"
#include "mbedtls/ssl.h"
#include "mbedtls/x509_crt.h"
#include "mbedtls/x509_csr.h"
#include "mbedtls/bignum.h"
#include "mbedtls/ecp.h"
#include "whep_proto.h"

#ifndef MBEDTLS_SSL_DTLS_SRTP
#error "mbedTLS built without MBEDTLS_SSL_DTLS_SRTP (v3/buildroot/external.mk enables it in the base image)"
#endif

#define MAXS 4

enum { S_FREE, S_HS, S_RUN };

struct sess {
	int state;
	char id[17];
	uint64_t t0, last;			/* ms: created, last sign of life (STUN, DTLS, SRTCP) */
	struct sockaddr_in peer;
	int have_peer;
	char lufrag[12], lpwd[28], ofp[128];
	struct hmac_sha1 ik;			/* key of the STUN integrity: our ice-pwd */
	mbedtls_ssl_context ssl;
	mbedtls_ssl_config conf;
	int ssl_on;
	uint8_t in[25 + WH_CH_MAX];		/* one datagram, or the ClientHello rebuilt from its fragments */
	int in_len;
	struct wh_chello ch;
	int ch_done;			/* the ClientHello went to mbedTLS: later copies of its fragments are dropped */
	uint64_t t_int, t_fin;			/* DTLS retransmission timers (ms, 0 = off) */
	uint8_t ms[48], cr[32], sr[32];
	int have_keys, prf;
	struct srtp_ctx txv, txa;		/* one per stream: each has its own sequence numbers, so its own rollover counter */
	int rfd;				/* RTSP connection (-1 = none) */
	uint8_t rb[2300];
	int rn;
	char rurl[160], rsess[64];
	int cseq;
	int pt_v, pt_a, a_on;
	uint32_t v_ssrc, a_ssrc;
	uint16_t vseq, aseq;
	uint8_t sps[128], pps[64];
	int spsn, ppsn, idr_seen;
	uint32_t idr_ts;
	unsigned long n_v, n_a;
};

static struct {
	int http, udp, debug;
	unsigned http_port, udp_port;
	char iface[48], cdir[96], pwfile[96], ruser[48], auth[200];
	int main_stream, max, audio, rtsp_port;
	mbedtls_entropy_context ent;
	mbedtls_ctr_drbg_context drbg;
	mbedtls_x509_crt crt;
	mbedtls_pk_context key;
	char fp[100];
	struct sess s[MAXS];
	volatile sig_atomic_t quit;
} G;
static struct wh_nets nets;	/* TC100_NET_ALLOW (controlscripts/whep): the networks whose datagrams are read */

static const int SUITES[] = { MBEDTLS_TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256, 0 };
static const mbedtls_ssl_srtp_profile PROFILES[] = { MBEDTLS_TLS_SRTP_AES128_CM_HMAC_SHA1_80, MBEDTLS_TLS_SRTP_UNSET };

static uint64_t now_ms(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return (uint64_t)t.tv_sec * 1000 + (uint64_t)t.tv_nsec / 1000000;
}

static void logf_(const char *fmt, ...)
{
	va_list ap;
	char b[300];
	int n;

	va_start(ap, fmt);
	n = vsnprintf(b, sizeof b - 1, fmt, ap);
	va_end(ap);
	if (n < 0) return;
	if (n > (int)sizeof b - 2) n = (int)sizeof b - 2;
	b[n++] = '\n';
	(void)!write(2, b, (size_t)n);
}
#define LOG(...) logf_("tc100-whep: " __VA_ARGS__)
#define DBG(...) do { if (G.debug) logf_("tc100-whep: " __VA_ARGS__); } while (0)

static void rnd(void *p, size_t n) { mbedtls_ctr_drbg_random(&G.drbg, p, n); }

static void rnd_text(char *d, size_t n, const char *alpha)	/* n characters and a NUL */
{
	size_t i, k = strlen(alpha);

	for (i = 0; i < n; i++) { uint8_t r; rnd(&r, 1); d[i] = alpha[r % k]; }
	d[n] = 0;
}

/* ---- certificate: made once, kept in /mnt/config (never in the repository) ---- */
static int write_secret(const char *path, const char *data, mode_t mode)
{
	char tmp[128];
	int fd;
	size_t n = strlen(data);

	snprintf(tmp, sizeof tmp, "%s.tmp", path);
	fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC, mode);
	if (fd < 0) return -1;
	if (write(fd, data, n) != (ssize_t)n) { close(fd); unlink(tmp); return -1; }
	fsync(fd); close(fd);
	return rename(tmp, path);
}

static int cert_init(void)
{
	char kp[128], cp[128];
	static char kpem[1024], cpem[1536];
	mbedtls_x509write_cert w;
	mbedtls_mpi serial;
	mbedtls_pk_context k;
	unsigned char der[2];
	int r;

	snprintf(kp, sizeof kp, "%s/whep-key.pem", G.cdir);
	snprintf(cp, sizeof cp, "%s/whep-cert.pem", G.cdir);
	mbedtls_pk_init(&G.key); mbedtls_x509_crt_init(&G.crt);
	if (!mbedtls_pk_parse_keyfile(&G.key, kp, NULL) && !mbedtls_x509_crt_parse_file(&G.crt, cp)) return 0;
	mbedtls_pk_free(&G.key); mbedtls_x509_crt_free(&G.crt);
	mbedtls_pk_init(&G.key); mbedtls_x509_crt_init(&G.crt);
	LOG("making the ECDSA P-256 certificate (once)");
	mbedtls_pk_init(&k);
	if ((r = mbedtls_pk_setup(&k, mbedtls_pk_info_from_type(MBEDTLS_PK_ECKEY))) ||
	    (r = mbedtls_ecp_gen_key(MBEDTLS_ECP_DP_SECP256R1, mbedtls_pk_ec(k), mbedtls_ctr_drbg_random, &G.drbg))) {
		LOG("key generation failed: -0x%x", -r); return -1;
	}
	mbedtls_x509write_crt_init(&w);
	mbedtls_mpi_init(&serial);
	rnd(der, 2);
	mbedtls_mpi_lset(&serial, 0x10000 | (der[0] << 8 | der[1]));
	mbedtls_x509write_crt_set_md_alg(&w, MBEDTLS_MD_SHA256);
	mbedtls_x509write_crt_set_subject_key(&w, &k);
	mbedtls_x509write_crt_set_issuer_key(&w, &k);
	mbedtls_x509write_crt_set_version(&w, MBEDTLS_X509_CRT_VERSION_3);
	r = mbedtls_x509write_crt_set_subject_name(&w, "CN=tc100-whep") ||
	    mbedtls_x509write_crt_set_issuer_name(&w, "CN=tc100-whep") ||
	    mbedtls_x509write_crt_set_serial(&w, &serial) ||
	    mbedtls_x509write_crt_set_validity(&w, "20200101000000", "20500101000000");	/* the clock may be wrong: browsers do not check it */
	if (!r) r = mbedtls_x509write_crt_pem(&w, (unsigned char *)cpem, sizeof cpem, mbedtls_ctr_drbg_random, &G.drbg);
	if (!r) r = mbedtls_pk_write_key_pem(&k, (unsigned char *)kpem, sizeof kpem);
	mbedtls_x509write_crt_free(&w); mbedtls_mpi_free(&serial);
	if (r) { LOG("certificate failed: -0x%x", -r); mbedtls_pk_free(&k); return -1; }
	if (write_secret(kp, kpem, 0600) || write_secret(cp, cpem, 0644))
		LOG("cannot keep the certificate in %s (a new one is made at every start)", G.cdir);
	mbedtls_pk_free(&k);
	if (mbedtls_pk_parse_key(&G.key, (unsigned char *)kpem, strlen(kpem) + 1, NULL, 0) ||
	    mbedtls_x509_crt_parse(&G.crt, (unsigned char *)cpem, strlen(cpem) + 1)) { LOG("made certificate does not parse"); return -1; }
	return 0;
}

static void fp_text(const uint8_t *der, size_t n, char *out, size_t max)
{
	uint8_t h[32];
	size_t i;

	mbedtls_md(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), der, n, h);
	for (i = 0; i < 32 && i * 3 + 3 <= max; i++) snprintf(out + i * 3, 4, "%02X%s", h[i], i < 31 ? ":" : "");
}

/* ---- DTLS plumbing ---- */
static int bio_send(void *c, const unsigned char *b, size_t n)
{
	struct sess *s = c;

	if (!s->have_peer) return MBEDTLS_ERR_SSL_WANT_WRITE;
	if (sendto(G.udp, b, n, MSG_DONTWAIT, (struct sockaddr *)&s->peer, sizeof s->peer) < 0 && errno != EAGAIN) return MBEDTLS_ERR_SSL_INTERNAL_ERROR;
	return (int)n;
}

static int bio_recv(void *c, unsigned char *b, size_t n)
{
	struct sess *s = c;
	int m = s->in_len;

	if (m <= 0) return MBEDTLS_ERR_SSL_WANT_READ;
	if ((size_t)m > n) m = (int)n;
	memcpy(b, s->in, (size_t)m);
	s->in_len = 0;
	return m;
}

static void timer_set(void *c, uint32_t int_ms, uint32_t fin_ms)
{
	struct sess *s = c;

	if (!fin_ms) { s->t_fin = s->t_int = 0; return; }
	s->t_int = now_ms() + int_ms; s->t_fin = now_ms() + fin_ms;
}

static int timer_get(void *c)
{
	struct sess *s = c;
	uint64_t t = now_ms();

	if (!s->t_fin) return -1;
	return t >= s->t_fin ? 2 : t >= s->t_int ? 1 : 0;
}

static int export_keys(void *p, const unsigned char *ms, const unsigned char *kb, size_t maclen, size_t keylen,
			size_t ivlen, const unsigned char cr[32], const unsigned char sr[32], mbedtls_tls_prf_types prf)
{
	struct sess *s = p;

	(void)kb; (void)maclen; (void)keylen; (void)ivlen;
	memcpy(s->ms, ms, 48); memcpy(s->cr, cr, 32); memcpy(s->sr, sr, 32);
	s->prf = (int)prf; s->have_keys = 1;
	return 0;
}

/* TLS 1.2 PRF with SHA-256 (RFC 5246 5): the one cipher suite we offer uses it */
static int prf256(const uint8_t *secret, size_t sn, const char *label, const uint8_t *seed, size_t seedn, uint8_t *out, size_t outn)
{
	const mbedtls_md_info_t *md = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
	uint8_t a[32], buf[32 + 19 + 64], h[32];
	size_t ln = strlen(label), done = 0;

	if (ln + seedn > 83) return -1;
	memcpy(buf + 32, label, ln); memcpy(buf + 32 + ln, seed, seedn);
	if (mbedtls_md_hmac(md, secret, sn, buf + 32, ln + seedn, a)) return -1;			/* A(1) */
	while (done < outn) {
		size_t k = outn - done < 32 ? outn - done : 32;

		memcpy(buf, a, 32);
		if (mbedtls_md_hmac(md, secret, sn, buf, 32 + ln + seedn, h)) return -1;
		memcpy(out + done, h, k); done += k;
		if (mbedtls_md_hmac(md, secret, sn, buf, 32, h)) return -1;				/* A(i+1) */
		memcpy(a, h, 32);
	}
	return 0;
}

static void sess_free(struct sess *s)
{
	if (s->state == S_FREE) return;
	if (s->ssl_on) {
		if (s->state == S_RUN) mbedtls_ssl_close_notify(&s->ssl);
		mbedtls_ssl_free(&s->ssl); mbedtls_ssl_config_free(&s->conf);
	}
	if (s->rfd >= 0) close(s->rfd);
	if (s->id[0]) LOG("viewer %s gone (%lu video, %lu audio packets)", s->id, s->n_v, s->n_a);
	memset(s, 0, sizeof *s);
	s->rfd = -1;
}

/* ---- RTSP client (to tc100_rtsp on the loopback) ---- */
static int rtsp_send(struct sess *s, const char *method, const char *url, const char *extra)
{
	char q[700];
	int n = snprintf(q, sizeof q, "%s %s RTSP/1.0\r\n" "CSeq: %d\r\n", method, url, ++s->cseq);

	if (G.auth[0]) n += snprintf(q + n, sizeof q - (size_t)n, "Authorization: Basic %s\r\n", G.auth);
	if (s->rsess[0]) n += snprintf(q + n, sizeof q - (size_t)n, "Session: %s\r\n", s->rsess);
	if (n >= (int)sizeof q) return -1;
	n += snprintf(q + n, sizeof q - (size_t)n, "%s\r\n", extra ? extra : "");
	if (n >= (int)sizeof q) return -1;
	return send(s->rfd, q, (size_t)n, MSG_NOSIGNAL) > 0 ? 0 : -1;
}

/* reads one response (blocking, the socket has a timeout); bytes after it stay in s->rb. Returns the status code. */
static int rtsp_resp(struct sess *s, char *body, size_t bmax)
{
	for (;;) {
		char *e;
		int r;

		s->rb[s->rn] = 0;
		e = strstr((char *)s->rb, "\r\n\r\n");
		if (e) {
			size_t hl = (size_t)(e - (char *)s->rb) + 4, cl = 0, tot;
			char *c = strcasestr((char *)s->rb, "\nContent-Length:");
			int code = !strncmp((char *)s->rb, "RTSP/1.0 ", 9) ? atoi((char *)s->rb + 9) : -1;

			if (c && c < e) cl = (size_t)atoi(c + 16);
			tot = hl + cl;
			if (tot > sizeof s->rb - 1) return -1;
			if ((size_t)s->rn >= tot) {
				size_t k = tot < bmax - 1 ? tot : bmax - 1;

				memcpy(body, s->rb, k); body[k] = 0;
				memmove(s->rb, s->rb + tot, (size_t)s->rn - tot);
				s->rn -= (int)tot;
				return code;
			}
		}
		if (s->rn >= (int)sizeof s->rb - 1) return -1;
		r = (int)recv(s->rfd, s->rb + s->rn, sizeof s->rb - 1 - (size_t)s->rn, 0);
		if (r <= 0) return -1;
		s->rn += r;
	}
}

static const char *hdr_val(const char *resp, const char *name, char *o, size_t max)
{
	char key[40];
	const char *p, *e;
	size_t n;

	snprintf(key, sizeof key, "\n%s:", name);
	p = strcasestr(resp, key);
	if (!p) return NULL;
	p += strlen(key);
	while (*p == ' ') p++;
	e = p;
	while (*e && *e != '\r' && *e != '\n' && *e != ';') e++;
	n = (size_t)(e - p); if (n >= max) n = max - 1;
	memcpy(o, p, n); o[n] = 0;
	return o;
}

/* connect, DESCRIBE, SETUP the video (and the audio) over TCP; the stream starts at PLAY (rtsp_play).
 * Returns 0, or an HTTP-like status: 503 (no stream), 415 (not H.264) */
static int rtsp_open(struct sess *s, int want_audio, char *src_plid, size_t plid_max, int *has_audio)
{
	struct sockaddr_in a;
	struct timeval tv = { 3, 0 };
	static char r[2300];
	char url[200], tr[120], v[64];
	const char *p;
	int code = 0;

	s->rfd = socket(AF_INET, SOCK_STREAM, 0);
	if (s->rfd < 0) return 503;
	setsockopt(s->rfd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
	setsockopt(s->rfd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);
	memset(&a, 0, sizeof a);
	a.sin_family = AF_INET; a.sin_port = htons((uint16_t)G.rtsp_port); a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
	if (connect(s->rfd, (struct sockaddr *)&a, sizeof a)) { LOG("RTSP server not reachable (port %d)", G.rtsp_port); return 503; }
	snprintf(s->rurl, sizeof s->rurl, "rtsp://127.0.0.1:%d/%s", G.rtsp_port, G.main_stream ? "video0_unicast" : "video1");
	if (rtsp_send(s, "DESCRIBE", s->rurl, "Accept: application/sdp\r\n") || (code = rtsp_resp(s, r, sizeof r)) != 200) {
		LOG("RTSP DESCRIBE failed (%d)", code);
		return 503;
	}
	if (!strcasestr(r, "H264/90000")) { LOG("the %s stream is not H.264: no WebRTC for it", G.main_stream ? "main" : "sub"); return 415; }
	src_plid[0] = 0;
	if ((p = strstr(r, "profile-level-id="))) { snprintf(src_plid, plid_max, "%.4s", p + 17); }
	if ((p = strstr(r, "sprop-parameter-sets="))) {
		const char *c = strchr(p, ','), *e;

		p += 21;
		if (c) {
			int n;

			n = wh_b64(p, (size_t)(c - p), s->sps, sizeof s->sps); s->spsn = n > 0 ? n : 0;
			e = c + 1; while (*e && *e != ';' && *e != '\r' && *e != '\n') e++;
			n = wh_b64(c + 1, (size_t)(e - c - 1), s->pps, sizeof s->pps); s->ppsn = n > 0 ? n : 0;
		}
	}
	*has_audio = strstr(r, "m=audio") && strcasestr(r, "PCMA/8000");
	snprintf(url, sizeof url, "%s/track1", s->rurl);
	snprintf(tr, sizeof tr, "Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n");
	if (rtsp_send(s, "SETUP", url, tr) || rtsp_resp(s, r, sizeof r) != 200) { LOG("RTSP SETUP failed"); return 503; }
	if (hdr_val(r, "Session", v, sizeof v)) snprintf(s->rsess, sizeof s->rsess, "%s", v);
	if (want_audio && *has_audio) {
		snprintf(url, sizeof url, "%s/track2", s->rurl);
		snprintf(tr, sizeof tr, "Transport: RTP/AVP/TCP;unicast;interleaved=2-3\r\n");
		if (rtsp_send(s, "SETUP", url, tr) || rtsp_resp(s, r, sizeof r) != 200) { *has_audio = 0; LOG("RTSP audio SETUP failed: video only"); }
	}
	return 0;
}

static int rtsp_play(struct sess *s)
{
	static char r[2300];

	if (rtsp_send(s, "PLAY", s->rurl, "Range: npt=0.000-\r\n") || rtsp_resp(s, r, sizeof r) != 200) return -1;
	fcntl(s->rfd, F_SETFL, fcntl(s->rfd, F_GETFL) | O_NONBLOCK);
	return 0;
}

/* ---- media: RTP from the RTSP server, rewritten, protected and sent ---- */
#define WH_SRTP_TAG 10	/* bytes srtp_protect() appends to the packet, in its buffer (srtp.h: returns n + 10) */

static void send_rtp(struct sess *s, struct srtp_ctx *c, uint8_t *pkt, size_t n)
{
	size_t m;

	if (!s->have_peer) return;
	m = srtp_protect(c, pkt, n);
	sendto(G.udp, pkt, m, MSG_DONTWAIT, (struct sockaddr *)&s->peer, sizeof s->peer);
}

static void rtp_head(uint8_t *h, int pt, int marker, uint16_t seq, uint32_t ts, uint32_t ssrc)
{
	h[0] = 0x80; h[1] = (uint8_t)((marker ? 0x80 : 0) | pt);
	wh_put16(h + 2, seq);
	aes_put32(h + 4, ts); aes_put32(h + 8, ssrc);
}

static void on_video(struct sess *s, const uint8_t *p, size_t n)
{
	uint8_t b[1500];
	int nal;
	uint32_t ts;

	/* up to the buffer less the 10-byte SRTP tag that srtp_protect() adds in place: tc100_rtsp sends 12 + RTP_PAYLOAD
	 * (1400) = 1412 bytes, and the former limit of 1400 dropped every full FU-A fragment, so no IDR ever got through
	 * (tester, IPCAM2 2026-11-05: 179 video packets in 12 s, 0 picture decoded). No CSRC, no extension: none sent. */
	if (n < 13 || n > sizeof b - WH_SRTP_TAG || (p[0] & 0x1f)) return;
	nal = p[12] & 31;
	ts = aes_be32(p + 4);
	if ((nal == 5 || (nal == 28 && n > 13 && (p[13] & 0x80) && (p[13] & 31) == 5)) && (!s->idr_seen || ts != s->idr_ts)) {
		s->idr_seen = 1; s->idr_ts = ts;
		if (s->spsn) { rtp_head(b, s->pt_v, 0, s->vseq++, ts, s->v_ssrc); memcpy(b + 12, s->sps, (size_t)s->spsn); send_rtp(s, &s->txv, b, 12 + (size_t)s->spsn); }
		if (s->ppsn) { rtp_head(b, s->pt_v, 0, s->vseq++, ts, s->v_ssrc); memcpy(b + 12, s->pps, (size_t)s->ppsn); send_rtp(s, &s->txv, b, 12 + (size_t)s->ppsn); }
	}
	memcpy(b, p, n);
	rtp_head(b, s->pt_v, p[1] & 0x80, s->vseq++, ts, s->v_ssrc);
	send_rtp(s, &s->txv, b, n);
	s->n_v++;
}

static void on_audio(struct sess *s, const uint8_t *p, size_t n)
{
	uint8_t b[1500];

	if (!s->a_on || n < 13 || n > sizeof b - WH_SRTP_TAG || (p[0] & 0x1f)) return;
	memcpy(b, p, n);
	rtp_head(b, s->pt_a, p[1] & 0x80, s->aseq++, aes_be32(p + 4), s->a_ssrc);
	send_rtp(s, &s->txa, b, n);
	s->n_a++;
}

static void rtsp_pump(struct sess *s)
{
	int r = (int)recv(s->rfd, s->rb + s->rn, sizeof s->rb - (size_t)s->rn, 0);

	if (r == 0 || (r < 0 && errno != EAGAIN && errno != EINTR)) { LOG("the RTSP source of viewer %s closed", s->id); sess_free(s); return; }
	if (r > 0) s->rn += r;
	for (;;) {
		if (s->rn < 4) break;
		if (s->rb[0] == '$') {
			unsigned len = wh_be16(s->rb + 2);

			if (len > sizeof s->rb - 4) { memmove(s->rb, s->rb + 1, (size_t)--s->rn); continue; }
			if ((unsigned)s->rn < 4 + len) break;
			if (s->state == S_RUN) {
				if (s->rb[1] == 0) on_video(s, s->rb + 4, len);
				else if (s->rb[1] == 2) on_audio(s, s->rb + 4, len);
			}
			memmove(s->rb, s->rb + 4 + len, (size_t)s->rn - 4 - len);
			s->rn -= (int)(4 + len);
		} else {			/* a stray RTSP response or noise: skip to the next frame */
			int i = 1;

			while (i < s->rn && s->rb[i] != '$') i++;
			memmove(s->rb, s->rb + i, (size_t)(s->rn - i));
			s->rn -= i;
		}
	}
}

/* ---- DTLS handshake and run ---- */
static void dtls_done(struct sess *s)
{
	mbedtls_dtls_srtp_info info;
	const mbedtls_x509_crt *pc = mbedtls_ssl_get_peer_cert(&s->ssl);
	char fp[100];
	uint8_t seed[64], km[60];

	mbedtls_ssl_get_dtls_srtp_negotiation_result(&s->ssl, &info);
	if (info.chosen_dtls_srtp_profile != MBEDTLS_TLS_SRTP_AES128_CM_HMAC_SHA1_80) { LOG("no SRTP profile agreed"); sess_free(s); return; }
	if (!pc) { LOG("the browser sent no certificate"); sess_free(s); return; }
	fp_text(pc->raw.p, pc->raw.len, fp, sizeof fp);
	if (strcasecmp(fp, s->ofp)) { LOG("DTLS certificate does not match the offer's fingerprint"); sess_free(s); return; }
	if (!s->have_keys || s->prf != MBEDTLS_SSL_TLS_PRF_SHA256) { LOG("keys not exported (prf %d)", s->prf); sess_free(s); return; }
	memcpy(seed, s->cr, 32); memcpy(seed + 32, s->sr, 32);
	if (prf256(s->ms, 48, "EXTRACTOR-dtls_srtp", seed, 64, km, sizeof km)) { sess_free(s); return; }
	/* RFC 5764 4.2: client key, server key, client salt, server salt; we are the server */
	srtp_init(&s->txv, km + 16, km + 32 + 14);
	srtp_init(&s->txa, km + 16, km + 32 + 14);
	memset(s->ms, 0, sizeof s->ms); memset(km, 0, sizeof km);
	if (rtsp_play(s)) { LOG("RTSP PLAY failed"); sess_free(s); return; }
	s->state = S_RUN;
	LOG("viewer %s: DTLS-SRTP up, streaming", s->id);
}

static void dtls_drive(struct sess *s)
{
	if (s->state == S_HS) {
		int r = mbedtls_ssl_handshake(&s->ssl);

		if (r == 0) dtls_done(s);
		else if (r != MBEDTLS_ERR_SSL_WANT_READ && r != MBEDTLS_ERR_SSL_WANT_WRITE) {
			LOG("viewer %s: DTLS handshake failed (-0x%x)", s->id, -r);
			sess_free(s);
		}
	} else if (s->state == S_RUN) {
		unsigned char b[64];
		int r = mbedtls_ssl_read(&s->ssl, b, sizeof b);

		if (r == MBEDTLS_ERR_SSL_PEER_CLOSE_NOTIFY || r == MBEDTLS_ERR_SSL_FATAL_ALERT_MESSAGE) sess_free(s);
	}
}

static struct sess *by_addr(const struct sockaddr_in *a)
{
	int i;

	for (i = 0; i < MAXS; i++) {
		struct sess *s = &G.s[i];

		if (s->state != S_FREE && s->have_peer && s->peer.sin_addr.s_addr == a->sin_addr.s_addr && s->peer.sin_port == a->sin_port) return s;
	}
	return NULL;
}

static void on_stun(const uint8_t *b, size_t n, const struct sockaddr_in *from)
{
	struct stun_msg m;
	uint8_t out[80];
	const uint8_t *c;
	size_t ul, rn;
	int i;

	if (stun_parse(b, n, &m) || m.type != 0x0001 || !m.user) return;
	c = memchr(m.user, ':', m.user_len);
	ul = c ? (size_t)(c - m.user) : m.user_len;
	for (i = 0; i < MAXS; i++) {
		struct sess *s = &G.s[i];

		if (s->state == S_FREE || strlen(s->lufrag) != ul || memcmp(s->lufrag, m.user, ul)) continue;
		if (!stun_check_integrity(b, &m, &s->ik)) return;
		rn = stun_binding_response(out, m.tid, ntohl(from->sin_addr.s_addr), ntohs(from->sin_port), &s->ik);
		sendto(G.udp, out, rn, MSG_DONTWAIT, (const struct sockaddr *)from, sizeof *from);
		if (!s->have_peer || s->peer.sin_addr.s_addr != from->sin_addr.s_addr || s->peer.sin_port != from->sin_port) {
			s->peer = *from; s->have_peer = 1;
			DBG("viewer %s: peer %s:%u", s->id, inet_ntoa(from->sin_addr), ntohs(from->sin_port));
		}
		s->last = now_ms();
		return;
	}
}

static int on_udp(void)
{
	uint8_t b[1600];
	struct sockaddr_in from;
	socklen_t fl = sizeof from;
	int n = (int)recvfrom(G.udp, b, sizeof b, MSG_DONTWAIT, (struct sockaddr *)&from, &fl);
	struct sess *s;

	if (n < 1) return 0;
	if (!wh_nets_ok(&nets, ntohl(from.sin_addr.s_addr))) return 1;	/* NET_LAN_ONLY: outside the allowed networks */
	if (b[0] < 4) { on_stun(b, (size_t)n, &from); return 1; }
	s = by_addr(&from);
	if (!s) return 1;
	/* only an ICE consent check with the right MESSAGE-INTEGRITY (on_stun) keeps a viewer alive (RFC 7675): a DTLS or
	 * SRTCP datagram is not authenticated here, and one sent from a spoofed address kept a dead viewer's slot forever */
	if (b[0] >= 20 && b[0] <= 63) {
		if (s->state == S_HS) {
			int r = s->ch_done ? (b[0] == 22 && n > 25 && b[13] == 1 ? 1 : 0) : wh_chello_feed(&s->ch, b, (size_t)n, s->in, sizeof s->in);

			if (r < 0) { LOG("viewer %s: bad ClientHello fragments", s->id); sess_free(s); return 1; }
			if (r == 1) return 1;
			if (r > 1) { DBG("viewer %s: ClientHello of %d bytes rebuilt from fragments", s->id, r - 25); s->in_len = r; s->ch_done = 1; dtls_drive(s); return 1; }
			if (b[0] == 22 && n > 25 && b[13] == 1) s->ch_done = 1;
		}
		s->in_len = n; memcpy(s->in, b, (size_t)n);
		dtls_drive(s);
	}	/* 128-191: SRTCP receiver reports, not used */
	return 1;
}

/* ---- HTTP (loopback) ---- */
static void http_reply(int fd, int code, const char *reason, const char *hdrs, const char *body)
{
	char h[400];
	int n = snprintf(h, sizeof h, "HTTP/1.1 %d %s\r\n%sContent-Length: %u\r\nConnection: close\r\n\r\n", code, reason,
			 hdrs ? hdrs : "", (unsigned)strlen(body));

	(void)!write(fd, h, (size_t)n);
	(void)!write(fd, body, strlen(body));
}

static int iface_ip(char *dst, size_t n)
{
	char names[48], *t, *sv = NULL;
	int fd = socket(AF_INET, SOCK_DGRAM, 0), ok = 0;

	if (fd < 0) return -1;
	snprintf(names, sizeof names, "%s", G.iface);
	for (t = strtok_r(names, ",", &sv); t && !ok; t = strtok_r(NULL, ",", &sv)) {
		struct ifreq r;

		memset(&r, 0, sizeof r);
		snprintf(r.ifr_name, sizeof r.ifr_name, "%s", t);
		if (!ioctl(fd, SIOCGIFADDR, &r)) {
			inet_ntop(AF_INET, &((struct sockaddr_in *)&r.ifr_addr)->sin_addr, dst, (socklen_t)n);
			ok = strcmp(dst, "0.0.0.0") != 0;
		}
	}
	close(fd);
	return ok ? 0 : -1;
}

static void sweep(void)
{
	uint64_t t = now_ms();
	int i;

	for (i = 0; i < MAXS; i++) {
		struct sess *s = &G.s[i];

		if (s->state == S_FREE) continue;
		/* consent: 30 s without an authenticated check (RFC 7675; Firefox checks every 4-6 s, a lost datagram or two on
		 * the Wi-Fi must not drop a viewer); a viewer that never answered STUN goes after 15 s. The page itself sends
		 * the stop request when it closes or hides the video, so this only frees the slot of a vanished viewer. */
		if ((s->state == S_HS && t - s->t0 > 30000) || (s->have_peer && t - s->last > 30000) ||
		    (!s->have_peer && t - s->t0 > 15000)) {
			LOG("viewer %s: no sign of life (%s)", s->id, s->state == S_HS ? "handshake" : "consent");
			sess_free(s);
		}
	}
}

static int ssl_prepare(struct sess *s)
{
	int r;

	mbedtls_ssl_config_init(&s->conf); mbedtls_ssl_init(&s->ssl);
	s->ssl_on = 1;
	if ((r = mbedtls_ssl_config_defaults(&s->conf, MBEDTLS_SSL_IS_SERVER, MBEDTLS_SSL_TRANSPORT_DATAGRAM, MBEDTLS_SSL_PRESET_DEFAULT))) return r;
	mbedtls_ssl_conf_rng(&s->conf, mbedtls_ctr_drbg_random, &G.drbg);
	if ((r = mbedtls_ssl_conf_own_cert(&s->conf, &G.crt, &G.key))) return r;
	mbedtls_ssl_conf_authmode(&s->conf, MBEDTLS_SSL_VERIFY_OPTIONAL);	/* the browser's self-signed certificate is checked by fingerprint */
	mbedtls_ssl_conf_min_version(&s->conf, MBEDTLS_SSL_MAJOR_VERSION_3, MBEDTLS_SSL_MINOR_VERSION_3);
	mbedtls_ssl_conf_ciphersuites(&s->conf, SUITES);
	mbedtls_ssl_conf_dtls_cookies(&s->conf, NULL, NULL, NULL);		/* the address is already proved by the STUN checks */
	mbedtls_ssl_conf_handshake_timeout(&s->conf, 500, 4000);
	if ((r = mbedtls_ssl_conf_dtls_srtp_protection_profiles(&s->conf, PROFILES))) return r;
	mbedtls_ssl_conf_export_keys_ext_cb(&s->conf, export_keys, s);
	if ((r = mbedtls_ssl_setup(&s->ssl, &s->conf))) return r;
	mbedtls_ssl_set_bio(&s->ssl, s, bio_send, bio_recv, NULL);
	mbedtls_ssl_set_timer_cb(&s->ssl, s, timer_set, timer_get);
	mbedtls_ssl_set_mtu(&s->ssl, 1200);
	return 0;
}

static void whep_post(int fd, const char *body)
{
	static struct sdp_offer of;
	static char ans[3000];
	struct sdp_answer_in ai;
	struct sess *s = NULL;
	char ip[20], plid[8] = "";
	int i, vm = -1, am = -1, vi, ai_, has_audio = 0, code, nact = 0;

	sweep();
	for (i = 0; i < MAXS; i++) { if (G.s[i].state != S_FREE) nact++; else if (!s) s = &G.s[i]; }
	if (nact >= G.max || !s) { http_reply(fd, 429, "Too Many Requests", NULL, "viewer limit reached\n"); return; }
	if (iface_ip(ip, sizeof ip)) { http_reply(fd, 503, "Service Unavailable", NULL, "no LAN address\n"); return; }
	if (sdp_parse_offer(body, &of)) { http_reply(fd, 400, "Bad Request", NULL, "not an SDP offer with ICE and DTLS\n"); return; }
	for (i = 0; i < of.nm; i++) {
		if (vm < 0 && !strcmp(of.m[i].kind, "video") && sdp_pick_h264(&of.m[i], NULL) >= 0) vm = i;
		if (am < 0 && !strcmp(of.m[i].kind, "audio") && sdp_pick_pcma(&of.m[i]) >= 0) am = i;
	}
	if (vm < 0) { http_reply(fd, 415, "Unsupported Media Type", NULL, "the offer has no H.264 (packetization-mode=1)\n"); return; }

	memset(s, 0, sizeof *s);
	s->rfd = -1; s->state = S_HS;
	code = rtsp_open(s, G.audio && am >= 0, plid, sizeof plid, &has_audio);
	if (code) {
		sess_free(s);
		http_reply(fd, code, code == 415 ? "Unsupported Media Type" : "Service Unavailable", NULL, code == 415 ? "the selected stream is not H.264\n" : "no video source\n");
		return;
	}
	s->state = S_HS;			/* sess_free above resets only on failure */
	s->a_on = G.audio && am >= 0 && has_audio;
	vi = sdp_pick_h264(&of.m[vm], plid);
	ai_ = s->a_on ? sdp_pick_pcma(&of.m[am]) : -1;
	rnd_text(s->id, 16, "0123456789abcdef");
	rnd_text(s->lufrag, 8, "abcdefghijklmnopqrstuvwxyz0123456789");
	rnd_text(s->lpwd, 24, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789");
	hmac_sha1_key(&s->ik, (const uint8_t *)s->lpwd, strlen(s->lpwd));
	snprintf(s->ofp, sizeof s->ofp, "%s", of.fp);
	s->pt_v = of.m[vm].pts[vi].pt;
	s->pt_a = ai_ >= 0 ? of.m[am].pts[ai_].pt : 8;
	rnd(&s->v_ssrc, 4); rnd(&s->a_ssrc, 4);
	if (s->a_ssrc == s->v_ssrc) s->a_ssrc++;
	rnd(&s->vseq, 2); rnd(&s->aseq, 2);
	s->t0 = s->last = now_ms();
	if (ssl_prepare(s)) { LOG("DTLS setup failed"); sess_free(s); http_reply(fd, 500, "Internal Server Error", NULL, "DTLS setup failed\n"); return; }
	memset(&ai, 0, sizeof ai);
	ai.offer = &of; ai.ufrag = s->lufrag; ai.pwd = s->lpwd; ai.fp = G.fp; ai.ip = ip; ai.port = G.udp_port;
	ai.v_media = vm; ai.v_idx = vi; ai.a_media = s->a_on ? am : -1; ai.a_idx = ai_;
	ai.v_ssrc = s->v_ssrc; ai.a_ssrc = s->a_ssrc; ai.sess_id = (unsigned long)(now_ms() / 1000);
	if (!sdp_answer(ans, sizeof ans, &ai)) { sess_free(s); http_reply(fd, 500, "Internal Server Error", NULL, "answer too long\n"); return; }
	{
		char h[160];

		snprintf(h, sizeof h, "Content-Type: application/sdp\r\nLocation: /whep/%s\r\n", s->id);
		http_reply(fd, 201, "Created", h, ans);
	}
	LOG("viewer %s: offer accepted (%s stream, H.264 pt %d%s)", s->id, G.main_stream ? "main" : "sub", s->pt_v, s->a_on ? ", PCMA" : "");
}

/* largest SDP offer accepted (whep.cgi has the same limit): Chrome 157 sends 7607 bytes for video + audio recvonly with
 * its host candidates, Firefox about as much; 6000 refused them with 413 and the page fell back to MP4 (rc28). */
#define WH_MAX_OFFER 12000

static void http_handle(int fd)
{
	char rq[16384], method[8], path[100];
	struct timeval tv = { 2, 0 };
	int n = 0, hl = -1;
	size_t cl = 0;
	char *p, *c;

	setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
	while (n < (int)sizeof rq - 1) {
		int r = (int)recv(fd, rq + n, sizeof rq - 1 - (size_t)n, 0);

		if (r <= 0) break;
		n += r; rq[n] = 0;
		if ((p = strstr(rq, "\r\n\r\n"))) { hl = (int)(p - rq) + 4; break; }
	}
	if (hl < 0) { http_reply(fd, 400, "Bad Request", NULL, "bad request\n"); return; }
	c = strcasestr(rq, "\nContent-Length:");
	if (c && c < rq + hl) cl = (size_t)atoi(c + 16);
	if (cl > WH_MAX_OFFER || (size_t)hl + cl >= sizeof rq) { http_reply(fd, 413, "Payload Too Large", NULL, "too large\n"); return; }
	while (n - hl < (int)cl) {
		int r = (int)recv(fd, rq + n, sizeof rq - 1 - (size_t)n, 0);

		if (r <= 0) break;
		n += r; rq[n] = 0;
	}
	if (sscanf(rq, "%7s %99s", method, path) != 2) { http_reply(fd, 400, "Bad Request", NULL, "bad request\n"); return; }
	if (!strcmp(method, "POST") && !strcmp(path, "/whep")) whep_post(fd, rq + hl);
	else if (!strcmp(method, "DELETE") && !strncmp(path, "/whep/", 6)) {
		int i, found = 0;

		for (i = 0; i < MAXS; i++) if (G.s[i].state != S_FREE && !strcmp(G.s[i].id, path + 6)) { sess_free(&G.s[i]); found = 1; }
		if (found) http_reply(fd, 200, "OK", NULL, "");
		else http_reply(fd, 404, "Not Found", NULL, "no such viewer\n");
	} else if (!strcmp(method, "GET") && !strcmp(path, "/status")) {
		char j[160];
		int i, v = 0;

		sweep();
		for (i = 0; i < MAXS; i++) if (G.s[i].state == S_RUN) v++;
		snprintf(j, sizeof j, "{\"viewers\":%d,\"max\":%d,\"stream\":\"%s\",\"audio\":%d}\n", v, G.max, G.main_stream ? "main" : "sub", G.audio);
		http_reply(fd, 200, "OK", "Content-Type: application/json\r\n", j);
	} else http_reply(fd, 404, "Not Found", NULL, "not found\n");
}

static int listen_on(int type, unsigned port, uint32_t addr)
{
	struct sockaddr_in a;
	int fd = socket(AF_INET, type, 0), one = 1;

	if (fd < 0) return -1;
	setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
	memset(&a, 0, sizeof a);
	a.sin_family = AF_INET; a.sin_port = htons((uint16_t)port); a.sin_addr.s_addr = htonl(addr);
	if (bind(fd, (struct sockaddr *)&a, sizeof a) || (type == SOCK_STREAM && listen(fd, 4))) { close(fd); return -1; }
	return fd;
}

static void on_term(int sig) { (void)sig; G.quit = 1; }

static void read_pw(void)
{
	char pw[128] = "", plain[200];
	FILE *f = fopen(G.pwfile, "r");
	static const char *b64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
	size_t n, i, o = 0;

	G.auth[0] = 0;
	if (!f) return;
	if (fgets(pw, sizeof pw, f)) pw[strcspn(pw, "\r\n")] = 0;
	fclose(f);
	if (!pw[0]) return;			/* no password: tc100_rtsp is open */
	n = (size_t)snprintf(plain, sizeof plain, "%s:%s", G.ruser, pw);
	for (i = 0; i < n; i += 3) {
		uint32_t v = (uint32_t)(uint8_t)plain[i] << 16 | (i + 1 < n ? (uint32_t)(uint8_t)plain[i + 1] << 8 : 0) | (i + 2 < n ? (uint8_t)plain[i + 2] : 0);

		G.auth[o++] = b64[v >> 18 & 63]; G.auth[o++] = b64[v >> 12 & 63];
		G.auth[o++] = i + 1 < n ? b64[v >> 6 & 63] : '='; G.auth[o++] = i + 2 < n ? b64[v & 63] : '=';
	}
	G.auth[o] = 0;
	memset(pw, 0, sizeof pw); memset(plain, 0, sizeof plain);
}

int main(int argc, char **argv)
{
	int o, i;

	G.http_port = 8889; G.udp_port = 8189; G.max = 2; G.audio = 1; G.rtsp_port = 554;
	snprintf(G.iface, sizeof G.iface, "wlan0,eth0"); snprintf(G.cdir, sizeof G.cdir, "/mnt/config");
	snprintf(G.pwfile, sizeof G.pwfile, "/mnt/config/user.pwd"); snprintf(G.ruser, sizeof G.ruser, "root");
	while ((o = getopt(argc, argv, "i:p:u:s:m:a:r:U:w:c:d")) != -1) {
		switch (o) {
		case 'i': snprintf(G.iface, sizeof G.iface, "%s", optarg); break;
		case 'p': G.http_port = (unsigned)atoi(optarg); break;
		case 'u': G.udp_port = (unsigned)atoi(optarg); break;
		case 's': G.main_stream = !strcmp(optarg, "main"); break;
		case 'm': G.max = atoi(optarg); break;
		case 'a': G.audio = atoi(optarg) != 0; break;
		case 'r': G.rtsp_port = atoi(optarg); break;
		case 'U': snprintf(G.ruser, sizeof G.ruser, "%s", optarg); break;
		case 'w': snprintf(G.pwfile, sizeof G.pwfile, "%s", optarg); break;
		case 'c': snprintf(G.cdir, sizeof G.cdir, "%s", optarg); break;
		case 'd': G.debug = 1; break;
		default: fprintf(stderr, "usage: tc100-whep [-i if[,if]] [-p http] [-u udp] [-s sub|main] [-m max] [-a 0|1] [-r rtsp] [-U user] [-w pwfile] [-c dir] [-d]\n"); return 2;
		}
	}
	if (G.max < 1) G.max = 1;
	if (G.max > MAXS) G.max = MAXS;
	for (i = 0; i < MAXS; i++) G.s[i].rfd = -1;
	signal(SIGPIPE, SIG_IGN); signal(SIGTERM, on_term); signal(SIGINT, on_term);
	mbedtls_entropy_init(&G.ent); mbedtls_ctr_drbg_init(&G.drbg);
	if (mbedtls_ctr_drbg_seed(&G.drbg, mbedtls_entropy_func, &G.ent, (const unsigned char *)"tc100-whep", 10)) { LOG("no entropy"); return 1; }
	if (cert_init()) return 1;
	fp_text(G.crt.raw.p, G.crt.raw.len, G.fp, sizeof G.fp);
	G.http = listen_on(SOCK_STREAM, G.http_port, INADDR_LOOPBACK);
	G.udp = listen_on(SOCK_DGRAM, G.udp_port, INADDR_ANY);
	if (G.http < 0 || G.udp < 0) { LOG("cannot listen (http %u on loopback, udp %u): %s", G.http_port, G.udp_port, strerror(errno)); return 1; }
	read_pw();
	wh_nets_parse(&nets, getenv("TC100_NET_ALLOW"));
	LOG("udp %u: %s", G.udp_port, nets.n ? "datagrams from the allowed networks only (NET_LAN_ONLY)" : "no network filter");
	LOG("ready: WHEP on 127.0.0.1:%u, ICE-lite on udp %u (%s), %s stream, up to %d viewers, certificate %.23s...", G.http_port, G.udp_port, G.iface,
	    G.main_stream ? "main" : "sub", G.max, G.fp);
	while (!G.quit) {
		struct pollfd pf[2 + MAXS];
		int np = 2, idx[MAXS], hs = 0;

		pf[0].fd = G.http; pf[0].events = POLLIN; pf[1].fd = G.udp; pf[1].events = POLLIN;
		for (i = 0; i < MAXS; i++) {
			struct sess *s = &G.s[i];

			idx[i] = -1;
			if (s->state == S_HS) hs = 1;
			if (s->state == S_RUN && s->rfd >= 0) { pf[np].fd = s->rfd; pf[np].events = POLLIN; idx[i] = np++; }
		}
		if (poll(pf, (nfds_t)np, hs ? 50 : 1000) < 0 && errno != EINTR) break;
		if (pf[0].revents & POLLIN) {
			int c = accept(G.http, NULL, NULL);

			if (c >= 0) { read_pw(); http_handle(c); close(c); }
		}
		if (pf[1].revents & POLLIN) for (i = 0; i < 32 && on_udp(); i++) ;
		for (i = 0; i < MAXS; i++) {
			struct sess *s = &G.s[i];

			if (idx[i] >= 0 && s->state == S_RUN && (pf[idx[i]].revents & (POLLIN | POLLHUP | POLLERR))) rtsp_pump(s);
			if (s->state == S_HS) dtls_drive(s);	/* retransmissions */
		}
		sweep();
	}
	for (i = 0; i < MAXS; i++) sess_free(&G.s[i]);
	LOG("stopped");
	return 0;
}
