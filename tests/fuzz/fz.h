/* fz.h: helpers shared by the libFuzzer harnesses of tests/fuzz (host only, never built into the camera image).
 *
 * A harness includes the daemon's own C file (so the code under test is the shipped code, not a copy) after the
 * system headers, with `#define main <name>` to put the daemon's main() aside, and uses these helpers:
 *   fz_dup()       the input in a heap block of exactly its size (+ a NUL), so that AddressSanitizer sees a read past it
 *   the fake clock: every read of the clock by the code under test moves it 100 ms on, so that the
 *                  per-address rate limits and lockouts of the daemons (20 answers a second, 20 wrong logins a minute)
 *                  do not shut the parser off after the first few hundred inputs
 *                  (clock_gettime() and time() are macros here: libFuzzer's own code is another translation unit and
 *                  keeps the real clock; include this file after the system headers the daemon's file needs)
 * The harnesses never write outside /tmp and never start a program (talk.c's player is a script of our own). */
#ifndef FZ_H
#define FZ_H
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/time.h>
#include <sys/types.h>

static long long fz_clock_ms = 1000000;	/* the fake monotonic clock, in ms */

static int fz_clock_gettime(clockid_t id, struct timespec *t)
{
	(void)id;
	fz_clock_ms += 100;
	t->tv_sec = (time_t)(fz_clock_ms / 1000);
	t->tv_nsec = (long)(fz_clock_ms % 1000) * 1000000L;
	return 0;
}

static time_t fz_time(time_t *p)
{
	time_t t = (time_t)(1800000000 + fz_clock_ms / 1000 % 200);	/* after 2025-01-01 (the camera clock is "set"), inside a 200 s window: a WS-Security "Created" of the seeds stays valid */

	if (p) *p = t;
	return t;
}

/* from here on, in this translation unit only, the code under test reads the fake clock */
#define clock_gettime(id, t) fz_clock_gettime((id), (t))
#define time(p) fz_time(p)

/* the daemons log to fd 2 (LOG(), dprintf(2, ...)): silent here, a fuzzer run would be megabytes of log lines;
 * FZ_VERBOSE=1 in the environment brings them back (to see what a crash input does) */
#include <unistd.h>
#include <stdarg.h>
#include <stdio.h>
static ssize_t fz_write(int fd, const void *p, size_t n)
{
	static int verbose = -1;

	if (verbose < 0) verbose = getenv("FZ_VERBOSE") != NULL;
	return fd == 2 && !verbose ? (ssize_t)n : write(fd, p, n);
}
static int fz_dprintf(int fd, const char *fmt, ...)
{
	static int verbose = -1;
	va_list ap;
	int r;

	if (verbose < 0) verbose = getenv("FZ_VERBOSE") != NULL;
	if (fd == 2 && !verbose) return 0;
	va_start(ap, fmt);
	r = vdprintf(fd, fmt, ap);
	va_end(ap);
	return r;
}
#define write(fd, p, n) fz_write((fd), (p), (n))
#define dprintf(fd, ...) fz_dprintf((fd), __VA_ARGS__)

/* a heap copy of the input of exactly n bytes (+1 for a NUL that is not counted): a read past the end is an ASan report */
static char *fz_dup(const uint8_t *d, size_t n)
{
	char *p = malloc(n + 1);

	if (!p) abort();
	if (n) memcpy(p, d, n);
	p[n] = 0;
	return p;
}

/* the first byte of the input is a set of switches, the rest is the payload */
#define FZ_SPLIT(d, n, sw) do { if ((n) < 1) return 0; (sw) = (d)[0]; (d)++; (n)--; } while (0)
#endif
