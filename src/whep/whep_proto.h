/* whep_proto.h: the protocol text and packet code of the WHEP gateway (item 35, src/whep), with no library but
 * srtp.h (SHA-1 / HMAC-SHA1): so that the host tests (whep_test.c: RFC 5769 STUN vectors, SDP offers and answers)
 * and the daemon (tc100_whep.c, which adds mbedTLS for DTLS) share the same code.
 *   - STUN (RFC 5389, 5245 ICE-lite): parse a binding request, check MESSAGE-INTEGRITY and FINGERPRINT, build the
 *     success response (XOR-MAPPED-ADDRESS, MESSAGE-INTEGRITY, FINGERPRINT);
 *   - SDP: read the browser's offer (ICE credentials, DTLS fingerprint, media sections, H.264 / PCMA payload types),
 *     write the answer (ice-lite, one host candidate, setup:passive, sendonly, bundle, rtcp-mux);
 *   - H.264 parameter sets from the RTSP "sprop-parameter-sets" (base64). */
#ifndef TC100_WHEP_PROTO_H
#define TC100_WHEP_PROTO_H
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <ctype.h>
#include "srtp.h"

/* ---- STUN ---- */
#define STUN_MAGIC 0x2112a442u

static uint32_t wh_crc32(const uint8_t *p, size_t n)
{
	uint32_t c = 0xffffffffu;
	int k;

	while (n--) {
		c ^= *p++;
		for (k = 0; k < 8; k++) c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1)));
	}
	return ~c;
}

static unsigned wh_be16(const uint8_t *p) { return (unsigned)p[0] << 8 | p[1]; }
static void wh_put16(uint8_t *p, unsigned v) { p[0] = (uint8_t)(v >> 8); p[1] = (uint8_t)v; }

struct stun_msg {
	unsigned type;			/* 0x0001 = binding request */
	const uint8_t *tid;		/* 12 bytes */
	const uint8_t *user;		/* USERNAME value */
	size_t user_len;
	size_t mi_off;			/* offset of the MESSAGE-INTEGRITY attribute (0 = none) */
	int use_candidate;
};

/* 0 = well-formed (and the FINGERPRINT, when there is one, matches), -1 otherwise */
static int stun_parse(const uint8_t *b, size_t n, struct stun_msg *m)
{
	size_t off = 20, len;

	memset(m, 0, sizeof *m);
	if (n < 20 || n > 1500 || (b[0] & 0xc0) || (b[3] & 3)) return -1;
	len = wh_be16(b + 2);
	if (len + 20 != n || b[4] != 0x21 || b[5] != 0x12 || b[6] != 0xa4 || b[7] != 0x42) return -1;
	m->type = wh_be16(b);
	m->tid = b + 8;
	while (off + 4 <= n) {
		unsigned t = wh_be16(b + off), l = wh_be16(b + off + 2);
		size_t next = off + 4 + ((l + 3u) & ~3u);

		if (next > n) return -1;
		if (t == 0x0006) { m->user = b + off + 4; m->user_len = l; }
		else if (t == 0x0008 && l == 20 && !m->mi_off) m->mi_off = off;
		else if (t == 0x0025) m->use_candidate = 1;
		else if (t == 0x8028 && l == 4) {		/* the fingerprint is last: CRC-32 of everything before it, xor 'STUN' */
			uint32_t c = wh_crc32(b, off) ^ 0x5354554eu;

			if (next != n || b[off + 4] != (uint8_t)(c >> 24) || b[off + 5] != (uint8_t)(c >> 16) ||
			    b[off + 6] != (uint8_t)(c >> 8) || b[off + 7] != (uint8_t)c)
				return -1;
		}
		off = next;
	}
	return off == n ? 0 : -1;
}

/* the HMAC-SHA1 of a message up to its MESSAGE-INTEGRITY attribute, the length field counting that attribute */
static void stun_mi(const uint8_t *b, size_t mi_off, const struct hmac_sha1 *key, uint8_t out[20])
{
	uint8_t hdr[20];

	memcpy(hdr, b, 20);
	wh_put16(hdr + 2, (unsigned)(mi_off - 20 + 24));
	hmac_sha1(key, hdr, 20, b + 20, mi_off - 20, out);
}

