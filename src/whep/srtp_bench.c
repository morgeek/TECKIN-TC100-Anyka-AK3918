/* srtp-bench: what WebRTC's SRTP would cost the camera's processor (item 35 of the implementer list, first step:
 * "measure before building"). Encrypts and authenticates RTP packets of 1200 bytes the way a browser expects them
 * (SRTP_AES128_CM_HMAC_SHA1_80, srtp.h) for a few seconds, then prints the throughput and the share of one CPU it
 * would take at the camera's bit rates.
 *   srtp-bench [SECONDS] [KBITS...]     defaults: 5 s; 600 (sub stream), 1200 and 2000 (main stream) kbit/s
 *   srtp-bench -t                       self-test with the published vectors (FIPS-197, RFC 3174, RFC 2202, RFC 3711)
 * Build for the camera (static, any user space): arm-linux-gnueabi-gcc -O2 -static -march=armv5te -mtune=arm926ej-s
 * -o srtp-bench srtp_bench.c. Run it while the stream runs, as on a normal day: the result includes the cache
 * misses the encoder causes. */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "srtp.h"

static double now_s(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return (double)t.tv_sec + (double)t.tv_nsec / 1e9;
}

static int hex(const char *h, uint8_t *out)
{
	int n = 0;

	for (; h[0] && h[1]; h += 2) {
		unsigned v;

		if (sscanf(h, "%2x", &v) != 1) return -1;
		out[n++] = (uint8_t)v;
	}
	return n;
}

static int check(const char *what, const uint8_t *got, const char *want_hex)
{
	uint8_t w[64];
	int n = hex(want_hex, w), ok = n > 0 && !memcmp(got, w, (size_t)n);

	printf("%-34s %s\n", what, ok ? "ok" : "FAILED");
	return ok ? 0 : 1;
}

static int self_test(void)
{
	struct aes128 k;
	struct sha1 c;
	struct hmac_sha1 m;
	uint8_t key[32], in[64], out[64], salt[14];
	int bad = 0;

	hex("000102030405060708090a0b0c0d0e0f", key); hex("00112233445566778899aabbccddeeff", in);
	aes128_key(&k, key); aes128_encrypt(&k, in, out);
	bad += check("AES-128 (FIPS-197 C.1)", out, "69c4e0d86a7b0430d8cdb78070b4c55a");
	hex("2b7e151628aed2a6abf7158809cf4f3c", key); hex("3243f6a8885a308d313198a2e0370734", in);
	aes128_key(&k, key); aes128_encrypt(&k, in, out);
	bad += check("AES-128 (FIPS-197 B)", out, "3925841d02dc09fbdc118597196a0b32");
	sha1_init(&c); sha1_update(&c, (const uint8_t *)"abc", 3); sha1_final(&c, out);
	bad += check("SHA-1 \"abc\" (RFC 3174)", out, "a9993e364706816aba3e25717850c26c9cd0d89d");
	sha1_init(&c);
	sha1_update(&c, (const uint8_t *)"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq", 56);
	sha1_final(&c, out);
	bad += check("SHA-1 two blocks (RFC 3174)", out, "84983e441c3bd26ebaae4aa1f95129e5e54670f1");
	memset(key, 0x0b, 20); hmac_sha1_key(&m, key, 20);
	hmac_sha1(&m, (const uint8_t *)"Hi There", 8, NULL, 0, out);
	bad += check("HMAC-SHA1 case 1 (RFC 2202)", out, "b617318655057264e28bc0b6fb378c8ef146be00");
	hmac_sha1_key(&m, (const uint8_t *)"Jefe", 4);
	hmac_sha1(&m, (const uint8_t *)"what do ya want ", 16, (const uint8_t *)"for nothing?", 12, out);
	bad += check("HMAC-SHA1 case 2 (RFC 2202)", out, "effcdf6ae5eb2fa2d27416d5f184df9c259a7c79");
	/* RFC 3711 B.2: AES-CM keystream, session key and salt given, SSRC 0, index 0 */
	hex("2b7e151628aed2a6abf7158809cf4f3c", key); aes128_key(&k, key);
	hex("f0f1f2f3f4f5f6f7f8f9fafbfcfd", salt);
	memset(out, 0, 48); srtp_aes_cm(&k, salt, 0, 0, out, 48);
	bad += check("SRTP AES-CM keystream (RFC 3711 B.2)", out,
		     "e03ead0935c95e80e166b16dd92b4eb4d23513162b02d0f72a43a2fe4a5f97ab41e95b3bb0a2e8dd477901e4fca894c0");
	/* RFC 3711 B.3: key derivation */
	hex("e1f97a0d3e018be0d64fa32c06de4139", key); hex("0ec675ad498afeebb6960b3aabe6", salt);
	{
		struct aes128 mk;
		uint8_t s2[14];

		aes128_key(&mk, key);
		memset(out, 0, 16); memcpy(s2, salt, 14); srtp_aes_cm(&mk, s2, 0, 0, out, 16);
		bad += check("SRTP cipher key (RFC 3711 B.3)", out, "c61e7a93744f39ee10734afe3ff7a087");
		memset(out, 0, 14); memcpy(s2, salt, 14); s2[7] ^= 2; srtp_aes_cm(&mk, s2, 0, 0, out, 14);
		bad += check("SRTP salt (RFC 3711 B.3)", out, "30cbbc08863d8c85d49db34a9ae1");
		memset(out, 0, 20); memcpy(s2, salt, 14); s2[7] ^= 1; srtp_aes_cm(&mk, s2, 0, 0, out, 20);
		bad += check("SRTP auth key (RFC 3711 B.3)", out, "cebe321f6ff7716b6fd4ab49af256a156d38baa4");
	}
	printf(bad ? "self-test: %d FAILED\n" : "self-test: all ok\n", bad);
	return bad ? 1 : 0;
}

