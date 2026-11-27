/* tc100-sigcheck: Ed25519 signature check of the update packages (docs/linux-port/upgrade-3.2/sign.md).
 *
 * Camera build (musl, static code from Monocypher 4.0.2, BSD-2-Clause / CC0):
 *   tc100-sigcheck verify FILE SIGFILE KEY...   KEY = a public key file (*.pub) or a folder (its *.pub files)
 *   tc100-sigcheck id KEYFILE                   the short id (8 hex digits) of a public key
 * Host build (-DSIGCHECK_HOST, the owner's tool, scripts/sign_update.py): also
 *   tc100-sigcheck keygen PREFIX                writes PREFIX.key (private, mode 0600) and PREFIX.pub
 *   tc100-sigcheck sign KEYFILE FILE            prints the signature file for FILE on stdout
 *
 * Formats (text, one line each):
 *   public key  "<64 hex> [comment]"                    (*.pub; lines starting with # are ignored)
 *   private key "<64 hex>"                              (*.key: the 32-byte Ed25519 seed)
 *   signature   "tc100-sig1 <keyid: 8 hex> <128 hex>"   (SHA256SUMS.sig, a standard Ed25519 signature of the file's bytes)
 *   keyid       the first 4 bytes of BLAKE2b-256 of the public key
 *
 * verify exit codes (the message is on stdout):
 *   0 "signed <keyid>"           the signature is valid for an installed key
 *   1 "bad ..."                  malformed signature, or made for the id of an installed key and not valid: always refuse
 *   2 "error ..."                usage, unreadable file
 *   3 "unknown <keyid>"          well formed, but no installed key has this id
 *   4 "nokey"                    no usable public key at all
 */
#include <dirent.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include "monocypher.h"
#include "monocypher-ed25519.h"

#define MAXFILE (1024 * 1024)
#define MAXKEYS 32

struct pubkey { uint8_t pk[32]; char id[9]; };

static int hexval(int c)
{
	if (c >= '0' && c <= '9') return c - '0';
	if (c >= 'a' && c <= 'f') return c - 'a' + 10;
	if (c >= 'A' && c <= 'F') return c - 'A' + 10;
	return -1;
}

/* exactly n bytes of hex at s, then end of string, a space or a newline */
static int from_hex(const char *s, uint8_t *out, size_t n)
{
	for (size_t i = 0; i < n; i++) {
		int h = hexval(s[2 * i]), l = h < 0 ? -1 : hexval(s[2 * i + 1]);
		if (h < 0 || l < 0) return -1;
		out[i] = (uint8_t)(h << 4 | l);
	}
	return (s[2 * n] == 0 || s[2 * n] == ' ' || s[2 * n] == '\t' || s[2 * n] == '\n' || s[2 * n] == '\r') ? 0 : -1;
}

static void to_hex(const uint8_t *in, size_t n, char *out)
{
	static const char d[] = "0123456789abcdef";
	for (size_t i = 0; i < n; i++) { out[2 * i] = d[in[i] >> 4]; out[2 * i + 1] = d[in[i] & 15]; }
	out[2 * n] = 0;
}

static void key_id(const uint8_t pk[32], char id[9])
{
	uint8_t h[32];
	crypto_blake2b(h, 32, pk, 32);
	to_hex(h, 4, id);
}

static uint8_t *slurp(const char *path, size_t *len)
{
	FILE *f = fopen(path, "rb");
	if (!f) return NULL;
	uint8_t *b = malloc(MAXFILE + 1);
	if (!b) { fclose(f); return NULL; }
	size_t n = fread(b, 1, MAXFILE + 1, f);
	int err = ferror(f);
	fclose(f);
	if (err || n > MAXFILE) { free(b); return NULL; }
	b[n] = 0;
	*len = n;
	return b;
}

/* first non-empty, non-comment line of a text file; returns a malloc'ed buffer, NUL terminated */
static char *first_line(const char *path)
{
	size_t n;
	char *b = (char *)slurp(path, &n);
	if (!b) return NULL;
	char *p = b;
	while (*p) {
		while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
		if (*p == '#') { while (*p && *p != '\n') p++; continue; }
		break;
	}
	if (!*p) { free(b); return NULL; }
	char *e = p;
	while (*e && *e != '\n') e++;
	*e = 0;
	memmove(b, p, (size_t)(e - p) + 1);
	return b;
}

static int load_pub(const char *path, struct pubkey *k)
{
	char *l = first_line(path);
	if (!l) return -1;
	int r = from_hex(l, k->pk, 32);
	free(l);
	if (r) return -1;
	key_id(k->pk, k->id);
	return 0;
}

static int add_key(const char *path, struct pubkey *keys, int *nk)
{
	if (*nk >= MAXKEYS) return 0;
	if (load_pub(path, &keys[*nk]) == 0) { (*nk)++; return 0; }
	fprintf(stderr, "tc100-sigcheck: %s is not a public key, ignored\n", path);
	return 0;
}

static int collect(const char *arg, struct pubkey *keys, int *nk)
{
	struct stat st;
	if (stat(arg, &st) != 0) return 0;	/* a missing key file or folder: no key from it */
	if (!S_ISDIR(st.st_mode)) return add_key(arg, keys, nk);
	DIR *d = opendir(arg);
	if (!d) return 0;
	struct dirent *e;
	while ((e = readdir(d)) != NULL) {
		size_t l = strlen(e->d_name);
		if (l < 5 || strcmp(e->d_name + l - 4, ".pub") != 0) continue;
		char p[1024];
		if (snprintf(p, sizeof p, "%s/%s", arg, e->d_name) >= (int)sizeof p) continue;
		add_key(p, keys, nk);
	}
	closedir(d);
	return 0;
}

