/* tc100_httpsd.c: lightweight non-blocking TLS 1.2 reverse proxy for BusyBox httpd + httpfront.
 * Designed for low CPU overhead on ARM926EJ-S (480 MHz, no AES hardware):
 *   - Single-process poll() event loop, zero-malloc connection slots
 *   - HTTP/1.1 Keep-Alive (+ chunked framing for CGI responses without Content-Length) so dashboards only handshake once
 *   - TLS session tickets (RFC 5077) + 32-entry server session cache across reconnects
 *   - ChaCha20-Poly1305 preferred before AES-128-GCM, X25519 + ECDSA P-256 self-signed cert cached in /mnt/config
 *   - Drops root to uid:gid (-D) after loading https-key.pem and binding port 443; nice(+5) yields CPU to tc100_rtsp. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <arpa/inet.h>

#include "mbedtls/ctr_drbg.h"
#include "mbedtls/ecp.h"
#include "mbedtls/entropy.h"
#include "mbedtls/oid.h"
#include "mbedtls/pk.h"
#include "mbedtls/ssl.h"
#include "mbedtls/x509_crt.h"
#ifdef MBEDTLS_PSA_CRYPTO_C
#include "psa/crypto.h"
#endif
#ifdef MBEDTLS_SSL_SESSION_TICKETS
#include "mbedtls/ssl_ticket.h"
#endif
#ifdef MBEDTLS_SSL_CACHE_C
#include "mbedtls/ssl_cache.h"
#endif

#include "httpsd_http.h"

#ifndef MSG_NOSIGNAL
#define MSG_NOSIGNAL 0
#endif

enum {
	S_FREE = 0,
	S_HS_WAIT,
	S_HS,
	S_REQ_HDR,
	S_BE_CONN,
	S_REQ_SEND,
	S_REQ_BODY,
	S_RESP_HDR,
	S_RESP_BODY,
	S_CLOSE
};

struct conn {
	int state;
	int cfd, bfd;
	uint32_t ip;
	char ip_str[20];
	uint64_t t_last, t_idle;
	int ssl_on, hs_counted, hs_want;
	mbedtls_ssl_context ssl;

	char ibuf[HTTPSD_MAX_HDR + 1024];
	size_t ibuf_len, req_hdr_len, req_body_rem;
	struct httpsd_req req;

	char obuf[HTTPSD_MAX_HDR + 4096];
	size_t obuf_len, resp_hdr_len, resp_body_rem;
	struct httpsd_resp resp;
	int body_mode;
	int be_eof;
	int chunk_done;

	char txbuf[HTTPSD_MAX_HDR + 4608];
	size_t tx_off, tx_len;
	int req_sent_off;
	int req_sent_len;
};

static struct {
	int lfd, debug, lockout_on, max_conns, nice_val;
	unsigned port, be_port;
	char cdir[128], hostname[80], ip_str[32];
	struct httpsd_nets nets;
	struct httpsd_lockout lockout;
	mbedtls_entropy_context ent;
	mbedtls_ctr_drbg_context drbg;
	mbedtls_x509_crt crt;
	mbedtls_pk_context key;
	mbedtls_ssl_config conf;
#ifdef MBEDTLS_SSL_SESSION_TICKETS
	mbedtls_ssl_ticket_context ticket;
#endif
#ifdef MBEDTLS_SSL_CACHE_C
	mbedtls_ssl_cache_context cache;
#endif
	struct conn conns[8];
	unsigned long hs_total, hs_resumed, req_total;
	volatile sig_atomic_t quit;
} G;

static const int CIPHERS[] = {
#if defined(MBEDTLS_CHACHAPOLY_C) && defined(MBEDTLS_TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256)
	MBEDTLS_TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256,
#endif
	MBEDTLS_TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256,
	0
};

#if defined(MBEDTLS_SSL_IANA_TLS_GROUP_X25519) && defined(MBEDTLS_ECP_DP_CURVE25519_ENABLED) && defined(MBEDTLS_SSL_IANA_TLS_GROUP_SECP256R1)
static const uint16_t GROUPS[] = {
	MBEDTLS_SSL_IANA_TLS_GROUP_X25519,
	MBEDTLS_SSL_IANA_TLS_GROUP_SECP256R1,
	0
};
#endif

static uint64_t now_ms(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return (uint64_t)t.tv_sec * 1000ULL + (uint64_t)t.tv_nsec / 1000000ULL;
}

static void logf_(const char *fmt, ...)
{
	va_list ap;
	char b[320];
	int n;

	va_start(ap, fmt);
	n = vsnprintf(b, sizeof b - 1, fmt, ap);
	va_end(ap);
	if (n < 0) return;
	if (n > (int)sizeof b - 2) n = (int)sizeof b - 2;
	b[n++] = '\n';
	(void)!write(2, b, (size_t)n);
}
#define LOG(...) logf_("tc100-httpsd: " __VA_ARGS__)
#define DBG(...) do { if (G.debug) logf_("tc100-httpsd: " __VA_ARGS__); } while (0)

static void on_term(int sig) { (void)sig; G.quit = 1; }

static void set_nonblock(int fd)
{
	int fl = fcntl(fd, F_GETFL, 0);

	if (fl >= 0) (void)fcntl(fd, F_SETFL, fl | O_NONBLOCK);
}

static void set_nodelay(int fd)
{
	int one = 1;

	(void)setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
}

static int bio_send(void *ctx, const unsigned char *buf, size_t len)
{
	int fd = *(int *)ctx;
	ssize_t r = send(fd, buf, len, MSG_NOSIGNAL);

	if (r < 0) {
		if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)
			return MBEDTLS_ERR_SSL_WANT_WRITE;
		return MBEDTLS_ERR_SSL_INTERNAL_ERROR;
	}
	return (int)r;
}

static int bio_recv(void *ctx, unsigned char *buf, size_t len)
{
	int fd = *(int *)ctx;
	ssize_t r = recv(fd, buf, len, 0);

	if (r < 0) {
		if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)
			return MBEDTLS_ERR_SSL_WANT_READ;
		return MBEDTLS_ERR_SSL_INTERNAL_ERROR;
	}
	if (r == 0) return 0;
	return (int)r;
}

static int write_atomic(const char *path, const char *data, mode_t mode)
{
	char tmp[160];
	int fd;
	size_t n = strlen(data);

	snprintf(tmp, sizeof tmp, "%s.tmp", path);
	fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC, mode);
	if (fd < 0) return -1;
	if (write(fd, data, n) != (ssize_t)n) { close(fd); unlink(tmp); return -1; }
	fsync(fd);
	close(fd);
	if (chmod(tmp, mode) < 0) { unlink(tmp); return -1; }
	return rename(tmp, path);
}

static int cert_init(void)
{
	char kp[160], cp[160], subj[128];
	static char kpem[1024], cpem[2048];
	mbedtls_x509write_cert w;
	mbedtls_pk_context k;
	unsigned char serial[8], san[512];
	int slen, r;

	snprintf(kp, sizeof kp, "%s/https-key.pem", G.cdir);
	snprintf(cp, sizeof cp, "%s/https-cert.pem", G.cdir);
	mbedtls_pk_init(&G.key);
	mbedtls_x509_crt_init(&G.crt);
	if (!mbedtls_pk_parse_keyfile(&G.key, kp, NULL, mbedtls_ctr_drbg_random, &G.drbg) &&
	    !mbedtls_x509_crt_parse_file(&G.crt, cp)) {
		return 0;
	}
	mbedtls_pk_free(&G.key);
	mbedtls_x509_crt_free(&G.crt);
	mbedtls_pk_init(&G.key);
	mbedtls_x509_crt_init(&G.crt);

	mbedtls_pk_init(&k);
	if ((r = mbedtls_pk_setup(&k, mbedtls_pk_info_from_type(MBEDTLS_PK_ECKEY))) ||
	    (r = mbedtls_ecp_gen_key(MBEDTLS_ECP_DP_SECP256R1, mbedtls_pk_ec(k), mbedtls_ctr_drbg_random, &G.drbg))) {
		LOG("ECDSA keygen failed (-0x%x)", -r);
		mbedtls_pk_free(&k);
		return -1;
	}
	mbedtls_ctr_drbg_random(&G.drbg, serial, sizeof serial);
	serial[0] &= 0x7f;

	snprintf(subj, sizeof subj, "CN=%s", G.hostname[0] ? G.hostname : "tc100");
	slen = httpsd_build_san_der(G.hostname, G.ip_str, san, sizeof san);

	mbedtls_x509write_crt_init(&w);
	mbedtls_x509write_crt_set_md_alg(&w, MBEDTLS_MD_SHA256);
	mbedtls_x509write_crt_set_subject_key(&w, &k);
	mbedtls_x509write_crt_set_issuer_key(&w, &k);
	mbedtls_x509write_crt_set_version(&w, MBEDTLS_X509_CRT_VERSION_3);
	r = mbedtls_x509write_crt_set_subject_name(&w, subj) ||
	    mbedtls_x509write_crt_set_issuer_name(&w, subj) ||
	    mbedtls_x509write_crt_set_serial_raw(&w, serial, sizeof serial) ||
	    mbedtls_x509write_crt_set_validity(&w, "20200101000000", "20500101000000") ||
	    mbedtls_x509write_crt_set_basic_constraints(&w, 1, 0);
	if (!r && slen > 0) {
		r = mbedtls_x509write_crt_set_extension(&w, MBEDTLS_OID_SUBJECT_ALT_NAME,
							MBEDTLS_OID_SIZE(MBEDTLS_OID_SUBJECT_ALT_NAME),
							0, san, (size_t)slen);
	}
	if (!r) r = mbedtls_x509write_crt_pem(&w, (unsigned char *)cpem, sizeof cpem, mbedtls_ctr_drbg_random, &G.drbg);
	if (!r) r = mbedtls_pk_write_key_pem(&k, (unsigned char *)kpem, sizeof kpem);
	mbedtls_x509write_crt_free(&w);
	mbedtls_pk_free(&k);
	if (r) { LOG("certificate write failed (-0x%x)", -r); return -1; }

	if (write_atomic(kp, kpem, 0600) || write_atomic(cp, cpem, 0644)) {
		LOG("warning: could not save certificate in %s", G.cdir);
	} else {
		LOG("generated persistent ECDSA P-256 certificate in %s", G.cdir);
	}
	if (mbedtls_pk_parse_key(&G.key, (unsigned char *)kpem, strlen(kpem) + 1, NULL, 0, mbedtls_ctr_drbg_random, &G.drbg) ||
	    mbedtls_x509_crt_parse(&G.crt, (unsigned char *)cpem, strlen(cpem) + 1)) {
		LOG("generated certificate failed self-parse");
		memset(kpem, 0, sizeof kpem);
		return -1;
	}
	memset(kpem, 0, sizeof kpem);
	return 0;
}

static int tls_init(void)
{
	int r;

	mbedtls_ssl_config_init(&G.conf);
	if ((r = mbedtls_ssl_config_defaults(&G.conf, MBEDTLS_SSL_IS_SERVER,
					     MBEDTLS_SSL_TRANSPORT_STREAM,
					     MBEDTLS_SSL_PRESET_DEFAULT))) {
		LOG("ssl_config_defaults failed (-0x%x)", -r);
		return -1;
	}
	mbedtls_ssl_conf_min_tls_version(&G.conf, MBEDTLS_SSL_VERSION_TLS1_2);
	mbedtls_ssl_conf_max_tls_version(&G.conf, MBEDTLS_SSL_VERSION_TLS1_2);
	mbedtls_ssl_conf_rng(&G.conf, mbedtls_ctr_drbg_random, &G.drbg);
	mbedtls_ssl_conf_ciphersuites(&G.conf, CIPHERS);
#if defined(MBEDTLS_SSL_IANA_TLS_GROUP_X25519) && defined(MBEDTLS_ECP_DP_CURVE25519_ENABLED) && defined(MBEDTLS_SSL_IANA_TLS_GROUP_SECP256R1)
	mbedtls_ssl_conf_groups(&G.conf, GROUPS);
#endif
	if ((r = mbedtls_ssl_conf_own_cert(&G.conf, &G.crt, &G.key))) {
		LOG("ssl_conf_own_cert failed (-0x%x)", -r);
		return -1;
	}
#ifdef MBEDTLS_SSL_SESSION_TICKETS
	mbedtls_ssl_ticket_init(&G.ticket);
	if ((r = mbedtls_ssl_ticket_setup(&G.ticket, mbedtls_ctr_drbg_random, &G.drbg,
					  MBEDTLS_CIPHER_AES_128_GCM, 86400)) == 0) {
		mbedtls_ssl_conf_session_tickets_cb(&G.conf, mbedtls_ssl_ticket_write,
						    mbedtls_ssl_ticket_parse, &G.ticket);
	}
#endif
#ifdef MBEDTLS_SSL_CACHE_C
	mbedtls_ssl_cache_init(&G.cache);
	mbedtls_ssl_cache_set_max_entries(&G.cache, 32);
	mbedtls_ssl_cache_set_timeout(&G.cache, 3600);
	mbedtls_ssl_conf_session_cache(&G.conf, &G.cache, mbedtls_ssl_cache_get, mbedtls_ssl_cache_set);
#endif
	return 0;
}

static int priv_drop(const char *spec)
{
	unsigned long v[2] = { 0, 0 };
	int k, n;

	if (!spec) return 0;
	for (k = 0; k < 2; k++) {
		for (n = 0; *spec >= '0' && *spec <= '9' && n < 6; n++) v[k] = v[k] * 10 + (unsigned long)(*spec++ - '0');
		if (!n || (k == 0 && *spec++ != ':')) return -1;
	}
	if (*spec || !v[0] || !v[1] || v[0] > 65534 || v[1] > 65534) return -1;
	if (setgroups(0, NULL) || setgid((gid_t)v[1]) || setuid((uid_t)v[0])) return -1;
	if (getuid() != (uid_t)v[0] || geteuid() != (uid_t)v[0] || getgid() != (gid_t)v[1] || getegid() != (gid_t)v[1]) return -1;
	if (setuid(0) == 0) return -1;
	return 0;
}

static int listen_tcp(unsigned port)
{
	int fd = socket(AF_INET, SOCK_STREAM, 0), one = 1;
	struct sockaddr_in a;

	if (fd < 0) return -1;
	setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
	memset(&a, 0, sizeof a);
	a.sin_family = AF_INET;
	a.sin_port = htons((uint16_t)port);
	a.sin_addr.s_addr = htonl(INADDR_ANY);
	if (bind(fd, (struct sockaddr *)&a, sizeof a) < 0 || listen(fd, 16) < 0) {
		close(fd);
		return -1;
	}
	set_nonblock(fd);
	return fd;
}

static void conn_close_be(struct conn *c)
{
	if (c->bfd >= 0) { close(c->bfd); c->bfd = -1; }
}

static void conn_free(struct conn *c)
{
	conn_close_be(c);
	if (c->ssl_on) {
		mbedtls_ssl_free(&c->ssl);
		c->ssl_on = 0;
	}
	if (c->cfd >= 0) { close(c->cfd); c->cfd = -1; }
	c->state = S_FREE;
}

static void conn_reset_ka(struct conn *c, uint64_t now)
{
	size_t left = c->ibuf_len > c->req_hdr_len ? c->ibuf_len - c->req_hdr_len : 0;

	conn_close_be(c);
	if (left > 0) memmove(c->ibuf, c->ibuf + c->req_hdr_len, left);
	c->ibuf_len = left;
	c->req_hdr_len = 0;
	c->req_body_rem = 0;
	c->obuf_len = 0;
	c->resp_hdr_len = 0;
	c->resp_body_rem = 0;
	c->tx_off = 0;
	c->tx_len = 0;
	c->be_eof = 0;
	c->chunk_done = 0;
	c->t_last = now;
	c->t_idle = now;
	c->state = S_REQ_HDR;
}

static int send_http_err(struct conn *c, int code, const char *msg)
{
	int n = snprintf(c->txbuf, sizeof c->txbuf,
			 "HTTP/1.1 %d %s\r\nContent-Type: text/plain\r\nContent-Length: %zu\r\nConnection: close\r\n\r\n%s",
			 code, msg, strlen(msg), msg);
	if (n < 0 || (size_t)n >= sizeof c->txbuf) return -1;
	c->tx_off = 0;
	c->tx_len = (size_t)n;
	c->req.keepalive = 0;
	c->body_mode = HTTPSD_BODY_NONE;
	c->state = S_CLOSE;
	return 0;
}

/* Returns: 0 still sending, 1 all sent, -1 fatal error */
static int tls_flush(struct conn *c, uint64_t now)
{
	while (c->tx_off < c->tx_len) {
		int r = mbedtls_ssl_write(&c->ssl, (const unsigned char *)c->txbuf + c->tx_off, c->tx_len - c->tx_off);

		if (r > 0) {
			c->tx_off += (size_t)r;
			c->t_last = now;
		} else if (r == MBEDTLS_ERR_SSL_WANT_WRITE || r == MBEDTLS_ERR_SSL_WANT_READ) {
			return 0;
		} else {
			return -1;
		}
	}
	c->tx_off = 0;
	c->tx_len = 0;
	return 1;
}

