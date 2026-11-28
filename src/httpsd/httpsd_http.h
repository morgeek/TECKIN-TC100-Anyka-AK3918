/* httpsd_http.h: pure-C HTTP/1.1 framing, CIDR ACL, 401 lockout, and ASN.1 SAN helpers for tc100-httpsd.
 * Kept free of Mbed TLS headers so host tests and libFuzzer compile directly with plain cc/clang. */
#ifndef HTTPSD_HTTP_H
#define HTTPSD_HTTP_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define HTTPSD_MAX_HDR    16384
#define HTTPSD_MAX_BODY   (12U * 1024U * 1024U)
#define HTTPSD_MAX_CONNS  6
#define HTTPSD_PER_IP     4
#define HTTPSD_MAX_HS     2
#define HTTPSD_LOCK_FAILS 10
#define HTTPSD_LOCK_WIN   300
#define HTTPSD_LOCK_SEC   300
#define HTTPSD_NLOCK      64
#define HTTPSD_MAXNET     16

enum {
	HTTPSD_BODY_NONE = 0,
	HTTPSD_BODY_CL = 1,
	HTTPSD_BODY_CHUNKED_OUT = 2,
	HTTPSD_BODY_CLOSE = 3
};

struct httpsd_req {
	int is_head;
	int http_minor;
	int keepalive;
	int has_cl;
	int is_chunked;
	size_t content_length;
};

struct httpsd_resp {
	int status;
	int has_cl;
	int is_chunked;
	int conn_close;
	size_t content_length;
};

struct httpsd_net {
	uint32_t net, mask;
};

struct httpsd_nets {
	struct httpsd_net a[HTTPSD_MAXNET];
	int n;
};

struct httpsd_lock_ent {
	uint32_t ip;
	int fails;
	uint64_t win_start;
	uint64_t blocked_until;
};

struct httpsd_lockout {
	struct httpsd_lock_ent e[HTTPSD_NLOCK];
};

static inline int httpsd_lc(int c) { return (c >= 'A' && c <= 'Z') ? c + 32 : c; }

static inline int httpsd_ieq_n(const char *a, size_t alen, const char *b)
{
	size_t blen = strlen(b), i;

	if (alen != blen) return 0;
	for (i = 0; i < alen; i++) if (httpsd_lc((unsigned char)a[i]) != httpsd_lc((unsigned char)b[i])) return 0;
	return 1;
}

static inline int httpsd_has_token_ci(const char *val, size_t vlen, const char *tok)
{
	size_t tlen = strlen(tok), i = 0;

	while (i < vlen) {
		size_t s, e;

		while (i < vlen && (val[i] == ' ' || val[i] == '\t' || val[i] == ',')) i++;
		s = i;
		while (i < vlen && val[i] != ',') i++;
		e = i;
		while (e > s && (val[e - 1] == ' ' || val[e - 1] == '\t')) e--;
		if (e - s == tlen && httpsd_ieq_n(val + s, e - s, tok)) return 1;
	}
	return 0;
}

static inline int httpsd_is_tchar(unsigned char c)
{
	if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) return 1;
	return strchr("!#$%&'*+-.^_`|~", (int)c) != NULL;
}

static inline int httpsd_find_hdr_end(const char *buf, size_t len)
{
	size_t i;

	for (i = 0; i + 3 < len && i < HTTPSD_MAX_HDR; i++) {
		if (buf[i] == '\r' && buf[i + 1] == '\n' && buf[i + 2] == '\r' && buf[i + 3] == '\n')
			return (int)(i + 4);
	}
	return 0;
}

static inline int httpsd_parse_u32_ipv4(const char *s, size_t len, uint32_t *out)
{
	uint32_t v = 0;
	int part = 0;
	size_t i = 0;

	if (!s || !len) return -1;
	for (part = 0; part < 4; part++) {
		uint32_t oct = 0;
		int dig = 0;

		if (part > 0) {
			if (i >= len || s[i] != '.') return -1;
			i++;
		}
		while (i < len && s[i] >= '0' && s[i] <= '9') {
			oct = oct * 10u + (uint32_t)(s[i] - '0');
			if (oct > 255u) return -1;
			dig++;
			i++;
		}
		if (!dig) return -1;
		v = (v << 8) | oct;
	}
	if (i != len) return -1;
	*out = v;
	return 0;
}

