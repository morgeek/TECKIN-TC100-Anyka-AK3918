/* httpfront: tiny front for busybox httpd on the Linux 6.6 system.
 *
 * The busybox httpd of the base image answers 404 for any directory URL, "/" included, so a browser
 * pointed at http://camera/ shows nothing. This listener accepts the connection, peeks (MSG_PEEK) at the
 * request line without consuming it, answers "GET /" with a redirect to /index.html and "GET /metrics" (the usual
 * Prometheus path) with a redirect to /cgi-bin/metrics.cgi, and hands every other connection to `httpd -i` (inetd
 * mode) as stdin/stdout.
 *
 * usage: httpfront [-p PORT] [-h HOME] [-r TARGET]    (defaults 80, /tmp/www, /index.html)
 *
 * Local network only (boot.conf NET_LAN_ONLY, audit 2026-11-04 W2): TC100_NET_ALLOW="a.b.c.d/n ..." in the
 * environment (scripts/common_functions.sh netacl_allow_list) lists the networks that may connect; a connection
 * from elsewhere is closed at once. 127/8 is always allowed (web-guard checks the server from the camera). An empty
 * or missing list: no filter, as libnetacl (never a camera its owner cannot reach).
 * Bounded (audit R2): at most MAXKIDS connections at once and PERIP from one address; beyond, "503" and close. A
 * connection that does not send its request line within 2 s is closed.
 * Password guessing (item 30, audit W3; TC100_WEB_LOCKOUT=1, boot.conf WEB_LOCKOUT): a request whose Basic login does
 * not match /etc/httpd.conf (MD5 crypt, md5crypt.h, or the plain text web-auth writes when httpd cannot hash) is
 * noted by its child in FAILFILE; at each new connection the parent counts them: LOCK_FAILS failures from one address
 * within LOCK_WINDOW s close its connections for LOCK_S s (127/8 never). httpd still answers the request itself (401
 * for a wrong login): this only counts. A login checked once is remembered by the MD5 of its header (OKFILE), so the
 * 1000-round crypt runs once, not at every request.
 *
 * Native status line (item 55; TC100_NATIVE_STATUS=1, boot.conf HTTPFRONT_NATIVE=1, off by default): "GET
 * /cgi-bin/statusline.cgi" with a right Basic login is answered by httpfront itself (status.h), the same JSON as the CGI,
 * without httpd and sh; anything it cannot answer exactly goes to httpd as before.
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
#define SYS_read 3
#define SYS_write 4
#define SYS_open 5
#define SYS_close 6
#define SYS_execve 11
#define SYS_dup2 63
#define SYS_wait4 114
#define SYS_nanosleep 162
#define SYS_rt_sigaction 174
#define SYS_socket 281
#define SYS_bind 282
#define SYS_listen 284
#define SYS_accept 285
#define SYS_recvfrom 292
#define SYS_setsockopt 294
#define SYS_clock_gettime 263

#define O_WRONLY 1
#define O_CREAT 0100
#define O_TRUNC 01000
#define O_APPEND 02000

#define EINTR 4
#define ECHILD 10
#define WNOHANG 1
#define AF_INET 2
#define SOCK_STREAM 1
#define SOL_SOCKET 1
#define SO_REUSEADDR 2
#define SO_RCVTIMEO 20
#define MSG_PEEK 2
#define SIGPIPE 13
#define SIGCHLD 17

struct sockaddr_in { u16 family; u16 port; u32 addr; unsigned char zero[8]; };
struct ksigaction { long handler; unsigned long flags; long restorer; unsigned long mask[2]; };
struct ts { long sec, nsec; };

#define MAXKIDS 16	/* connections served at once (a browser opens up to 6) */
#define PERIP 8		/* from one address */
#define MAXNET 16
#define LOCK_FAILS 10	/* failed logins from one address ... */
#define LOCK_WINDOW 300	/* ... within this many seconds ... */
#define LOCK_S 300	/* ... close its connections this long */
#define NLOCK 16
#define FAILFILE "/tmp/.httpfront-fail"
#define OKFILE "/tmp/.httpfront-ok"