static int cmd_verify(int argc, char **argv)
{
	if (argc < 3) { puts("error usage: verify FILE SIGFILE KEY..."); return 2; }
	struct pubkey keys[MAXKEYS];
	int nk = 0;
	for (int i = 2; i < argc; i++) collect(argv[i], keys, &nk);
	size_t fl, sl;
	uint8_t *msg = slurp(argv[0], &fl);
	if (!msg) { printf("error cannot read %s\n", argv[0]); return 2; }
	uint8_t *sg = slurp(argv[1], &sl);
	if (!sg) { printf("error cannot read %s\n", argv[1]); return 2; }
	/* "tc100-sig1 <8 hex> <128 hex>" and nothing else (a trailing newline or blanks are fine) */
	char *s = (char *)sg;
	uint8_t sig[64];
	char kid[9];
	if (strncmp(s, "tc100-sig1 ", 11) != 0) { puts("bad malformed signature file"); return 1; }
	s += 11;
	uint8_t kb[4];
	if (from_hex(s, kb, 4) != 0 || s[8] != ' ') { puts("bad malformed signature file"); return 1; }
	to_hex(kb, 4, kid);
	s += 9;
	if (from_hex(s, sig, 64) != 0) { puts("bad malformed signature file"); return 1; }
	s += 128;
	while (*s == ' ' || *s == '\t' || *s == '\r' || *s == '\n') s++;
	if (*s) { puts("bad malformed signature file"); return 1; }
	if (nk == 0) { puts("nokey"); return 4; }
	int matched = 0;
	for (int i = 0; i < nk; i++) {
		if (strcmp(keys[i].id, kid) != 0) continue;
		matched = 1;
		if (crypto_ed25519_check(sig, keys[i].pk, msg, fl) == 0) { printf("signed %s\n", kid); return 0; }
	}
	if (!matched) { printf("unknown %s\n", kid); return 3; }
	printf("bad signature for key %s\n", kid);
	return 1;
}

static int cmd_id(int argc, char **argv)
{
	struct pubkey k;
	if (argc < 1 || load_pub(argv[0], &k) != 0) { puts("error not a public key"); return 2; }
	puts(k.id);
	return 0;
}

#ifdef SIGCHECK_HOST
static int rand_bytes(uint8_t *b, size_t n)
{
	FILE *f = fopen("/dev/urandom", "rb");
	if (!f) return -1;
	size_t r = fread(b, 1, n, f);
	fclose(f);
	return r == n ? 0 : -1;
}

static int cmd_keygen(int argc, char **argv)
{
	if (argc < 1) { fputs("usage: keygen PREFIX\n", stderr); return 2; }
	char kp[1024], pp[1024];
	snprintf(kp, sizeof kp, "%s.key", argv[0]);
	snprintf(pp, sizeof pp, "%s.pub", argv[0]);
	FILE *t = fopen(kp, "rb");
	if (t) { fclose(t); fprintf(stderr, "%s exists: not overwritten\n", kp); return 2; }
	uint8_t seed[32], sk[64], pk[32];
	if (rand_bytes(seed, 32) != 0) { fputs("no random source\n", stderr); return 2; }
	char hseed[65], hpk[65], id[9];
	to_hex(seed, 32, hseed);
	crypto_ed25519_key_pair(sk, pk, seed);	/* wipes seed */
	to_hex(pk, 32, hpk);
	key_id(pk, id);
	umask(077);
	FILE *f = fopen(kp, "wb");
	if (!f) { fprintf(stderr, "cannot write %s\n", kp); return 2; }
	fprintf(f, "%s\n", hseed);
	fclose(f);
	chmod(kp, 0600);
	f = fopen(pp, "wb");
	if (!f) { fprintf(stderr, "cannot write %s\n", pp); return 2; }
	fprintf(f, "%s tc100 update key %s\n", hpk, id);
	fclose(f);
	crypto_wipe(sk, 64);
	crypto_wipe(hseed, sizeof hseed);
	printf("%s\n", id);
	return 0;
}

static int cmd_sign(int argc, char **argv)
{
	if (argc < 2) { fputs("usage: sign KEYFILE FILE\n", stderr); return 2; }
	char *l = first_line(argv[0]);
	uint8_t seed[32], sk[64], pk[32], sig[64];
	if (!l || from_hex(l, seed, 32) != 0) { fputs("not a private key file\n", stderr); return 2; }
	crypto_wipe(l, strlen(l));
	free(l);
	size_t n;
	uint8_t *msg = slurp(argv[1], &n);
	if (!msg) { fprintf(stderr, "cannot read %s\n", argv[1]); return 2; }
	crypto_ed25519_key_pair(sk, pk, seed);
	crypto_ed25519_sign(sig, sk, msg, n);
	crypto_wipe(sk, 64);
	char id[9], hs[129];
	key_id(pk, id);
	to_hex(sig, 64, hs);
	printf("tc100-sig1 %s %s\n", id, hs);
	return 0;
}
#endif

int main(int argc, char **argv)
{
	if (argc >= 2) {
		if (strcmp(argv[1], "verify") == 0) return cmd_verify(argc - 2, argv + 2);
		if (strcmp(argv[1], "id") == 0) return cmd_id(argc - 2, argv + 2);
#ifdef SIGCHECK_HOST
		if (strcmp(argv[1], "keygen") == 0) return cmd_keygen(argc - 2, argv + 2);
		if (strcmp(argv[1], "sign") == 0) return cmd_sign(argc - 2, argv + 2);
#endif
	}
	fputs("usage: tc100-sigcheck verify FILE SIGFILE KEY... | id KEYFILE"
#ifdef SIGCHECK_HOST
	      " | keygen PREFIX | sign KEYFILE FILE"
#endif
	      "\n", stderr);
	puts("error usage");
	return 2;
}