/* Returns: 0 need more data, >0 header length (incl. \r\n\r\n), -1 bad request (400), -2 too large (413/431). */
static inline int httpsd_parse_req(const char *buf, size_t len, struct httpsd_req *req)
{
	int hdr_end;
	size_t pos = 0, i;
	const char *rl;
	size_t rllen;
	const char *sp1, *sp2;
	int conn_close = 0, conn_ka = 0;

	memset(req, 0, sizeof *req);
	if (!buf) return -1;
	hdr_end = httpsd_find_hdr_end(buf, len);
	{
		size_t scan = hdr_end ? (size_t)hdr_end : (len < HTTPSD_MAX_HDR ? len : HTTPSD_MAX_HDR);
		for (i = 0; i < scan; i++) {
			if (buf[i] == '\0') return -1;
			if (buf[i] == '\n' && (i == 0 || buf[i - 1] != '\r')) return -1;
		}
	}
	if (!hdr_end) return (len >= HTTPSD_MAX_HDR) ? -2 : 0;

	/* First line */
	rl = buf;
	for (pos = 0; pos + 1 < (size_t)hdr_end; pos++) {
		if (buf[pos] == '\n') return -1; /* bare LF */
		if (buf[pos] == '\r' && buf[pos + 1] == '\n') break;
	}
	if (pos == 0 || pos + 1 >= (size_t)hdr_end) return -1;
	rllen = pos;
	sp1 = memchr(rl, ' ', rllen);
	if (!sp1 || sp1 == rl || (size_t)(sp1 - rl) > 15) return -1;
	for (i = 0; i < (size_t)(sp1 - rl); i++) {
		if (!httpsd_is_tchar((unsigned char)rl[i])) return -1;
	}
	req->is_head = ((sp1 - rl) == 4 && memcmp(rl, "HEAD", 4) == 0);

	sp2 = memchr(sp1 + 1, ' ', rllen - (size_t)(sp1 + 1 - rl));
	if (!sp2 || sp2 == sp1 + 1) return -1;
	if (sp1[1] != '/' && !((sp2 - (sp1 + 1)) == 1 && sp1[1] == '*')) return -1;
	for (i = (size_t)(sp1 + 1 - rl); i < (size_t)(sp2 - rl); i++) {
		unsigned char ch = (unsigned char)rl[i];
		if (ch <= 0x20 || ch == 0x7f) return -1;
	}
	if ((size_t)(rl + rllen - (sp2 + 1)) != 8 || memcmp(sp2 + 1, "HTTP/1.", 7) != 0) return -1;
	if (sp2[8] == '0') req->http_minor = 0;
	else if (sp2[8] == '1') req->http_minor = 1;
	else return -1;

	pos += 2;
	while (pos < (size_t)hdr_end - 2) {
		size_t lend = pos, colon = 0, vstart, vend;

		while (lend + 1 < (size_t)hdr_end) {
			if (buf[lend] == '\n') return -1; /* bare LF */
			if (buf[lend] == '\r' && buf[lend + 1] == '\n') break;
			lend++;
		}
		if (lend + 1 >= (size_t)hdr_end) return -1;
		if (lend == pos) break;
		if (buf[pos] == ' ' || buf[pos] == '\t') return -1; /* obs-fold */
		for (i = pos; i < lend; i++) {
			if (buf[i] == ':') { colon = i; break; }
			if (!httpsd_is_tchar((unsigned char)buf[i])) return -1;
		}
		if (!colon || colon == pos) return -1;
		vstart = colon + 1;
		while (vstart < lend && (buf[vstart] == ' ' || buf[vstart] == '\t')) vstart++;
		vend = lend;
		while (vend > vstart && (buf[vend - 1] == ' ' || buf[vend - 1] == '\t')) vend--;
		for (i = vstart; i < vend; i++) {
			unsigned char ch = (unsigned char)buf[i];
			if ((ch < 0x20 && ch != '\t') || ch == 0x7f) return -1;
		}

		if (httpsd_ieq_n(buf + pos, colon - pos, "Content-Length")) {
			uint64_t cl = 0;

			if (req->has_cl) return -1; /* reject duplicate Content-Length */
			if (vstart == vend) return -1;
			for (i = vstart; i < vend; i++) {
				if (buf[i] < '0' || buf[i] > '9') return -1;
				cl = cl * 10ULL + (uint64_t)(buf[i] - '0');
				if (cl > HTTPSD_MAX_BODY) return -2;
			}
			req->has_cl = 1;
			req->content_length = (size_t)cl;
		} else if (httpsd_ieq_n(buf + pos, colon - pos, "Transfer-Encoding")) {
			if (httpsd_has_token_ci(buf + vstart, vend - vstart, "chunked")) {
				req->is_chunked = 1;
			} else if (vstart != vend) {
				return -1;
			}
		} else if (httpsd_ieq_n(buf + pos, colon - pos, "Connection")) {
			if (httpsd_has_token_ci(buf + vstart, vend - vstart, "close")) conn_close = 1;
			if (httpsd_has_token_ci(buf + vstart, vend - vstart, "keep-alive")) conn_ka = 1;
		}
		pos = lend + 2;
	}
	if (req->has_cl && req->is_chunked) return -1; /* CL + TE smuggling */
	req->keepalive = (req->http_minor == 1) ? !conn_close : (conn_ka && !conn_close);
	return hdr_end;
}