#include "md5crypt.h"

static void _exit_(int c) { for (;;) sc(SYS_exit, c, 0, 0, 0, 0); }
static void sigset(int sig, long h) { struct ksigaction a = { h, 0, 0, { 0, 0 } }; sc(SYS_rt_sigaction, sig, (long)&a, 0, 8, 0); }
static void ignore(int sig) { sigset(sig, 1 /* SIG_IGN */); }
static void sleep100ms(void) { struct ts t = { 0, 100000000 }; sc(SYS_nanosleep, (long)&t, 0, 0, 0, 0); }
static int slen(const char *s) { int n = 0; while (s[n]) n++; return n; }
static int pfx(const char *s, const char *p) { while (*p) if (*s++ != *p++) return 0; return 1; }
static int num(const char *s) { int n = 0; while (*s >= '0' && *s <= '9') n = n * 10 + *s++ - '0'; return n; }
static int has_nl(const char *b, int n) { for (int i = 0; i < n; i++) if (b[i] == '\n') return 1; return 0; }
static int has_end(const char *b, int n) { for (int i = 3; i < n; i++) if (b[i] == '\n' && b[i - 2] == '\n') return 1; return 0; }
static void cat(char *d, int *l, int max, const char *s) { while (*s && *l < max) d[(*l)++] = *s++; }
static int slen_eq(const char *a, const char *b) { while (*a && *a == *b) { a++; b++; } return *a != *b; }	/* 0: equal */
static int cred_cmp(const char *a, const char *b, int n) { while (n--) if (*a++ != *b++) return 1; return 0; }

/* ---- allowed networks (host order) */
static u32 net_a[MAXNET], net_m[MAXNET];
static int nnet;

static const char *getenv_(char **envp, const char *k)
{
	for (; envp && *envp; envp++) {
		const char *e = *envp, *p = k;

		while (*p && *e == *p) { e++; p++; }
		if (!*p && *e == '=') return e + 1;
	}
	return 0;
}

/* "a.b.c.d/n a.b.c.d ..." ; an unreadable entry is skipped (as libnetacl) */
static void parse_allow(const char *s)
{
	while (s && *s && nnet < MAXNET) {
		u32 a = 0;
		int ok = 1, bits = 32;

		while (*s == ' ') s++;
		if (!*s) break;
		for (int i = 0; i < 4 && ok; i++) {
			int v = 0, d = 0;

			while (*s >= '0' && *s <= '9' && d < 4) { v = v * 10 + *s++ - '0'; d++; }
			if (!d || v > 255) ok = 0;
			a = a << 8 | (u32)v;
			if (ok && i < 3) { if (*s == '.') s++; else ok = 0; }
		}
		if (ok && *s == '/') {
			int d = 0;

			s++;
			bits = 0;
			while (*s >= '0' && *s <= '9' && d < 3) { bits = bits * 10 + *s++ - '0'; d++; }
			if (!d || bits > 32) ok = 0;
		}
		if (ok && *s && *s != ' ') ok = 0;
		if (ok) {
			u32 m = bits ? 0xffffffffu << (32 - bits) : 0;

			net_a[nnet] = a & m;
			net_m[nnet] = m;
			nnet++;
		}
		while (*s && *s != ' ') s++;
	}
}

static int allowed(u32 ip)
{
	if (!nnet || (ip >> 24) == 127) return 1;
	for (int i = 0; i < nnet; i++)
		if ((ip & net_m[i]) == net_a[i]) return 1;
	return 0;
}

/* ---- children: pid and address, reaped without blocking before each new connection */
static struct { long pid; u32 ip; } kid[MAXKIDS];

static void reap(void)
{
	for (;;) {
		long p = sc(SYS_wait4, -1, 0, WNOHANG, 0, 0);

		if (p == -ECHILD) {	/* no child left: whatever the table says */
			for (int i = 0; i < MAXKIDS; i++) kid[i].pid = 0;
			return;
		}
		if (p <= 0) return;
		for (int i = 0; i < MAXKIDS; i++)
			if (kid[i].pid == p) kid[i].pid = 0;
	}
}

