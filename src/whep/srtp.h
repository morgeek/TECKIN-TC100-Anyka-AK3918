/* srtp.h: the SRTP protection of WebRTC (RFC 3711, profile SRTP_AES128_CM_HMAC_SHA1_80) in plain C, for the WHEP
 * gateway of item 35 (src/whep) and its CPU bench (srtp_bench.c). AES-128 (table-based encryption only, all that the
 * counter mode needs), SHA-1 and HMAC-SHA1, the SRTP key derivation and the protection of one RTP packet:
 * payload encrypted with AES-CM, then an 80-bit HMAC-SHA1 tag over header + payload + rollover counter.
 * No library: it builds for the host (tests) and for the camera with the same code. Not constant-time (AES tables):
 * the keys only protect a video stream on the local network. */
#ifndef TC100_SRTP_H
#define TC100_SRTP_H
#include <stdint.h>
#include <string.h>

/* ---- AES-128, encryption ---- */
struct aes128 { uint32_t rk[44]; };

static uint8_t aes_sbox[256];
static uint32_t aes_te[4][256];

static uint8_t aes_xt(uint8_t x) { return (uint8_t)((x << 1) ^ ((x & 0x80) ? 0x1b : 0)); }

static void aes_tables(void)
{
	uint8_t p = 1, q = 1, s;
	int i;

	if (aes_sbox[0]) return;			/* built (sbox[0] = 0x63) */
	do {						/* p walks the field by 3, q by 1/3 */
		p = (uint8_t)(p ^ (p << 1) ^ ((p & 0x80) ? 0x1b : 0));
		q ^= (uint8_t)(q << 1); q ^= (uint8_t)(q << 2); q ^= (uint8_t)(q << 4);
		if (q & 0x80) q ^= 0x09;
		s = (uint8_t)(q ^ (uint8_t)(q << 1 | q >> 7) ^ (uint8_t)(q << 2 | q >> 6) ^ (uint8_t)(q << 3 | q >> 5) ^
			      (uint8_t)(q << 4 | q >> 4));
		aes_sbox[p] = (uint8_t)(s ^ 0x63);
	} while (p != 1);
	aes_sbox[0] = 0x63;
	for (i = 0; i < 256; i++) {
		uint8_t a = aes_sbox[i], b = aes_xt(a), c = (uint8_t)(a ^ b);
		uint32_t t = (uint32_t)b << 24 | (uint32_t)a << 16 | (uint32_t)a << 8 | c;

		aes_te[0][i] = t;
		aes_te[1][i] = t >> 8 | t << 24;
		aes_te[2][i] = t >> 16 | t << 16;
		aes_te[3][i] = t >> 24 | t << 8;
	}
}

static uint32_t aes_be32(const uint8_t *p) { return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3]; }
static void aes_put32(uint8_t *p, uint32_t v) { p[0] = (uint8_t)(v >> 24); p[1] = (uint8_t)(v >> 16); p[2] = (uint8_t)(v >> 8); p[3] = (uint8_t)v; }

static void aes128_key(struct aes128 *k, const uint8_t key[16])
{
	static const uint8_t rcon[10] = { 1, 2, 4, 8, 16, 32, 64, 128, 0x1b, 0x36 };
	int i;

	aes_tables();
	for (i = 0; i < 4; i++) k->rk[i] = aes_be32(key + 4 * i);
	for (i = 4; i < 44; i++) {
		uint32_t t = k->rk[i - 1];

		if (i % 4 == 0)
			t = ((uint32_t)aes_sbox[t >> 16 & 255] << 24 | (uint32_t)aes_sbox[t >> 8 & 255] << 16 |
			     (uint32_t)aes_sbox[t & 255] << 8 | aes_sbox[t >> 24]) ^ (uint32_t)rcon[i / 4 - 1] << 24;
		k->rk[i] = k->rk[i - 4] ^ t;
	}
}

