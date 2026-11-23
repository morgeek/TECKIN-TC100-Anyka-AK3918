/* ssp-freestanding.h: the stack protector of the freestanding programs (httpfront, tc100-mdnsd, isp_flip: no C
 * library, raw ARM EABI system calls), whose C library would otherwise provide it ([harden], 2026-11-23).
 *
 * With -fstack-protector-strong GCC puts a canary in every function with a local array or a local whose address is
 * taken, and checks it before the function returns. On ARM the canary is the global variable __stack_chk_guard (GCC's
 * default -mstack-protector-guard=global: ARMv5 has no thread register to hold it), and a mismatch calls
 * __stack_chk_fail. This file defines both, and tc100_ssp_init(), which _start must call before anything else: it takes
 * the canary from the 16 random bytes the kernel gives every process (auxiliary vector AT_RANDOM, after envp on the
 * initial stack). The lowest byte is zeroed as glibc does, so a string copy cannot write the canary back.
 *
 * tc100_ssp_init() has no canary itself (no_stack_protector) and must not return into a function that already loaded
 * the old value: _start calls it, then run(). Without -fstack-protector (HARDEN=0) it does nothing and nothing else is
 * defined. A smashed stack writes "stack smashing detected" to stderr and ends the process with SIGABRT (as glibc), so
 * the supervisor restarts it and the log keeps the reason. */
#ifndef TC100_SSP_FREESTANDING_H
#define TC100_SSP_FREESTANDING_H

#if defined(__SSP__) || defined(__SSP_STRONG__) || defined(__SSP_ALL__) || defined(__SSP_EXPLICIT__)
unsigned long __stack_chk_guard = 0xff0a0d00UL;	/* replaced at start; a terminator canary if AT_RANDOM is missing */

static long tc100_ssp_sc(long n, long a, long b, long c)
{
	register long r7 __asm__("r7") = n, r0 __asm__("r0") = a, r1 __asm__("r1") = b, r2 __asm__("r2") = c;

	__asm__ volatile ("svc 0" : "+r"(r0) : "r"(r7), "r"(r1), "r"(r2) : "memory");
	return r0;
}

__attribute__((noreturn, used, no_stack_protector)) void __stack_chk_fail(void)
{
	static const char m[] = "*** stack smashing detected ***: terminated\n";

	tc100_ssp_sc(4 /* write */, 2, (long)m, sizeof m - 1);
	tc100_ssp_sc(37 /* kill */, tc100_ssp_sc(20 /* getpid */, 0, 0, 0), 6 /* SIGABRT */, 0);
	for (;;) tc100_ssp_sc(248 /* exit_group */, 127, 0, 0);
}

__attribute__((used, noinline, no_stack_protector)) void tc100_ssp_init(char **argv)
{
	char **p = argv;
	unsigned long *a;

	while (*p) p++;		/* argv, NULL, */
	p++;
	while (*p) p++;		/* envp, NULL, */
	for (a = (unsigned long *)(p + 1); a[0]; a += 2)	/* then the auxiliary vector (type, value), AT_NULL = 0 */
		if (a[0] == 25 /* AT_RANDOM */ && a[1]) {
			const unsigned char *r = (const unsigned char *)a[1];

			__stack_chk_guard = (unsigned long)r[1] << 8 | (unsigned long)r[2] << 16 | (unsigned long)r[3] << 24;
			break;
		}
}
#else
__attribute__((used, noinline)) void tc100_ssp_init(char **argv) { (void)argv; }
#endif

#endif