static inline int httpsd_rewrite_req(const char *buf, size_t hdr_len, const char *peer_ip, char *out, size_t out_cap)
{
	size_t pos = 0, op = 0, lend;
	char tail[160];
	int tlen;

	if (!buf || hdr_len < 4 || !peer_ip || !out) return -1;
	/* Copy request line */
	for (lend = 0; lend + 1 < hdr_len; lend++) {
		if (buf[lend] == '\r' && buf[lend + 1] == '\n') break;
	}
	if (lend + 2 > hdr_len || lend + 2 > out_cap) return -1;
	memcpy(out, buf, lend + 2);
	op = lend + 2;
	pos = lend + 2;

	while (pos + 2 < hdr_len) {
		size_t colon = 0, i;

		for (lend = pos; lend + 1 < hdr_len; lend++) {
			if (buf[lend] == '\r' && buf[lend + 1] == '\n') break;
		}
		if (lend == pos) break;
		for (i = pos; i < lend; i++) if (buf[i] == ':') { colon = i; break; }
		if (colon > pos &&
		    !httpsd_ieq_n(buf + pos, colon - pos, "Connection") &&
		    !httpsd_ieq_n(buf + pos, colon - pos, "Keep-Alive") &&
		    !httpsd_ieq_n(buf + pos, colon - pos, "Proxy-Connection") &&
		    !httpsd_ieq_n(buf + pos, colon - pos, "X-Forwarded-For") &&
		    !httpsd_ieq_n(buf + pos, colon - pos, "X-Forwarded-Proto")) {
			size_t line_n = lend - pos + 2;
			if (op + line_n >= out_cap) return -1;
			memcpy(out + op, buf + pos, line_n);
			op += line_n;
		}
		pos = lend + 2;
	}
	tlen = snprintf(tail, sizeof tail,
			"Connection: close\r\nX-Forwarded-Proto: https\r\nX-Forwarded-For: %s\r\n\r\n",
			peer_ip);
	if (tlen < 0 || (size_t)tlen >= sizeof tail || op + (size_t)tlen > out_cap) return -1;
	memcpy(out + op, tail, (size_t)tlen);
	op += (size_t)tlen;
	return (int)op;
}