/* ---- password guessing (item 30) ---- */
static int lockout;	/* TC100_WEB_LOCKOUT=1 */
static const char *httpd_conf = "/etc/httpd.conf", *fail_file = FAILFILE, *ok_file = OKFILE;
static struct { u32 ip; long first, until; int n; } lk[NLOCK];

static long now_s(void)
{
	struct ts t = { 0, 0 };

	sc(SYS_clock_gettime, 1 /* CLOCK_MONOTONIC */, (long)&t, 0, 0, 0);
	return t.sec;
}

static int read_file(const char *path, char *buf, int max)
{
	long fd = sc(SYS_open, (long)path, 0, 0, 0, 0), n, t = 0;

	if (fd < 0) return -1;
	while (t < max - 1 && (n = sc(SYS_read, fd, (long)buf + t, max - 1 - t, 0, 0)) > 0) t += n;
	sc(SYS_close, fd, 0, 0, 0, 0);
	buf[t] = 0;
	return (int)t;
}

static void write_file(const char *path, const void *buf, int len, int flags)
{
	long fd = sc(SYS_open, (long)path, O_WRONLY | O_CREAT | flags, 0600, 0, 0);

	if (fd < 0) return;
	sc(SYS_write, fd, (long)buf, len, 0, 0);
	sc(SYS_close, fd, 0, 0, 0, 0);
}

static void hex16(const unsigned char d[16], char out[33])
{
	static const char H[] = "0123456789abcdef";

	for (int i = 0; i < 16; i++) { out[2 * i] = H[d[i] >> 4]; out[2 * i + 1] = H[d[i] & 15]; }
	out[32] = 0;
}

/* the Basic login of the request (headers in b): 1 matches httpd.conf, 0 does not, -1 no login or nothing to check */
static int login_ok(const char *b)
{
	const char *h = b, *v;
	char tok[300], cred[300], conf[1024], want[160], got[64], hx[33];
	unsigned char d[16];
	struct md5 m;
	int i, n;

	for (;;) {	/* "Authorization: Basic " at the start of a line, any case for the name */
		while (*h && *h != '\n') h++;
		if (!*h) return -1;
		h++;
		if ((h[0] | 32) == 'a' && pfx(h + 1, "uthorization:")) break;
	}
	v = h + 14;
	while (*v == ' ') v++;
	if (!pfx(v, "Basic ")) return -1;
	v += 6;
	for (i = 0; i < (int)sizeof tok - 1 && v[i] > ' '; i++) tok[i] = v[i];
	tok[i] = 0;
	md5_init(&m); md5_update(&m, tok, (unsigned int)i); md5_final(&m, d); hex16(d, hx);
	if (read_file(ok_file, got, sizeof got) == 32 && !slen_eq(got, hx)) return 1;	/* checked before */
	if (b64dec(tok, cred, sizeof cred) < 0) return 0;
	if ((n = read_file(httpd_conf, conf, sizeof conf)) <= 0) return -1;
	{	/* "/:user:hash" */
		const char *l = conf, *u, *p;

		while (*l && !pfx(l, "/:")) { while (*l && *l != '\n') l++; if (*l) l++; }
		if (!*l) return -1;	/* no login line: the pages are open */
		u = l + 2;
		for (p = u; *p && *p != ':' && *p != '\n'; p++) ;
		if (*p != ':') return -1;
		for (i = 0; cred[i] && cred[i] != ':'; i++) ;
		if (cred[i] != ':' || i != p - u || cred_cmp(cred, u, i)) return 0;	/* another user */
		p++;
		for (n = 0; p[n] && p[n] != '\n' && n < (int)sizeof want - 1; n++) want[n] = p[n];
		want[n] = 0;
		{
			char out[80];
			const char *pw = cred + i + 1;

			if (pfx(want, "$1$")) { if (md5crypt(pw, want, out) || slen_eq(out, want)) return 0; }
			else if (slen_eq(pw, want)) return 0;	/* plain text (httpd without MD5) */
		}
	}
	write_file(ok_file, hx, 32, O_TRUNC);
	return 1;
}