int main(int argc, char **argv)
{
	static uint8_t pkt[1200 + 10];
	uint8_t mkey[16], msalt[14];
	struct srtp_ctx s;
	double secs = 5, t0, t1, rate;
	unsigned long n = 0;
	int i, nk = 0;
	long kbits[8];

	if (argc > 1 && !strcmp(argv[1], "-t")) return self_test();
	if (argc > 1) secs = atof(argv[1]);
	for (i = 2; i < argc && nk < 8; i++) kbits[nk++] = atol(argv[i]);
	if (!nk) { kbits[0] = 600; kbits[1] = 1200; kbits[2] = 2000; nk = 3; }
	if (secs < 0.5) secs = 0.5;

	for (i = 0; i < 16; i++) mkey[i] = (uint8_t)(i * 7 + 1);
	for (i = 0; i < 14; i++) msalt[i] = (uint8_t)(i * 13 + 5);
	srtp_init(&s, mkey, msalt);
	for (i = 0; i < 1200; i++) pkt[i] = (uint8_t)i;
	pkt[0] = 0x80; pkt[1] = 96; pkt[8] = 0x12; pkt[9] = 0x34; pkt[10] = 0x56; pkt[11] = 0x78;

	t0 = now_s();
	do {
		int j;

		for (j = 0; j < 64; j++, n++) {
			pkt[2] = (uint8_t)(n >> 8); pkt[3] = (uint8_t)n;	/* sequence number */
			srtp_protect(&s, pkt, 1200);
		}
		t1 = now_s();
	} while (t1 - t0 < secs);
	rate = (double)n * 1200 / (t1 - t0);		/* protected bytes per second */
	printf("srtp-bench: %lu packets of 1200 bytes in %.2f s: %.0f packets/s, %.2f MB/s, %.1f us per packet\n",
	       n, t1 - t0, n / (t1 - t0), rate / 1e6, (t1 - t0) / n * 1e6);
	for (i = 0; i < nk; i++)
		printf("  stream of %ld kbit/s: %.1f %% of one CPU\n", kbits[i], 100.0 * kbits[i] * 1000 / 8 / rate);
	return 0;
}