static inline int httpsd_parse_resp(const char *buf, size_t len, struct httpsd_resp *resp)
{
	int hdr_end;
	size_t pos = 0, lend, i;

	memset(resp, 0, sizeof *resp);
	if (!buf) return -1;
	hdr_end = httpsd_find_hdr_end(buf, len);
	if (!hdr_end) return (len >= HTTPSD_MAX_HDR) ? -1 : 0;

	for (lend = 0; lend + 1 < (size_t)hdr_end; lend++) {
		if (buf[lend] == '\r' && buf[lend + 1] == '\n') break;
	}
	if (lend < 12 || memcmp(buf, "HTTP/1.", 7) != 0 || (buf[7] != '0' && buf[7] != '1') || buf[8] != ' ')
		return -1;
	if (buf[9] < '1' || buf[9] > '5' || buf[10] < '0' || buf[10] > '9' || buf[11] < '0' || buf[11] > '9')
		return -1;
	if (lend > 12 && buf[12] != ' ') return -1;
	resp->status = (buf[9] - '0') * 100 + (buf[10] - '0') * 10 + (buf[11] - '0');

	pos = lend + 2;
	while (pos + 2 < (size_t)hdr_end) {
		size_t colon = 0, vstart, vend;

		for (lend = pos; lend + 1 < (size_t)hdr_end; lend++) {
			if (buf[lend] == '\r' && buf[lend + 1] == '\n') break;
		}
		if (lend == pos) break;
		for (i = pos; i < lend; i++) if (buf[i] == ':') { colon = i; break; }
		if (colon > pos) {
			vstart = colon + 1;
			while (vstart < lend && (buf[vstart] == ' ' || buf[vstart] == '\t')) vstart++;
			vend = lend;
			while (vend > vstart && (buf[vend - 1] == ' ' || buf[vend - 1] == '\t')) vend--;
			if (httpsd_ieq_n(buf + pos, colon - pos, "Content-Length") && !resp->has_cl && vstart < vend) {
				uint64_t cl = 0;
				int ok = 1;
				for (i = vstart; i < vend; i++) {
					if (buf[i] < '0' || buf[i] > '9') { ok = 0; break; }
					cl = cl * 10ULL + (uint64_t)(buf[i] - '0');
					if (cl > 0x7fffffffULL) { ok = 0; break; }
				}
				if (ok) { resp->has_cl = 1; resp->content_length = (size_t)cl; }
			} else if (httpsd_ieq_n(buf + pos, colon - pos, "Transfer-Encoding") &&
				   httpsd_has_token_ci(buf + vstart, vend - vstart, "chunked")) {
				resp->is_chunked = 1;
			} else if (httpsd_ieq_n(buf + pos, colon - pos, "Connection") &&
				   httpsd_has_token_ci(buf + vstart, vend - vstart, "close")) {
				resp->conn_close = 1;
			}
		}
		pos = lend + 2;
	}
	return hdr_end;
}

static inline int httpsd_rewrite_resp(const char *buf, size_t hdr_len, int req_is_head, int client_keepalive,
				      const struct httpsd_resp *resp, char *out, size_t out_cap, int *body_mode)
{
	size_t pos = 0, op = 0, lend;
	int no_body;
	char tail[160];
	int tlen, bm;

	if (!buf || hdr_len < 16 || !resp || !out || !body_mode) return -1;
	no_body = req_is_head || (resp->status >= 100 && resp->status < 200) || resp->status == 204 || resp->status == 304;
	if (no_body) bm = HTTPSD_BODY_NONE;
	else if (resp->has_cl) bm = HTTPSD_BODY_CL;
	else if (!resp->is_chunked && client_keepalive) bm = HTTPSD_BODY_CHUNKED_OUT;
	else bm = HTTPSD_BODY_CLOSE;
	*body_mode = bm;

	for (lend = 0; lend + 1 < hdr_len; lend++) {
		if (buf[lend] == '\r' && buf[lend + 1] == '\n') break;
	}
	if (lend < 12 || lend + 2 > out_cap) return -1;
	memcpy(out, buf, lend + 2);
	out[7] = '1'; /* upgrade status line to HTTP/1.1 for persistent connections + chunked */
	op = lend + 2;
	pos = lend + 2;

	while (pos + 2 < hdr_len) {
		size_t colon = 0, i;

		for (lend = pos; lend + 1 < hdr_len; lend++) {
			if (buf[lend] == '\r' && buf[lend + 1] == '\n') break;
		}
		if (lend == pos) break;
		for (i = pos; i < lend; i++) if (buf[i] == ':') { colon = i; break; }
		if (colon > pos &&
		    !httpsd_ieq_n(buf + pos, colon - pos, "Connection") &&
		    !httpsd_ieq_n(buf + pos, colon - pos, "Keep-Alive") &&
		    !httpsd_ieq_n(buf + pos, colon - pos, "Proxy-Connection")) {
			size_t line_n = lend - pos + 2;
			if (op + line_n >= out_cap) return -1;
			memcpy(out + op, buf + pos, line_n);
			op += line_n;
		}
		pos = lend + 2;
	}

	if (bm == HTTPSD_BODY_CHUNKED_OUT) {
		tlen = snprintf(tail, sizeof tail,
				"Transfer-Encoding: chunked\r\nConnection: keep-alive\r\nKeep-Alive: timeout=30, max=100\r\n\r\n");
	} else if (client_keepalive && bm != HTTPSD_BODY_CLOSE) {
		tlen = snprintf(tail, sizeof tail,
				"Connection: keep-alive\r\nKeep-Alive: timeout=30, max=100\r\n\r\n");
	} else {
		tlen = snprintf(tail, sizeof tail, "Connection: close\r\n\r\n");
	}
	if (tlen < 0 || (size_t)tlen >= sizeof tail || op + (size_t)tlen > out_cap) return -1;
	memcpy(out + op, tail, (size_t)tlen);
	op += (size_t)tlen;
	return (int)op;
}

