/* httpfront: tiny front for busybox httpd on the Linux 6.6 system.
 *
 * The busybox httpd of the base image answers 404 for any directory URL, "/" included, so a browser
 * pointed at http://camera/ shows nothing. This listener accepts the connection, peeks (MSG_PEEK) at the
 * request line without consuming it, answers "GET /" with a redirect to /index.html, and hands every other
 * connection to `httpd -i` (inetd mode) as stdin/stdout.
 *
 * usage: httpfront [-p PORT] [-h HOME] [-r TARGET]    (defaults 80, /tmp/www, /index.html)
 *
 * Freestanding (no C library: raw ARM EABI system calls), a few KB instead of 630 KB for the static glibc
 * build it replaces. Build: arm-linux-gnueabi-gcc -Os -marm -march=armv5te -nostdlib -static -fno-builtin
 *   -fno-pic -no-pie -s -o httpfront httpfront.c
 */
typedef unsigned int u32;
typedef unsigned short u16;

/* ---- system calls (ARM EABI: number in r7, arguments in r0..r5, result in r0) */
static long sc(long n, long a, long b, long c, long d, long e)
{
	register long r7 __asm__("r7") = n, r0 __asm__("r0") = a, r1 __asm__("r1") = b, r2 __asm__("r2") = c,
		r3 __asm__("r3") = d, r4 __asm__("r4") = e;

	__asm__ volatile ("svc 0" : "+r"(r0) : "r"(r7), "r"(r1), "r"(r2), "r"(r3), "r"(r4) : "memory");
	return r0;
}
#define SYS_exit 1
#define SYS_fork 2
#define SYS_write 4
#define SYS_close 6
#define SYS_execve 11
#define SYS_dup2 63
#define SYS_nanosleep 162
#define SYS_rt_sigaction 174
#define SYS_socket 281
#define SYS_bind 282
#define SYS_listen 284
#define SYS_accept 285
#define SYS_recvfrom 292
#define SYS_setsockopt 294

#define EINTR 4
#define AF_INET 2
#define SOCK_STREAM 1
#define SOL_SOCKET 1
#define SO_REUSEADDR 2
#define MSG_PEEK 2
#define SIGPIPE 13
#define SIGCHLD 17

struct sockaddr_in { u16 family; u16 port; u32 addr; unsigned char zero[8]; };
struct ksigaction { long handler; unsigned long flags; long restorer; unsigned long mask[2]; };
struct ts { long sec, nsec; };

static void _exit_(int c) { for (;;) sc(SYS_exit, c, 0, 0, 0, 0); }
static void ignore(int sig) { struct ksigaction a = { 1 /* SIG_IGN */, 0, 0, { 0, 0 } }; sc(SYS_rt_sigaction, sig, (long)&a, 0, 8, 0); }
static void sleep100ms(void) { struct ts t = { 0, 100000000 }; sc(SYS_nanosleep, (long)&t, 0, 0, 0, 0); }
static int slen(const char *s) { int n = 0; while (s[n]) n++; return n; }
static int pfx(const char *s, const char *p) { while (*p) if (*s++ != *p++) return 0; return 1; }
static int num(const char *s) { int n = 0; while (*s >= '0' && *s <= '9') n = n * 10 + *s++ - '0'; return n; }
static int has_nl(const char *b, int n) { for (int i = 0; i < n; i++) if (b[i] == '\n') return 1; return 0; }
static void cat(char *d, int *l, int max, const char *s) { while (*s && *l < max) d[(*l)++] = *s++; }

static void serve(int c, const char *home, const char *target, char **envp)
{
	char b[64], r[256];
	long n;
	int tries = 0, l = 0;

	/* wait (max ~5 s) until the request line is complete */
	for (;;) {
		n = sc(SYS_recvfrom, c, (long)b, sizeof b - 1, MSG_PEEK, 0);
		if (n <= 0) _exit_(0);
		b[n] = 0;
		if (has_nl(b, (int)n) || n >= (long)sizeof b - 1 || ++tries > 50) break;
		sleep100ms();
	}
	if (pfx(b, "GET / ") || pfx(b, "GET /?") || pfx(b, "HEAD / ")) {
		cat(r, &l, sizeof r, "HTTP/1.0 302 Found\r\nLocation: ");
		cat(r, &l, sizeof r - 60, target);
		cat(r, &l, sizeof r, "\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
		sc(SYS_write, c, (long)r, l, 0, 0);
		_exit_(0);
	}
	sc(SYS_dup2, c, 0, 0, 0, 0);
	sc(SYS_dup2, c, 1, 0, 0, 0);
	if (c > 2) sc(SYS_close, c, 0, 0, 0, 0);
	{
		const char *argv[] = { "httpd", "-i", "-h", home, 0 };

		sc(SYS_execve, (long)"/usr/sbin/httpd", (long)argv, (long)envp, 0, 0);
	}
	_exit_(1);
}

int run(int argc, char **argv, char **envp)
{
	int port = 80, ls, on = 1;
	const char *home = "/tmp/www", *target = "/index.html";
	struct sockaddr_in a = { AF_INET, 0, 0, { 0 } };

	for (int i = 1; i < argc; i++) {
		const char *o = argv[i], *v = i + 1 < argc ? argv[i + 1] : 0;

		if (o[0] != '-' || !o[1] || o[2] || !v) return 2;
		if (o[1] == 'p') port = num(v);
		else if (o[1] == 'h') home = v;
		else if (o[1] == 'r') target = v;
		else return 2;
		i++;
	}
	ignore(SIGCHLD);	/* no zombies: the kernel reaps the children */
	ignore(SIGPIPE);
	ls = (int)sc(SYS_socket, AF_INET, SOCK_STREAM, 0, 0, 0);
	if (ls < 0) return 1;
	sc(SYS_setsockopt, ls, SOL_SOCKET, SO_REUSEADDR, (long)&on, sizeof on);
	a.port = (u16)((port & 0xff) << 8 | (port >> 8 & 0xff));	/* network order */
	if (sc(SYS_bind, ls, (long)&a, sizeof a, 0, 0) || sc(SYS_listen, ls, 16, 0, 0, 0)) {
		const char *m = "httpfront: cannot listen on the port\n";

		sc(SYS_write, 2, (long)m, slen(m), 0, 0);
		return 1;
	}
	for (;;) {
		long c = sc(SYS_accept, ls, 0, 0, 0, 0);

		if (c < 0) { if (c != -EINTR) sleep100ms(); continue; }
		if (sc(SYS_fork, 0, 0, 0, 0, 0) == 0) {
			sc(SYS_close, ls, 0, 0, 0, 0);
			serve((int)c, home, target, envp);
		}
		sc(SYS_close, c, 0, 0, 0, 0);
	}
}

/* entry point: argc at [sp], argv after it, then envp after argv's NULL */
__attribute__((naked, noreturn)) void _start(void)
{
	__asm__ volatile (
		"ldr r0, [sp]\n"
		"add r1, sp, #4\n"
		"add r2, r1, r0, lsl #2\n"
		"add r2, r2, #4\n"
		"bl run\n"
		"mov r7, #1\n"
		"svc 0\n");
}