static int active_handshakes(void)
{
	int i, n = 0;

	for (i = 0; i < G.max_conns; i++) if (G.conns[i].state == S_HS) n++;
	return n;
}

static void accept_clients(uint64_t now)
{
	for (;;) {
		struct sockaddr_in a;
		socklen_t al = sizeof a;
		int cfd = accept(G.lfd, (struct sockaddr *)&a, &al);
		uint32_t ip;
		int i, free_slot = -1, per_ip = 0;

		if (cfd < 0) break;
		ip = ntohl(a.sin_addr.s_addr);
		if (!httpsd_nets_allow(&G.nets, ip)) {
			close(cfd);
			continue;
		}
		if (G.lockout_on && httpsd_lockout_blocked(&G.lockout, ip, (uint64_t)time(NULL))) {
			close(cfd);
			continue;
		}
		for (i = 0; i < G.max_conns; i++) {
			if (G.conns[i].state == S_FREE && free_slot < 0) free_slot = i;
			else if (G.conns[i].state != S_FREE && G.conns[i].ip == ip) per_ip++;
		}
		if (free_slot < 0 || per_ip >= HTTPSD_PER_IP) {
			close(cfd);
			continue;
		}
		set_nonblock(cfd);
		set_nodelay(cfd);
		{
			struct conn *c = &G.conns[free_slot];

			memset(c, 0, sizeof *c);
			c->state = S_HS_WAIT;
			c->cfd = cfd;
			c->bfd = -1;
			c->ip = ip;
			inet_ntop(AF_INET, &a.sin_addr, c->ip_str, sizeof c->ip_str);
			c->t_last = now;
			c->t_idle = now;
			mbedtls_ssl_init(&c->ssl);
			if (mbedtls_ssl_setup(&c->ssl, &G.conf) != 0) {
				mbedtls_ssl_free(&c->ssl);
				close(cfd);
				c->state = S_FREE;
				continue;
			}
			mbedtls_ssl_set_bio(&c->ssl, &c->cfd, bio_send, bio_recv, NULL);
			c->ssl_on = 1;
			DBG("conn[%d] from %s", free_slot, c->ip_str);
		}
	}
}