static void aes128_encrypt(const struct aes128 *k, const uint8_t in[16], uint8_t out[16])
{
	const uint32_t *rk = k->rk;
	uint32_t s0 = aes_be32(in) ^ rk[0], s1 = aes_be32(in + 4) ^ rk[1], s2 = aes_be32(in + 8) ^ rk[2],
		 s3 = aes_be32(in + 12) ^ rk[3], t0, t1, t2, t3;
	int r;

	for (r = 1; r < 10; r++) {
		rk += 4;
		t0 = aes_te[0][s0 >> 24] ^ aes_te[1][s1 >> 16 & 255] ^ aes_te[2][s2 >> 8 & 255] ^ aes_te[3][s3 & 255] ^ rk[0];
		t1 = aes_te[0][s1 >> 24] ^ aes_te[1][s2 >> 16 & 255] ^ aes_te[2][s3 >> 8 & 255] ^ aes_te[3][s0 & 255] ^ rk[1];
		t2 = aes_te[0][s2 >> 24] ^ aes_te[1][s3 >> 16 & 255] ^ aes_te[2][s0 >> 8 & 255] ^ aes_te[3][s1 & 255] ^ rk[2];
		t3 = aes_te[0][s3 >> 24] ^ aes_te[1][s0 >> 16 & 255] ^ aes_te[2][s1 >> 8 & 255] ^ aes_te[3][s2 & 255] ^ rk[3];
		s0 = t0; s1 = t1; s2 = t2; s3 = t3;
	}
	rk += 4;
#define AES_LAST(a, b, c, d, w) ((uint32_t)aes_sbox[(a) >> 24] << 24 ^ (uint32_t)aes_sbox[(b) >> 16 & 255] << 16 ^ \
				 (uint32_t)aes_sbox[(c) >> 8 & 255] << 8 ^ aes_sbox[(d) & 255]) ^ (w)
	aes_put32(out, AES_LAST(s0, s1, s2, s3, rk[0]));
	aes_put32(out + 4, AES_LAST(s1, s2, s3, s0, rk[1]));
	aes_put32(out + 8, AES_LAST(s2, s3, s0, s1, rk[2]));
	aes_put32(out + 12, AES_LAST(s3, s0, s1, s2, rk[3]));
#undef AES_LAST
}

/* ---- SHA-1, HMAC-SHA1 ---- */
struct sha1 { uint32_t h[5]; uint64_t len; uint8_t buf[64]; unsigned n; };

static uint32_t sha1_rol(uint32_t x, int n) { return x << n | x >> (32 - n); }

