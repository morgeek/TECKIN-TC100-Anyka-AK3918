/* md5crypt.h: MD5 (RFC 1321), the "$1$" MD5 crypt of busybox httpd -m / glibc crypt(), and a Base64 decoder, with no C
 * library (httpfront is freestanding). Included by httpfront.c and by its host test (tests/test_httpfront_auth.py). */
#ifndef HF_MD5CRYPT_H
#define HF_MD5CRYPT_H

struct md5 { unsigned int s[4]; unsigned int n[2]; unsigned char b[64]; };

static void md5_block(unsigned int s[4], const unsigned char *p)
{
	static const unsigned int K[64] = {
		0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501,
		0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821,
		0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa, 0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
		0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed, 0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a,
		0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70,
		0x289b7ec6, 0xeaa127fa, 0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665,
		0xf4292244, 0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
		0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391 };
	static const unsigned char R[16] = { 7, 12, 17, 22, 5, 9, 14, 20, 4, 11, 16, 23, 6, 10, 15, 21 };
	unsigned int w[16], a = s[0], b = s[1], c = s[2], d = s[3], f, t;
	int i, g;

	for (i = 0; i < 16; i++)
		w[i] = p[i * 4] | p[i * 4 + 1] << 8 | (unsigned int)p[i * 4 + 2] << 16 | (unsigned int)p[i * 4 + 3] << 24;
	for (i = 0; i < 64; i++) {
		if (i < 16) { f = (b & c) | (~b & d); g = i; }
		else if (i < 32) { f = (d & b) | (~d & c); g = (5 * i + 1) & 15; }
		else if (i < 48) { f = b ^ c ^ d; g = (3 * i + 5) & 15; }
		else { f = c ^ (b | ~d); g = (7 * i) & 15; }
		t = d; d = c; c = b;
		f += a + K[i] + w[g];
		b += f << R[(i >> 4) * 4 + (i & 3)] | f >> (32 - R[(i >> 4) * 4 + (i & 3)]);
		a = t;
	}
	s[0] += a; s[1] += b; s[2] += c; s[3] += d;
}

static void md5_init(struct md5 *m)
{
	m->s[0] = 0x67452301; m->s[1] = 0xefcdab89; m->s[2] = 0x98badcfe; m->s[3] = 0x10325476;
	m->n[0] = m->n[1] = 0;
}

static void md5_update(struct md5 *m, const void *v, unsigned int len)
{
	const unsigned char *p = v;
	unsigned int have = m->n[0] & 63;

	if ((m->n[0] += len) < len) m->n[1]++;
	while (len--) {
		m->b[have++] = *p++;
		if (have == 64) { md5_block(m->s, m->b); have = 0; }
	}
}

static void md5_final(struct md5 *m, unsigned char out[16])
{
	unsigned int bits0 = m->n[0] << 3, bits1 = m->n[1] << 3 | m->n[0] >> 29, have = m->n[0] & 63;
	unsigned char z = 0x80, len[8];
	int i;

	for (i = 0; i < 4; i++) { len[i] = (unsigned char)(bits0 >> (8 * i)); len[i + 4] = (unsigned char)(bits1 >> (8 * i)); }
	md5_update(m, &z, 1);
	z = 0;
	have = (have + 1) & 63;
	while (have != 56) { md5_update(m, &z, 1); have = (have + 1) & 63; }
	md5_update(m, len, 8);
	for (i = 0; i < 16; i++) out[i] = (unsigned char)(m->s[i >> 2] >> (8 * (i & 3)));
}

static unsigned int hf_len(const char *s) { unsigned int n = 0; while (s[n]) n++; return n; }

static void to64(char **o, unsigned int v, int n)
{
	static const char A[] = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";

	while (n-- > 0) { *(*o)++ = A[v & 0x3f]; v >>= 6; }
}

/* "$1$<salt>$<22 chars>" of pw with the salt of setting ("$1$salt$..." or "$1$salt"); out: 64 bytes at least.
 * Returns 0, or -1 when setting is not an MD5 crypt string. */
static int md5crypt(const char *pw, const char *setting, char *out)
{
	struct md5 c, c1;
	unsigned char f[16];
	const char *salt;
	unsigned int sl = 0, pl = hf_len(pw), i, k3, k7;
	char *o = out;
	int k;

	if (setting[0] != '$' || setting[1] != '1' || setting[2] != '$') return -1;
	salt = setting + 3;
	while (salt[sl] && salt[sl] != '$' && sl < 8) sl++;
	md5_init(&c);
	md5_update(&c, pw, pl); md5_update(&c, "$1$", 3); md5_update(&c, salt, sl);
	md5_init(&c1);
	md5_update(&c1, pw, pl); md5_update(&c1, salt, sl); md5_update(&c1, pw, pl);
	md5_final(&c1, f);
	for (k = (int)pl; k > 0; k -= 16) md5_update(&c, f, k > 16 ? 16 : (unsigned int)k);
	for (i = pl; i; i >>= 1) md5_update(&c, (i & 1) ? "" : pw, 1);	/* "" gives its 0 byte */
	md5_final(&c, f);
	for (i = 0, k3 = 0, k7 = 0; i < 1000; i++) {	/* k3 = i % 3, k7 = i % 7 without a division (no libgcc) */
		md5_init(&c1);
		if (i & 1) md5_update(&c1, pw, pl); else md5_update(&c1, f, 16);
		if (k3) md5_update(&c1, salt, sl);
		if (k7) md5_update(&c1, pw, pl);
		if (i & 1) md5_update(&c1, f, 16); else md5_update(&c1, pw, pl);
		md5_final(&c1, f);
		if (++k3 == 3) k3 = 0;
		if (++k7 == 7) k7 = 0;
	}
	*o++ = '$'; *o++ = '1'; *o++ = '$';
	for (i = 0; i < sl; i++) *o++ = salt[i];
	*o++ = '$';
	to64(&o, (unsigned int)f[0] << 16 | f[6] << 8 | f[12], 4);
	to64(&o, (unsigned int)f[1] << 16 | f[7] << 8 | f[13], 4);
	to64(&o, (unsigned int)f[2] << 16 | f[8] << 8 | f[14], 4);
	to64(&o, (unsigned int)f[3] << 16 | f[9] << 8 | f[15], 4);
	to64(&o, (unsigned int)f[4] << 16 | f[10] << 8 | f[5], 4);
	to64(&o, f[11], 2);
	*o = 0;
	return 0;
}

/* Base64 (RFC 4648) of s, up to the first character outside the alphabet, into out (max bytes, NUL added);
 * returns the length, -1 when it does not fit */
static int b64dec(const char *s, char *out, int max)
{
	unsigned int acc = 0;
	int bits = 0, n = 0, v;

	for (; *s; s++) {
		char ch = *s;

		if (ch >= 'A' && ch <= 'Z') v = ch - 'A';
		else if (ch >= 'a' && ch <= 'z') v = ch - 'a' + 26;
		else if (ch >= '0' && ch <= '9') v = ch - '0' + 52;
		else if (ch == '+') v = 62;
		else if (ch == '/') v = 63;
		else break;
		acc = acc << 6 | (unsigned int)v;
		bits += 6;
		if (bits >= 8) {
			bits -= 8;
			if (n >= max - 1) return -1;
			out[n++] = (char)(acc >> bits);
		}
	}
	out[n] = 0;
	return n;
}

#endif