static int stun_check_integrity(const uint8_t *b, const struct stun_msg *m, const struct hmac_sha1 *key)
{
	uint8_t mac[20];
	unsigned diff = 0;
	int i;

	if (!m->mi_off) return 0;
	stun_mi(b, m->mi_off, key, mac);
	for (i = 0; i < 20; i++) diff |= (unsigned)(mac[i] ^ b[m->mi_off + 4 + i]);
	return diff == 0;
}

/* b[0..len) is a message (header + attributes, length field not yet set): append MESSAGE-INTEGRITY and FINGERPRINT,
 * set the length field, return the final size */
static size_t stun_finish(uint8_t *b, size_t len, const struct hmac_sha1 *key)
{
	uint32_t c;
	size_t mi = len;

	stun_mi(b, mi, key, b + mi + 4);			/* length field is patched inside on a copy of the header */
	wh_put16(b + mi, 0x0008); wh_put16(b + mi + 2, 20);
	len = mi + 24;
	wh_put16(b + 2, (unsigned)(len - 20 + 8));
	c = wh_crc32(b, len) ^ 0x5354554eu;
	wh_put16(b + len, 0x8028); wh_put16(b + len + 2, 4);
	b[len + 4] = (uint8_t)(c >> 24); b[len + 5] = (uint8_t)(c >> 16); b[len + 6] = (uint8_t)(c >> 8); b[len + 7] = (uint8_t)c;
	len += 8;
	wh_put16(b + 2, (unsigned)(len - 20));
	return len;
}

/* binding success response to a request with transaction id tid, from the address ip:port (host order) it came from;
 * out holds at least 64 bytes */
static size_t stun_binding_response(uint8_t *out, const uint8_t *tid, uint32_t ip, unsigned port,
				    const struct hmac_sha1 *key)
{
	uint32_t x = ip ^ STUN_MAGIC;

	wh_put16(out, 0x0101); wh_put16(out + 2, 0);
	out[4] = 0x21; out[5] = 0x12; out[6] = 0xa4; out[7] = 0x42;
	memcpy(out + 8, tid, 12);
	wh_put16(out + 20, 0x0020); wh_put16(out + 22, 8);	/* XOR-MAPPED-ADDRESS */
	out[24] = 0; out[25] = 1;
	wh_put16(out + 26, (port ^ 0x2112u) & 0xffff);
	out[28] = (uint8_t)(x >> 24); out[29] = (uint8_t)(x >> 16); out[30] = (uint8_t)(x >> 8); out[31] = (uint8_t)x;
	return stun_finish(out, 32, key);
}

/* ---- base64 (the sprop-parameter-sets of the RTSP SDP) ---- */
static int wh_b64(const char *s, size_t n, uint8_t *out, size_t max)
{
	size_t i, o = 0;
	uint32_t acc = 0;
	int bits = 0;

	for (i = 0; i < n; i++) {
		int v;
		char c = s[i];

		if (c >= 'A' && c <= 'Z') v = c - 'A';
		else if (c >= 'a' && c <= 'z') v = c - 'a' + 26;
		else if (c >= '0' && c <= '9') v = c - '0' + 52;
		else if (c == '+') v = 62;
		else if (c == '/') v = 63;
		else if (c == '=') break;
		else return -1;
		acc = acc << 6 | (uint32_t)v; bits += 6;
		if (bits >= 8) {
			bits -= 8;
			if (o >= max) return -1;
			out[o++] = (uint8_t)(acc >> bits);
		}
	}
	return (int)o;
}

/* ---- SDP ---- */
#define SDP_MEDIA_MAX 4
#define SDP_PT_MAX 16

struct sdp_pt { int pt; int h264, mode1, pcma; char plid[8]; char fmtp[160]; };

struct sdp_media {
	char kind[16];			/* video, audio, application ... */
	char tail[96];			/* the m-line after the port: protocol and formats, echoed when the section is rejected */
	char mid[32];
	struct sdp_pt pts[SDP_PT_MAX];
	int npt;
};

struct sdp_offer {
	char ufrag[64], pwd[128];
	char fp[128];			/* the fingerprint value: "AA:BB:..." (sha-256 only) */
	struct sdp_media m[SDP_MEDIA_MAX];
	int nm;
};