static inline void httpsd_nets_parse(struct httpsd_nets *nets, const char *s)
{
	nets->n = 0;
	if (!s) return;
	while (*s && nets->n < HTTPSD_MAXNET) {
		uint32_t a, mask = 0xffffffffu;
		const char *tok, *sl = NULL, *end;

		while (*s == ' ' || *s == '\t' || *s == ',') s++;
		if (!*s) break;
		tok = s;
		while (*s && *s != ' ' && *s != '\t' && *s != ',') {
			if (*s == '/' && !sl) sl = s;
			s++;
		}
		end = sl ? sl : s;
		if (httpsd_parse_u32_ipv4(tok, (size_t)(end - tok), &a) == 0) {
			int bits = 32, ok = 1;

			if (sl) {
				const char *p = sl + 1;
				if (p == s) ok = 0;
				bits = 0;
				for (; p < s; p++) {
					if (*p < '0' || *p > '9') { ok = 0; break; }
					bits = bits * 10 + (*p - '0');
				}
				if (bits < 0 || bits > 32) ok = 0;
			}
			if (ok) {
				mask = (bits == 0) ? 0u : (0xffffffffu << (32 - bits));
				nets->a[nets->n].net = a & mask;
				nets->a[nets->n].mask = mask;
				nets->n++;
			}
		}
	}
}

static inline int httpsd_nets_allow(const struct httpsd_nets *nets, uint32_t host_ip)
{
	int i;

	if ((host_ip >> 24) == 127u) return 1;
	if (!nets || nets->n == 0) return 1;
	for (i = 0; i < nets->n; i++) {
		if ((host_ip & nets->a[i].mask) == nets->a[i].net) return 1;
	}
	return 0;
}

static inline void httpsd_lockout_init(struct httpsd_lockout *l)
{
	memset(l, 0, sizeof *l);
}

static inline int httpsd_lockout_blocked(const struct httpsd_lockout *l, uint32_t host_ip, uint64_t now_s)
{
	int i;

	if ((host_ip >> 24) == 127u) return 0;
	for (i = 0; i < HTTPSD_NLOCK; i++) {
		if (l->e[i].ip == host_ip && l->e[i].blocked_until > now_s) return 1;
	}
	return 0;
}

