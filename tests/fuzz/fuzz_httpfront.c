/* fuzz_httpfront: the request handling of httpfront (src/httpfront/httpfront.c, built with -DTC100_FUZZ_HOST: its sc()
 * system call wrapper, ARM assembly, is replaced by the stand-in below, the only change to the file for this harness).
 * serve() is what each accepted connection runs: it peeks at up to 4095 bytes of the request, waits for the request line
 * and (with the lockout or the native routes on) the end of the headers, refuses a malformed header block (hdr_bad,
 * auth_count: 400 / 431), redirects "GET /" and "GET /metrics", answers the native routes (pl_route: the query string
 * of state.cgi / action.cgi / health.cgi) for a right Basic login (login_ok: the Authorization header, base64,
 * MD5 crypt against a /etc/httpd.conf of ours) and otherwise hands the connection to httpd (execve, stubbed).
 * What httpfront never parses (the method beyond "GET /", the body, Content-Length, cookies) goes to busybox httpd: it is
 * not reached here, see docs/linux-port/upgrade-3.2/fuzz.md.
 * Input: byte 0 = switches (bit 0 lockout, bit 1 native routes, bits 2-3 which /etc/httpd.conf), the rest = the request
 * bytes the peer sent (the whole input is what MSG_PEEK sees). */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#include "fz.h"
#define TC100_FUZZ_HOST 1
#include "../../src/httpfront/httpfront.c"

static const unsigned char *g_in;
static size_t g_inn;
static int g_conf;
static jmp_buf g_jb;
static const char *const CONFS[] = {
	"/:admin:$1$abcdefgh$Ru5SQ1c0OfiaDcrg4xgkr.\n",	/* MD5 crypt */
	"/:admin:plainpass\n",					/* plain text (httpd without MD5) */
	"",							/* no login line: the pages are open */
	"/:admin\n/:x:y",					/* broken lines */
};
static size_t g_confpos;

/* the system calls of the code under test: what it asks of the kernel is answered here, from the input and from memory */
static long sc(long n, long a, long b, long c, long d, long e)
{
	(void)e;
	switch (n) {
	case SYS_recvfrom: {	/* MSG_PEEK of the request: the bytes the peer sent, at most the size asked */
		size_t k = g_inn < (size_t)c ? g_inn : (size_t)c;

		(void)a; (void)d;
		memcpy((void *)b, g_in, k);
		return (long)k;
	}
	case SYS_open:
		if (!strcmp((const char *)a, "/etc/httpd.conf")) { g_confpos = 0; return 100; }
		return (b & O_WRONLY) ? 101 : -2;	/* a file it may write (the cache of a checked login, the failure record): a sink */
	case SYS_read:
		if (a == 100) {
			const char *cf = CONFS[g_conf];
			size_t l = strlen(cf), k = l - g_confpos < (size_t)c ? l - g_confpos : (size_t)c;

			memcpy((void *)b, cf + g_confpos, k);
			g_confpos += k;
			return (long)k;
		}
		return a == 0 ? 0 : -9;
	case SYS_write: return c;
	case SYS_clock_gettime: ((struct ts *)b)->sec = 1000 + (long)(fz_clock_ms / 1000); ((struct ts *)b)->nsec = 0; return 0;
	case SYS_exit: longjmp(g_jb, 1);
	case SYS_execve: longjmp(g_jb, 2);	/* handed to httpd: the request was let through */
	case SYS_close: case SYS_dup2: case SYS_setsockopt: case SYS_nanosleep: return 0;
	default: return -1;
	}
}

int LLVMFuzzerTestOneInput(const uint8_t *d, size_t n)
{
	int sw;
	char *envp[1] = { 0 };
	unsigned char *copy;

	FZ_SPLIT(d, n, sw);
	if (n > 8192) return 0;
	copy = malloc(n ? n : 1);	/* exact size: the code may not read past what was "received" */
	memcpy(copy, d, n);
	g_in = copy; g_inn = n;
	lockout = sw & 1;
	native_status = sw >> 1 & 1;
	g_conf = sw >> 2 & 3;
	st_root = "/nonexistent";
	if (setjmp(g_jb) == 0) serve(5, "/tmp/www", "/index.html", envp, sw & 0x10 ? 0x7f000001u : 0xc0a80105u);
	free(copy);
	return 0;
}