/* parent: the failures the children noted, then whether ip is locked out now */
static void lock_note(u32 ip, long t)
{
	int i, free_i = -1, old = 0;

	for (i = 0; i < NLOCK; i++) {
		if (lk[i].n && lk[i].ip == ip) break;
		if (!lk[i].n && free_i < 0) free_i = i;
		if (lk[i].first < lk[old].first) old = i;
	}
	if (i == NLOCK) { i = free_i >= 0 ? free_i : old; lk[i].ip = ip; lk[i].n = 0; lk[i].until = 0; }
	if (!lk[i].n || t - lk[i].first > LOCK_WINDOW) { lk[i].first = t; lk[i].n = 0; }
	if (++lk[i].n >= LOCK_FAILS && lk[i].until <= t) {
		char msg[80];
		int l = 0;

		lk[i].until = t + LOCK_S;
		cat(msg, &l, sizeof msg, "httpfront: login failures, an address is locked out for 5 min\n");
		write_file("/tmp/log/httpfront.log", msg, l, O_APPEND);
	}
}

static int locked(u32 ip)
{
	long t = now_s();
	u32 rec[64];
	int n, i;

	if ((n = read_file(fail_file, (char *)rec, sizeof rec)) > 0) {
		write_file(fail_file, "", 0, O_TRUNC);
		for (i = 0; i < n / 4; i++) lock_note(rec[i], t);
	}
	if ((ip >> 24) == 127) return 0;
	for (i = 0; i < NLOCK; i++)
		if (lk[i].n && lk[i].ip == ip && lk[i].until > t) return 1;
	return 0;
}

#include "status.h"

static const char *httpd_bin = "/usr/sbin/httpd";	/* TC100_HTTPD_BIN: tests */
static int native_status;	/* TC100_NATIVE_STATUS=1: GET /cgi-bin/statusline.cgi answered here (status.h) */

static void busy(int c)
{
	static const char m[] = "HTTP/1.0 503 Service Unavailable\r\nRetry-After: 2\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";

	sc(SYS_write, c, (long)m, sizeof m - 1, 0, 0);
}