static int sdp_pt_find(struct sdp_media *m, int pt, int add)
{
	int i;

	for (i = 0; i < m->npt; i++) if (m->pts[i].pt == pt) return i;
	if (!add || m->npt >= SDP_PT_MAX) return -1;
	memset(&m->pts[m->npt], 0, sizeof m->pts[0]);
	m->pts[m->npt].pt = pt;
	return m->npt++;
}

static void sdp_copy(char *d, size_t dn, const char *s, size_t n)
{
	if (n >= dn) n = dn - 1;
	memcpy(d, s, n); d[n] = 0;
}

/* 0 = parsed (at least one media section), -1 = not an SDP offer we can answer */
static int sdp_parse_offer(const char *txt, struct sdp_offer *o)
{
	const char *p = txt;
	struct sdp_media *cur = NULL;

	memset(o, 0, sizeof *o);
	while (*p) {
		const char *e = strchr(p, '\n');
		size_t n = e ? (size_t)(e - p) : strlen(p);
		const char *l = p;

		p = e ? e + 1 : p + n;
		while (n && (l[n - 1] == '\r' || l[n - 1] == ' ')) n--;
		if (n < 3 || l[1] != '=') continue;
		if (l[0] == 'm') {
			const char *sp;
			size_t kn;
			char *c;

			if (o->nm >= SDP_MEDIA_MAX) return -1;
			cur = &o->m[o->nm++];
			sp = memchr(l + 2, ' ', n - 2);
			kn = sp ? (size_t)(sp - (l + 2)) : n - 2;
			sdp_copy(cur->kind, sizeof cur->kind, l + 2, kn);
			if (sp) {		/* skip the port */
				const char *t = sp + 1, *end = l + n;

				while (t < end && *t != ' ') t++;
				if (t < end) t++;
				sdp_copy(cur->tail, sizeof cur->tail, t, (size_t)(end - t));
				/* the formats: payload types of an RTP profile */
				if (strstr(cur->tail, "RTP/")) {
					c = strchr(cur->tail, ' ');
					while (c && *c) {
						int v;

						while (*c == ' ') c++;
						if (!isdigit((unsigned char)*c)) break;
						v = atoi(c);
						sdp_pt_find(cur, v, 1);
						c = strchr(c, ' ');
					}
				}
			}
			continue;
		}
		if (l[0] != 'a') continue;
		l += 2; n -= 2;
#define IS(k) (n > sizeof(k) - 1 && !strncmp(l, k, sizeof(k) - 1))
		if (IS("ice-ufrag:")) { if (!o->ufrag[0]) sdp_copy(o->ufrag, sizeof o->ufrag, l + 10, n - 10); }
		else if (IS("ice-pwd:")) { if (!o->pwd[0]) sdp_copy(o->pwd, sizeof o->pwd, l + 8, n - 8); }
		else if (IS("fingerprint:sha-256 ")) { if (!o->fp[0]) sdp_copy(o->fp, sizeof o->fp, l + 20, n - 20); }
		else if (cur && IS("mid:")) sdp_copy(cur->mid, sizeof cur->mid, l + 4, n - 4);
		else if (cur && IS("rtpmap:")) {
			int pt = atoi(l + 7), i = sdp_pt_find(cur, pt, 1);
			const char *s = memchr(l, ' ', n);

			if (i >= 0 && s) {
				s++;
				if (!strncasecmp(s, "H264/", 5)) cur->pts[i].h264 = 1;
				else if (!strncasecmp(s, "PCMA/8000", 9)) cur->pts[i].pcma = 1;
			}
		} else if (cur && IS("fmtp:")) {
			int pt = atoi(l + 5), i = sdp_pt_find(cur, pt, 0);
			const char *s = memchr(l, ' ', n);

			if (i >= 0 && s) {
				char tmp[160];
				const char *q;

				s++;
				sdp_copy(cur->pts[i].fmtp, sizeof cur->pts[i].fmtp, s, n - (size_t)(s - l));
				sdp_copy(tmp, sizeof tmp, s, n - (size_t)(s - l));
				if (strstr(tmp, "packetization-mode=1")) cur->pts[i].mode1 = 1;
				q = strstr(tmp, "profile-level-id=");
				if (q) sdp_copy(cur->pts[i].plid, sizeof cur->pts[i].plid, q + 17, 6);
			}
		}
#undef IS
	}
	if (!o->nm || !o->ufrag[0] || !o->pwd[0] || !o->fp[0]) return -1;
	return 0;
}