static void start_backend_connect(struct conn *c, uint64_t now)
{
	int fd = socket(AF_INET, SOCK_STREAM, 0);
	struct sockaddr_in a;
	int r, rw;

	if (fd < 0) { send_http_err(c, 502, "Bad Gateway"); return; }
	set_nonblock(fd);
	set_nodelay(fd);
	memset(&a, 0, sizeof a);
	a.sin_family = AF_INET;
	a.sin_port = htons((uint16_t)G.be_port);
	a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
	r = connect(fd, (struct sockaddr *)&a, sizeof a);
	if (r < 0 && errno != EINPROGRESS) {
		close(fd);
		send_http_err(c, 502, "Bad Gateway");
		return;
	}
	rw = httpsd_rewrite_req(c->ibuf, c->req_hdr_len, c->ip_str, c->txbuf, sizeof c->txbuf);
	if (rw < 0) {
		close(fd);
		send_http_err(c, 431, "Headers Too Large");
		return;
	}
	c->bfd = fd;
	c->req_sent_off = 0;
	c->req_sent_len = rw;
	c->t_last = now;
	c->state = (r == 0) ? S_REQ_SEND : S_BE_CONN;
}

static void handle_conn(struct conn *c, uint64_t now)
{
	int r;

	if (c->state == S_HS_WAIT) {
		if (active_handshakes() < HTTPSD_MAX_HS) c->state = S_HS;
		else return;
	}

	if (c->state == S_HS) {
		r = mbedtls_ssl_handshake(&c->ssl);
		if (r == 0) {
			G.hs_total++;
			c->hs_want = 0;
			if (!c->hs_counted) c->hs_counted = 1;
			c->t_last = now;
			c->t_idle = now;
			c->state = S_REQ_HDR;
			DBG("handshake ok (%lu total)", G.hs_total);
		} else if (r == MBEDTLS_ERR_SSL_WANT_READ || r == MBEDTLS_ERR_SSL_WANT_WRITE) {
			c->hs_want = r;
		} else {
			conn_free(c);
			return;
		}
	}

	if (c->state == S_REQ_HDR) {
		for (;;) {
			int pr;

			if (c->ibuf_len > 0) {
				pr = httpsd_parse_req(c->ibuf, c->ibuf_len, &c->req);
				if (pr > 0) {
					c->req_hdr_len = (size_t)pr;
					c->req_body_rem = c->req.has_cl ? c->req.content_length : 0;
					G.req_total++;
					start_backend_connect(c, now);
					break;
				}
				if (pr == -1) { send_http_err(c, 400, "Bad Request"); break; }
				if (pr == -2) { send_http_err(c, 413, "Payload Too Large"); break; }
			}
			if (c->ibuf_len >= HTTPSD_MAX_HDR) { send_http_err(c, 431, "Headers Too Large"); break; }
			r = mbedtls_ssl_read(&c->ssl, (unsigned char *)c->ibuf + c->ibuf_len, HTTPSD_MAX_HDR - c->ibuf_len);
			if (r > 0) {
				c->ibuf_len += (size_t)r;
				c->t_last = now;
			} else if (r == MBEDTLS_ERR_SSL_WANT_READ || r == MBEDTLS_ERR_SSL_WANT_WRITE) {
				break;
			} else {
				conn_free(c);
				return;
			}
		}
	}

	if (c->state == S_BE_CONN) {
		int err = 0;
		socklen_t el = sizeof err;
		struct pollfd p = { c->bfd, POLLOUT, 0 };

		if (poll(&p, 1, 0) > 0 && (p.revents & (POLLOUT | POLLERR | POLLHUP))) {
			if (getsockopt(c->bfd, SOL_SOCKET, SO_ERROR, &err, &el) < 0 || err != 0) {
				conn_close_be(c);
				send_http_err(c, 502, "Bad Gateway");
				return;
			}
			c->state = S_REQ_SEND;
		}
	}

	if (c->state == S_REQ_SEND) {
		while (c->req_sent_off < c->req_sent_len) {
			ssize_t w = send(c->bfd, c->txbuf + c->req_sent_off,
					 (size_t)(c->req_sent_len - c->req_sent_off), MSG_NOSIGNAL);
			if (w > 0) { c->req_sent_off += (int)w; c->t_last = now; }
			else if (w < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) return;
			else { conn_close_be(c); send_http_err(c, 502, "Bad Gateway"); return; }
		}
		c->tx_off = 0;
		c->tx_len = 0;
		/* Move buffered request body tail out of ibuf */
		if (c->ibuf_len > c->req_hdr_len && c->req_body_rem > 0) {
			size_t avail = c->ibuf_len - c->req_hdr_len;
			size_t take = avail < c->req_body_rem ? avail : c->req_body_rem;
			if (take > sizeof c->txbuf) take = sizeof c->txbuf;
			memcpy(c->txbuf, c->ibuf + c->req_hdr_len, take);
			c->tx_off = 0;
			c->tx_len = take;
			c->req_body_rem -= take;
			if (avail > take) memmove(c->ibuf + c->req_hdr_len, c->ibuf + c->req_hdr_len + take, avail - take);
			c->ibuf_len -= take;
		} else {
			/* Discard request headers, preserve any pipelined tail */
			size_t left = c->ibuf_len > c->req_hdr_len ? c->ibuf_len - c->req_hdr_len : 0;
			if (left > 0) memmove(c->ibuf, c->ibuf + c->req_hdr_len, left);
			c->ibuf_len = left;
			c->req_hdr_len = 0;
		}
		c->state = (c->req_body_rem > 0 || c->tx_len > 0) ? S_REQ_BODY : S_RESP_HDR;
	}

	if (c->state == S_REQ_BODY) {
		for (;;) {
			while (c->tx_off < c->tx_len) {
				ssize_t w = send(c->bfd, c->txbuf + c->tx_off, c->tx_len - c->tx_off, MSG_NOSIGNAL);
				if (w > 0) { c->tx_off += (size_t)w; c->t_last = now; }
				else if (w < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) return;
				else { conn_close_be(c); send_http_err(c, 502, "Bad Gateway"); return; }
			}
			c->tx_off = 0;
			c->tx_len = 0;
			if (c->req_body_rem == 0) {
				size_t left = c->ibuf_len > c->req_hdr_len ? c->ibuf_len - c->req_hdr_len : 0;
				if (left > 0) memmove(c->ibuf, c->ibuf + c->req_hdr_len, left);
				c->ibuf_len = left;
				c->req_hdr_len = 0;
				c->state = S_RESP_HDR;
				break;
			}
			if (c->ibuf_len > c->req_hdr_len) {
				size_t avail = c->ibuf_len - c->req_hdr_len;
				size_t take = avail < c->req_body_rem ? avail : c->req_body_rem;
				if (take > sizeof c->txbuf) take = sizeof c->txbuf;
				memcpy(c->txbuf, c->ibuf + c->req_hdr_len, take);
				c->tx_len = take;
				c->req_body_rem -= take;
				if (avail > take) memmove(c->ibuf + c->req_hdr_len, c->ibuf + c->req_hdr_len + take, avail - take);
				c->ibuf_len -= take;
				continue;
			}
			{
				size_t want = c->req_body_rem < sizeof c->txbuf ? c->req_body_rem : sizeof c->txbuf;
				r = mbedtls_ssl_read(&c->ssl, (unsigned char *)c->txbuf, want);
				if (r > 0) {
					c->tx_len = (size_t)r;
					c->req_body_rem -= (size_t)r;
					c->t_last = now;
				} else if (r == MBEDTLS_ERR_SSL_WANT_READ || r == MBEDTLS_ERR_SSL_WANT_WRITE) {
					return;
				} else {
					conn_free(c);
					return;
				}
			}
		}
	}

	if (c->state == S_RESP_HDR) {
		for (;;) {
			if (c->obuf_len > 0) {
				int pr = httpsd_parse_resp(c->obuf, c->obuf_len, &c->resp);
				if (pr > 0) {
					int rw = httpsd_rewrite_resp(c->obuf, (size_t)pr, c->req.is_head,
								     c->req.keepalive, &c->resp,
								     c->txbuf, sizeof c->txbuf, &c->body_mode);
					if (rw < 0) { conn_close_be(c); send_http_err(c, 502, "Bad Gateway"); break; }
					if (G.lockout_on && c->resp.status == 401)
						httpsd_lockout_fail(&G.lockout, c->ip, (uint64_t)time(NULL));
					c->resp_hdr_len = (size_t)pr;
					c->resp_body_rem = (c->body_mode == HTTPSD_BODY_CL) ? c->resp.content_length : 0;
					c->tx_off = 0;
					c->tx_len = (size_t)rw;
					if (c->obuf_len > c->resp_hdr_len) {
						memmove(c->obuf, c->obuf + c->resp_hdr_len, c->obuf_len - c->resp_hdr_len);
						c->obuf_len -= c->resp_hdr_len;
					} else {
						c->obuf_len = 0;
					}
					c->state = S_RESP_BODY;
					break;
				}
				if (pr < 0) { conn_close_be(c); send_http_err(c, 502, "Bad Gateway"); break; }
			}
			if (c->obuf_len >= HTTPSD_MAX_HDR) { conn_close_be(c); send_http_err(c, 502, "Bad Gateway"); break; }
			{
				ssize_t rr = recv(c->bfd, c->obuf + c->obuf_len, HTTPSD_MAX_HDR - c->obuf_len, 0);
				if (rr > 0) {
					c->obuf_len += (size_t)rr;
					c->t_last = now;
				} else if (rr < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) {
					break;
				} else {
					conn_close_be(c);
					send_http_err(c, 502, "Bad Gateway");
					break;
				}
			}
		}
	}

	if (c->state == S_RESP_BODY) {
		for (;;) {
			if (c->tx_off < c->tx_len) {
				int f = tls_flush(c, now);
				if (f < 0) { conn_free(c); return; }
				if (f == 0) return;
			}
			if (c->body_mode == HTTPSD_BODY_NONE) {
				if (c->req.keepalive) conn_reset_ka(c, now);
				else c->state = S_CLOSE;
				break;
			}
			if (c->body_mode == HTTPSD_BODY_CL && c->resp_body_rem == 0) {
				if (c->req.keepalive) conn_reset_ka(c, now);
				else c->state = S_CLOSE;
				break;
			}
			if (c->body_mode == HTTPSD_BODY_CHUNKED_OUT && c->chunk_done) {
				conn_reset_ka(c, now);
				break;
			}
			if (c->body_mode == HTTPSD_BODY_CLOSE && c->be_eof && c->obuf_len == 0) {
				c->state = S_CLOSE;
				break;
			}

			if (c->obuf_len > 0) {
				if (c->body_mode == HTTPSD_BODY_CL) {
					size_t take = c->obuf_len < c->resp_body_rem ? c->obuf_len : c->resp_body_rem;
					if (take > sizeof c->txbuf) take = sizeof c->txbuf;
					memcpy(c->txbuf, c->obuf, take);
					c->tx_off = 0;
					c->tx_len = take;
					c->resp_body_rem -= take;
					if (c->obuf_len > take) memmove(c->obuf, c->obuf + take, c->obuf_len - take);
					c->obuf_len -= take;
				} else if (c->body_mode == HTTPSD_BODY_CHUNKED_OUT) {
					size_t max_payload = sizeof c->txbuf - 20;
					size_t take = c->obuf_len < max_payload ? c->obuf_len : max_payload;
					int hn = snprintf(c->txbuf, sizeof c->txbuf, "%zx\r\n", take);
					memcpy(c->txbuf + hn, c->obuf, take);
					c->txbuf[hn + (int)take] = '\r';
					c->txbuf[hn + (int)take + 1] = '\n';
					c->tx_off = 0;
					c->tx_len = (size_t)hn + take + 2;
					if (c->obuf_len > take) memmove(c->obuf, c->obuf + take, c->obuf_len - take);
					c->obuf_len -= take;
				} else {
					size_t take = c->obuf_len < sizeof c->txbuf ? c->obuf_len : sizeof c->txbuf;
					memcpy(c->txbuf, c->obuf, take);
					c->tx_off = 0;
					c->tx_len = take;
					if (c->obuf_len > take) memmove(c->obuf, c->obuf + take, c->obuf_len - take);
					c->obuf_len -= take;
				}
				continue;
			}

			if (c->bfd < 0 || c->be_eof) {
				if (c->body_mode == HTTPSD_BODY_CHUNKED_OUT && !c->chunk_done) {
					memcpy(c->txbuf, "0\r\n\r\n", 5);
					c->tx_off = 0;
					c->tx_len = 5;
					c->chunk_done = 1;
					continue;
				}
				if (c->body_mode == HTTPSD_BODY_CL && c->resp_body_rem > 0) {
					/* Truncated backend response: must close TLS */
					c->req.keepalive = 0;
				}
				c->state = S_CLOSE;
				break;
			}

			{
				ssize_t rr = recv(c->bfd, c->obuf, sizeof c->obuf, 0);
				if (rr > 0) {
					c->obuf_len = (size_t)rr;
					c->t_last = now;
				} else if (rr == 0) {
					c->be_eof = 1;
					conn_close_be(c);
				} else if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) {
					return;
				} else {
					c->be_eof = 1;
					conn_close_be(c);
					c->req.keepalive = 0;
				}
			}
		}
	}

	if (c->state == S_CLOSE) {
		if (c->tx_off < c->tx_len) {
			if (tls_flush(c, now) == 0) return;
		}
		(void)mbedtls_ssl_close_notify(&c->ssl);
		conn_free(c);
	}
}