static void redirect(int c, const char *to)
{
	char r[256];
	int l = 0;

	cat(r, &l, sizeof r, "HTTP/1.0 302 Found\r\nLocation: ");
	cat(r, &l, sizeof r - 60, to);
	cat(r, &l, sizeof r, "\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
	sc(SYS_write, c, (long)r, l, 0, 0);
	_exit_(0);
}

static void serve(int c, const char *home, const char *target, char **envp, u32 ip)
{
	char b[2048];
	long n;
	int tries = 0;
	struct ts rt = { 2, 0 }, none = { 0, 0 };	/* struct timeval: seconds, microseconds */

	/* wait (max ~2 s) until the request line is complete; nothing by then: close (audit R2). The peek blocks while
	 * nothing comes: a receive timeout bounds it, taken off again before httpd reads (a slow upload is not cut). */
	sc(SYS_setsockopt, c, SOL_SOCKET, SO_RCVTIMEO, (long)&rt, sizeof rt);
	for (;;) {
		n = sc(SYS_recvfrom, c, (long)b, sizeof b - 1, MSG_PEEK, 0);
		if (n <= 0) _exit_(0);
		b[n] = 0;
		if (n >= (long)sizeof b - 1) break;
		if (has_nl(b, (int)n) && (!(lockout || native_status) || has_end(b, (int)n))) break;	/* the login needs the headers */
		if (++tries > 20) { if (has_nl(b, (int)n)) break; _exit_(0); }
		sleep100ms();
	}
	if (pfx(b, "GET / ") || pfx(b, "GET /?") || pfx(b, "HEAD / ")) redirect(c, target);
	if (pfx(b, "GET /metrics ") || pfx(b, "GET /metrics?") || pfx(b, "HEAD /metrics ")) redirect(c, "/cgi-bin/metrics.cgi");
	{
		/* item 55: the status line, natively, for a complete request whose Basic login is right (no login, a wrong
		 * one, anything the native code cannot answer exactly: httpd as before, which answers 401 or the CGI) */
		int route = native_status && pfx(b, "GET /cgi-bin/statusline.cgi") && (b[27] == ' ' || b[27] == '?');
		int au = (lockout || route) ? login_ok(b) : -1, len;
		const char *resp;

		if (lockout && au == 0) write_file(fail_file, &ip, 4, O_APPEND);	/* counted by the parent */
		if (route && au == 1 && has_end(b, (int)n) && (resp = status_response(st_root, &len))) {
			sc(SYS_read, c, (long)b, n, 0, 0);	/* the request we only peeked at: no reset on close */
			sc(SYS_write, c, (long)resp, len, 0, 0);
			_exit_(0);
		}
	}
	sc(SYS_setsockopt, c, SOL_SOCKET, SO_RCVTIMEO, (long)&none, sizeof none);
	sc(SYS_dup2, c, 0, 0, 0, 0);
	sc(SYS_dup2, c, 1, 0, 0, 0);
	if (c > 2) sc(SYS_close, c, 0, 0, 0, 0);
	{
		const char *argv[] = { "httpd", "-i", "-h", home, 0 };

		sc(SYS_execve, (long)httpd_bin, (long)argv, (long)envp, 0, 0);
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
	parse_allow(getenv_(envp, "TC100_NET_ALLOW"));
	{
		const char *e = getenv_(envp, "TC100_WEB_LOCKOUT"), *f;

		lockout = e && e[0] == '1';
		native_status = (e = getenv_(envp, "TC100_NATIVE_STATUS")) && e[0] == '1';
		if ((f = getenv_(envp, "TC100_STATUS_ROOT"))) st_root = f;	/* tests */
		if ((f = getenv_(envp, "TC100_HTTPD_BIN"))) httpd_bin = f;	/* tests */
		if ((f = getenv_(envp, "TC100_HTTPD_CONF"))) httpd_conf = f;	/* tests */
		if ((f = getenv_(envp, "TC100_LOCK_DIR"))) {
			static char ff[128], of[128];
			int l = 0, m = 0;

			cat(ff, &l, sizeof ff - 1, f); cat(ff, &l, sizeof ff - 1, "/fail"); ff[l] = 0;
			cat(of, &m, sizeof of - 1, f); cat(of, &m, sizeof of - 1, "/ok"); of[m] = 0;
			fail_file = ff; ok_file = of;
		}
	}
	sigset(SIGCHLD, 0);	/* SIG_DFL, even if the parent ignored it: the children are counted and reaped (wait4) */
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
		struct sockaddr_in pa = { 0, 0, 0, { 0 } };
		int pl = sizeof pa, same = 0, slot = -1;
		long c = sc(SYS_accept, ls, (long)&pa, (long)&pl, 0, 0), p;
		u32 ip;

		if (c < 0) { if (c != -EINTR) sleep100ms(); continue; }
		ip = pa.addr >> 24 | (pa.addr >> 8 & 0xff00) | (pa.addr << 8 & 0xff0000) | pa.addr << 24;	/* host order */
		if (!allowed(ip)) { sc(SYS_close, c, 0, 0, 0, 0); continue; }
		if (lockout && locked(ip)) { sc(SYS_close, c, 0, 0, 0, 0); continue; }	/* password guessing (item 30) */
		reap();
		for (int i = 0; i < MAXKIDS; i++) {
			if (kid[i].pid) { if (kid[i].ip == ip) same++; }
			else if (slot < 0) slot = i;
		}
		if (slot < 0 || same >= PERIP) { busy((int)c); sc(SYS_close, c, 0, 0, 0, 0); continue; }
		p = sc(SYS_fork, 0, 0, 0, 0, 0);
		if (p == 0) {
			sc(SYS_close, ls, 0, 0, 0, 0);
			serve((int)c, home, target, envp, ip);
		}
		if (p > 0) { kid[slot].pid = p; kid[slot].ip = ip; }
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