/* the payload type of H.264 packetization mode 1 to answer with: the one whose profile-level-id starts with the
 * source's profile (prefer, 4 hex digits, e.g. "4d00" = Main), else the first; -1 = none */
static int sdp_pick_h264(const struct sdp_media *m, const char *prefer)
{
	int i, first = -1;

	for (i = 0; i < m->npt; i++) {
		const struct sdp_pt *t = &m->pts[i];

		if (!t->h264 || !t->mode1) continue;
		if (first < 0) first = i;
		if (prefer && prefer[0] && !strncasecmp(t->plid, prefer, 4)) return i;
	}
	return first;
}

static int sdp_pick_pcma(const struct sdp_media *m)
{
	int i;

	for (i = 0; i < m->npt; i++) if (m->pts[i].pcma || m->pts[i].pt == 8) return i;
	return -1;
}

struct sdp_answer_in {
	const struct sdp_offer *offer;
	const char *ufrag, *pwd;	/* ours */
	const char *fp;			/* "AA:BB:..." of our certificate */
	const char *ip;			/* dotted quad of the LAN interface */
	unsigned port;			/* UDP port */
	int v_media, v_idx;		/* index of the media section (and of the payload type in it) that carries the video */
	int a_media, a_idx;		/* same for the audio; a_media < 0: none */
	uint32_t v_ssrc, a_ssrc;
	unsigned long sess_id;
};

/* the answer: every section of the offer in the same order; the ones we do not send are rejected (port 0).
 * Returns the length, 0 if the buffer is too small. */
static size_t sdp_answer(char *out, size_t max, const struct sdp_answer_in *a)
{
	size_t n = 0;
	int i;
	char bundle[160] = "";

#define PR(...) do { int r_ = snprintf(out + n, max - n, __VA_ARGS__); if (r_ < 0 || (size_t)r_ >= max - n) return 0; n += (size_t)r_; } while (0)
	for (i = 0; i < a->offer->nm; i++) {
		if ((i == a->v_media || i == a->a_media) && strlen(bundle) + strlen(a->offer->m[i].mid) + 2 < sizeof bundle) {
			strcat(bundle, " "); strcat(bundle, a->offer->m[i].mid);
		}
	}
	PR("v=0\r\no=- %lu 1 IN IP4 %s\r\ns=-\r\nt=0 0\r\n", a->sess_id, a->ip);
	PR("a=group:BUNDLE%s\r\na=ice-lite\r\na=msid-semantic: WMS\r\n", bundle);
	for (i = 0; i < a->offer->nm; i++) {
		const struct sdp_media *m = &a->offer->m[i];
		int vid = i == a->v_media, aud = i == a->a_media;

		if (!vid && !aud) {
			PR("m=%s 0 %s\r\nc=IN IP4 0.0.0.0\r\na=mid:%s\r\na=inactive\r\n", m->kind, m->tail, m->mid);
			continue;
		}
		{
			const struct sdp_pt *t = &m->pts[vid ? a->v_idx : a->a_idx];

			PR("m=%s 9 UDP/TLS/RTP/SAVPF %d\r\nc=IN IP4 %s\r\n", m->kind, t->pt, a->ip);
			PR("a=ice-ufrag:%s\r\na=ice-pwd:%s\r\na=fingerprint:sha-256 %s\r\na=setup:passive\r\n", a->ufrag, a->pwd, a->fp);
			PR("a=mid:%s\r\na=sendonly\r\na=rtcp-mux\r\n", m->mid);
			if (vid) PR("a=rtpmap:%d H264/90000\r\na=fmtp:%d %s\r\n", t->pt, t->pt, t->fmtp);
			else PR("a=rtpmap:%d PCMA/8000\r\n", t->pt);
			PR("a=ssrc:%u cname:tc100\r\n", (unsigned)(vid ? a->v_ssrc : a->a_ssrc));
			PR("a=candidate:1 1 udp 2130706431 %s %u typ host\r\na=end-of-candidates\r\n", a->ip, a->port);
		}
	}
#undef PR
	return n;
}
#endif