int main(int argc, char **argv)
{
	int o, i;
	const char *drop = NULL;

	G.port = 443;
	G.be_port = 80;
	G.max_conns = HTTPSD_MAX_CONNS;
	G.nice_val = 5;
	snprintf(G.cdir, sizeof G.cdir, "/mnt/config");
	snprintf(G.hostname, sizeof G.hostname, "tc100");
	if (getenv("TC100_WEB_LOCKOUT") && strcmp(getenv("TC100_WEB_LOCKOUT"), "1") == 0)
		G.lockout_on = 1;

	while ((o = getopt(argc, argv, "p:b:c:H:I:m:D:n:Ld")) != -1) {
		switch (o) {
		case 'p': G.port = (unsigned)atoi(optarg); break;
		case 'b': G.be_port = (unsigned)atoi(optarg); break;
		case 'c': snprintf(G.cdir, sizeof G.cdir, "%s", optarg); break;
		case 'H': snprintf(G.hostname, sizeof G.hostname, "%s", optarg); break;
		case 'I': snprintf(G.ip_str, sizeof G.ip_str, "%s", optarg); break;
		case 'm': G.max_conns = atoi(optarg); break;
		case 'D': drop = optarg; break;
		case 'n': G.nice_val = atoi(optarg); break;
		case 'L': G.lockout_on = 1; break;
		case 'd': G.debug = 1; break;
		default:
			fprintf(stderr, "usage: tc100-httpsd [-p port] [-b backend] [-c certdir] [-H host] [-I ipv4] [-m max] [-D uid:gid] [-n nice] [-L] [-d]\n");
			return 2;
		}
	}
	if (G.max_conns < 1) G.max_conns = 1;
	if (G.max_conns > 8) G.max_conns = 8;
	for (i = 0; i < 8; i++) { G.conns[i].cfd = -1; G.conns[i].bfd = -1; }

	signal(SIGPIPE, SIG_IGN);
	signal(SIGTERM, on_term);
	signal(SIGINT, on_term);
	httpsd_nets_parse(&G.nets, getenv("TC100_NET_ALLOW"));
	httpsd_lockout_init(&G.lockout);

#ifdef MBEDTLS_PSA_CRYPTO_C
	if (psa_crypto_init() != PSA_SUCCESS) { LOG("psa_crypto_init failed"); return 1; }
#endif
	mbedtls_entropy_init(&G.ent);
	mbedtls_ctr_drbg_init(&G.drbg);
	if (mbedtls_ctr_drbg_seed(&G.drbg, mbedtls_entropy_func, &G.ent, (const unsigned char *)"tc100-httpsd", 12)) {
		LOG("entropy seed failed");
		return 1;
	}
	if (cert_init() || tls_init()) return 1;

	G.lfd = listen_tcp(G.port);
	if (G.lfd < 0) {
		LOG("cannot listen on port %u: %s", G.port, strerror(errno));
		return 1;
	}
	if (priv_drop(drop)) {
		LOG("cannot drop root (-D %s): stopping", drop);
		return 1;
	}
	if (G.nice_val != 0) (void)nice(G.nice_val);
	LOG("ready on :%u -> 127.0.0.1:%u (max=%d, lockout=%d, nice=%d)", G.port, G.be_port, G.max_conns, G.lockout_on, G.nice_val);

	while (!G.quit) {
		struct pollfd pf[1 + 16];
		int nf = 1, to = 1000;
		uint64_t now = now_ms();

		pf[0].fd = G.lfd;
		pf[0].events = POLLIN;

		for (i = 0; i < G.max_conns; i++) {
			struct conn *c = &G.conns[i];
			short cev = 0, bev = 0;

			if (c->state == S_FREE) continue;
			if (c->state == S_HS_WAIT && active_handshakes() < HTTPSD_MAX_HS) to = 0;
			if (c->state == S_HS) {
				cev = (c->hs_want == MBEDTLS_ERR_SSL_WANT_WRITE) ? POLLOUT : POLLIN;
			} else if (c->state == S_REQ_HDR) {
				cev = POLLIN;
				if (c->ssl_on && mbedtls_ssl_get_bytes_avail(&c->ssl) > 0) to = 0;
			} else if (c->state == S_BE_CONN || c->state == S_REQ_SEND) {
				bev = POLLOUT;
			} else if (c->state == S_REQ_BODY) {
				if (c->tx_off < c->tx_len) {
					bev = POLLOUT;
				} else {
					cev = POLLIN;
					if (c->ssl_on && mbedtls_ssl_get_bytes_avail(&c->ssl) > 0) to = 0;
				}
			} else if (c->state == S_RESP_HDR) {
				bev = POLLIN;
			} else if (c->state == S_RESP_BODY) {
				if (c->tx_off < c->tx_len) cev = POLLOUT;
				if (c->bfd >= 0 && c->obuf_len == 0 && !c->be_eof) bev |= POLLIN;
			} else if (c->state == S_CLOSE) {
				if (c->tx_off < c->tx_len) cev = POLLOUT;
				else to = 0;
			}
			if (c->cfd >= 0 && cev) {
				pf[nf].fd = c->cfd; pf[nf].events = cev; nf++;
			}
			if (c->bfd >= 0 && bev) {
				pf[nf].fd = c->bfd; pf[nf].events = bev; nf++;
			}
		}

		if (poll(pf, (nfds_t)nf, to) < 0 && errno != EINTR) break;
		now = now_ms();
		if (pf[0].revents & POLLIN) accept_clients(now);

		for (i = 0; i < G.max_conns; i++) {
			struct conn *c = &G.conns[i];

			if (c->state == S_FREE) continue;
			handle_conn(c, now);
			if (c->state == S_FREE) continue;
			if (c->state == S_REQ_HDR && c->ibuf_len == 0 && (now - c->t_idle) > 30000ULL) {
				c->state = S_CLOSE;
				handle_conn(c, now);
			} else if (c->state == S_HS && (now - c->t_last) > 5000ULL) {
				conn_free(c);
			} else if (c->state != S_REQ_HDR && (now - c->t_last) > 30000ULL) {
				conn_free(c);
			}
		}
	}

	LOG("stopping (reqs=%lu hs=%lu)", G.req_total, G.hs_total);
	for (i = 0; i < G.max_conns; i++) conn_free(&G.conns[i]);
	if (G.lfd >= 0) close(G.lfd);
#ifdef MBEDTLS_SSL_SESSION_TICKETS
	mbedtls_ssl_ticket_free(&G.ticket);
#endif
#ifdef MBEDTLS_SSL_CACHE_C
	mbedtls_ssl_cache_free(&G.cache);
#endif
	mbedtls_ssl_config_free(&G.conf);
	mbedtls_x509_crt_free(&G.crt);
	mbedtls_pk_free(&G.key);
	mbedtls_ctr_drbg_free(&G.drbg);
	mbedtls_entropy_free(&G.ent);
	return 0;
}