static inline void httpsd_lockout_fail(struct httpsd_lockout *l, uint32_t host_ip, uint64_t now_s)
{
	int i, free_idx = -1, oldest_idx = 0;
	uint64_t oldest_t = ~(uint64_t)0;

	if ((host_ip >> 24) == 127u || !host_ip) return;
	for (i = 0; i < HTTPSD_NLOCK; i++) {
		if (l->e[i].ip == host_ip) {
			struct httpsd_lock_ent *e = &l->e[i];
			if (now_s >= e->win_start + HTTPSD_LOCK_WIN) {
				e->fails = 0;
				e->win_start = now_s;
			}
			e->fails++;
			if (e->fails >= HTTPSD_LOCK_FAILS) {
				e->blocked_until = now_s + HTTPSD_LOCK_SEC;
				e->fails = 0;
			}
			return;
		}
		if (!l->e[i].ip && free_idx < 0) free_idx = i;
		if (l->e[i].win_start < oldest_t) { oldest_t = l->e[i].win_start; oldest_idx = i; }
	}
	i = (free_idx >= 0) ? free_idx : oldest_idx;
	l->e[i].ip = host_ip;
	l->e[i].fails = 1;
	l->e[i].win_start = now_s;
	l->e[i].blocked_until = 0;
}

static inline int httpsd_add_san_dns(uint8_t *dst, size_t *pos, size_t cap, const char *name,
				     const char (*seen)[80], int *nseen)
{
	size_t n, j;
	int i;

	if (!name || !name[0]) return 0;
	n = strlen(name);
	if (n > 64) return 0;
	for (j = 0; j < n; j++) {
		unsigned char c = (unsigned char)name[j];
		if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' || c == '.'))
			return 0;
	}
	for (i = 0; i < *nseen; i++) {
		if (httpsd_ieq_n(name, n, seen[i])) return 0;
	}
	if (*pos + 2 + n > cap) return -1;
	dst[(*pos)++] = 0x82; /* dNSName [2] IMPLICIT IA5String */
	dst[(*pos)++] = (uint8_t)n;
	memcpy(dst + *pos, name, n);
	*pos += n;
	return 1;
}

/* Builds DER ASN.1 SubjectAltName extension value (SEQUENCE of GeneralName). */
static inline int httpsd_build_san_der(const char *host, const char *ip_str, uint8_t *out, size_t out_cap)
{
	uint8_t inner[512];
	size_t ilen = 0, hdr_sz, n;
	char seen[6][80];
	int nseen = 0;
	const char *cands[4];
	char host_local[80];
	int i;
	uint32_t ip4 = 0;

	host_local[0] = 0;
	if (host && host[0]) {
		n = strlen(host);
		if (n < 64) {
			if (n > 6 && httpsd_ieq_n(host + n - 6, 6, ".local")) {
				snprintf(host_local, sizeof host_local, "%s", host);
			} else {
				snprintf(host_local, sizeof host_local, "%s.local", host);
			}
		}
	}
	cands[0] = (host && host[0]) ? host : NULL;
	cands[1] = host_local[0] ? host_local : NULL;
	cands[2] = "tc100";
	cands[3] = "tc100.local";

	for (i = 0; i < 4 && nseen < 6; i++) {
		int r;
		if (!cands[i]) continue;
		r = httpsd_add_san_dns(inner, &ilen, sizeof inner, cands[i], (const char (*)[80])seen, &nseen);
		if (r < 0) return -1;
		if (r > 0) snprintf(seen[nseen++], sizeof seen[0], "%s", cands[i]);
	}
	if (ip_str && ip_str[0] && httpsd_parse_u32_ipv4(ip_str, strlen(ip_str), &ip4) == 0) {
		if (ilen + 6 > sizeof inner) return -1;
		inner[ilen++] = 0x87; /* iPAddress [7] IMPLICIT OCTET STRING */
		inner[ilen++] = 4;
		inner[ilen++] = (uint8_t)(ip4 >> 24);
		inner[ilen++] = (uint8_t)(ip4 >> 16);
		inner[ilen++] = (uint8_t)(ip4 >> 8);
		inner[ilen++] = (uint8_t)(ip4);
	}
	hdr_sz = (ilen < 128) ? 2 : 3;
	if (hdr_sz + ilen > out_cap) return -1;
	out[0] = 0x30;
	if (ilen < 128) {
		out[1] = (uint8_t)ilen;
	} else {
		out[1] = 0x81;
		out[2] = (uint8_t)ilen;
	}
	memcpy(out + hdr_sz, inner, ilen);
	return (int)(hdr_sz + ilen);
}

#endif