static void sha1_block(struct sha1 *c, const uint8_t *p)
{
	uint32_t w[80], a = c->h[0], b = c->h[1], d = c->h[3], e = c->h[4], cc = c->h[2], f, k, t;
	int i;

	for (i = 0; i < 16; i++) w[i] = aes_be32(p + 4 * i);
	for (; i < 80; i++) w[i] = sha1_rol(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
	for (i = 0; i < 80; i++) {
		if (i < 20) { f = (b & cc) | (~b & d); k = 0x5a827999; }
		else if (i < 40) { f = b ^ cc ^ d; k = 0x6ed9eba1; }
		else if (i < 60) { f = (b & cc) | (b & d) | (cc & d); k = 0x8f1bbcdc; }
		else { f = b ^ cc ^ d; k = 0xca62c1d6; }
		t = sha1_rol(a, 5) + f + e + k + w[i];
		e = d; d = cc; cc = sha1_rol(b, 30); b = a; a = t;
	}
	c->h[0] += a; c->h[1] += b; c->h[2] += cc; c->h[3] += d; c->h[4] += e;
}

static void sha1_init(struct sha1 *c)
{
	static const uint32_t h0[5] = { 0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476, 0xc3d2e1f0 };

	memcpy(c->h, h0, sizeof h0); c->len = 0; c->n = 0;
}

static void sha1_update(struct sha1 *c, const uint8_t *p, size_t n)
{
	c->len += n;
	while (n) {
		size_t m = 64 - c->n < n ? 64 - c->n : n;

		if (c->n == 0 && n >= 64) { sha1_block(c, p); p += 64; n -= 64; continue; }
		memcpy(c->buf + c->n, p, m); c->n += (unsigned)m; p += m; n -= m;
		if (c->n == 64) { sha1_block(c, c->buf); c->n = 0; }
	}
}

static void sha1_final(struct sha1 *c, uint8_t out[20])
{
	uint64_t bits = c->len * 8;
	uint8_t z = 0x80, l[8];
	int i;

	sha1_update(c, &z, 1);
	z = 0;
	while (c->n != 56) sha1_update(c, &z, 1);
	for (i = 0; i < 8; i++) l[i] = (uint8_t)(bits >> (56 - 8 * i));
	sha1_update(c, l, 8);
	for (i = 0; i < 5; i++) aes_put32(out + 4 * i, c->h[i]);
}

/* the inner and outer states after the padded key: one per session, then each packet costs only its own blocks */
struct hmac_sha1 { struct sha1 in, out; };

static void hmac_sha1_key(struct hmac_sha1 *m, const uint8_t *key, size_t n)
{
	uint8_t k[64], pad[64];
	int i;

	memset(k, 0, sizeof k);
	if (n > 64) { struct sha1 c; sha1_init(&c); sha1_update(&c, key, n); sha1_final(&c, k); }
	else memcpy(k, key, n);
	for (i = 0; i < 64; i++) pad[i] = (uint8_t)(k[i] ^ 0x36);
	sha1_init(&m->in); sha1_update(&m->in, pad, 64);
	for (i = 0; i < 64; i++) pad[i] = (uint8_t)(k[i] ^ 0x5c);
	sha1_init(&m->out); sha1_update(&m->out, pad, 64);
}

/* HMAC over a then b (b may be empty) */
static void hmac_sha1(const struct hmac_sha1 *m, const uint8_t *a, size_t an, const uint8_t *b, size_t bn,
		      uint8_t out[20])
{
	struct sha1 c = m->in;
	uint8_t d[20];

	sha1_update(&c, a, an);
	if (bn) sha1_update(&c, b, bn);
	sha1_final(&c, d);
	c = m->out;
	sha1_update(&c, d, 20);
	sha1_final(&c, out);
}

/* ---- SRTP (RFC 3711), AES_CM_128_HMAC_SHA1_80 ---- */
struct srtp_ctx {
	struct aes128 enc;		/* session encryption key */
	uint8_t salt[14];		/* session salt */
	struct hmac_sha1 auth;		/* session authentication key (160 bits) */
	uint32_t roc;			/* rollover counter */
	uint16_t last_seq;
	int started;
};

/* AES-CM keystream XORed over p[0..n): IV = salt XOR (SSRC << 64) XOR (index << 16), then counter blocks */
static void srtp_aes_cm(const struct aes128 *k, const uint8_t salt[14], uint32_t ssrc, uint64_t index, uint8_t *p,
			size_t n)
{
	uint8_t iv[16], ks[16];
	uint32_t blk = 0;
	size_t i, j;

	memset(iv, 0, sizeof iv);
	memcpy(iv, salt, 14);
	for (i = 0; i < 4; i++) iv[4 + i] ^= (uint8_t)(ssrc >> (24 - 8 * i));
	for (i = 0; i < 6; i++) iv[8 + i] ^= (uint8_t)(index >> (40 - 8 * i));
	for (i = 0; i < n; i += 16, blk++) {
		iv[14] = (uint8_t)(blk >> 8); iv[15] = (uint8_t)blk;
		aes128_encrypt(k, iv, ks);
		for (j = 0; j < 16 && i + j < n; j++) p[i + j] ^= ks[j];
	}
}

/* the session keys from the master key and salt of the DTLS-SRTP export (RFC 3711 4.3, key derivation rate 0) */
static void srtp_init(struct srtp_ctx *s, const uint8_t master_key[16], const uint8_t master_salt[14])
{
	struct aes128 mk;
	uint8_t x[32], salt[14];
	int label;

	memset(s, 0, sizeof *s);
	aes128_key(&mk, master_key);
	for (label = 0; label < 3; label++) {
		size_t n = label == 0 ? 16 : label == 1 ? 20 : 14;

		memcpy(salt, master_salt, 14);
		salt[7] ^= (uint8_t)label;
		memset(x, 0, sizeof x);
		srtp_aes_cm(&mk, salt, 0, 0, x, n);	/* x = keystream: the derived key */
		if (label == 0) aes128_key(&s->enc, x);
		else if (label == 1) hmac_sha1_key(&s->auth, x, 20);
		else memcpy(s->salt, x, 14);
	}
}

/* protect one RTP packet in place: p holds n bytes (12-byte header, no CSRC or extension) and room for 10 more;
 * returns the SRTP length (n + 10) */
static size_t srtp_protect(struct srtp_ctx *s, uint8_t *p, size_t n)
{
	uint16_t seq = (uint16_t)(p[2] << 8 | p[3]);
	uint32_t ssrc = aes_be32(p + 8);
	uint8_t roc[4], tag[20];
	size_t h = 12 + 4 * (size_t)(p[0] & 15);

	if (s->started && seq < s->last_seq && (uint16_t)(s->last_seq - seq) > 0x8000) s->roc++;	/* wrapped */
	s->last_seq = seq; s->started = 1;
	srtp_aes_cm(&s->enc, s->salt, ssrc, (uint64_t)s->roc << 16 | seq, p + h, n - h);
	aes_put32(roc, s->roc);
	hmac_sha1(&s->auth, p, n, roc, 4, tag);
	memcpy(p + n, tag, 10);
	return n + 10;
}
#endif
