/* tc100-mdnsd: answers "<hostname>.local" on the local network (mDNS, RFC 6762) and, with -s, the DNS-SD browse.
 *
 * The camera then opens as http://ipcam1.local/ (the name comes from config/hostname.conf, applied by the boot
 * script) without knowing its address. Answer only: no announcements, no SSDP, and only to senders on the same subnet
 * as the camera; never a key in any record. Item 38 of the implementer list, chosen in boot.conf (controlscripts/mdns
 * passes the options): -s (MDNS_SERVICES=1) answers the DNS-SD browse for _http._tcp (port 80) and _rtsp._tcp (port
 * 554, path=/video0_unicast), so VLC, Home Assistant or a browser list the camera; -v (MDNS_INFO=1) adds the model,
 * the firmware version, the load and the Wi-Fi level to their TXT records. config/boot.conf.dist ships both on: the
 * TXT records carry model, fw, load and rssi by default. Without the options only the A record is answered. The
 * packet part is mdns_pkt.h (tested on the build host by src/mdnsd/test_mdns.c).
 *
 * Cost (W6, audit 2026-11-24): the host name, address and netmask are kept MDNS_CACHE_S seconds (they were read with
 * three system calls and two ioctls for every query of the subnet); the TXT strings of -v are read only when a
 * DNS-SD answer is due.
 *
 * usage: tc100-mdnsd [-i IFACE] [-s] [-v] [-D UID:GID]   (default wlan0)
 *
 * Freestanding like src/httpfront (raw ARM EABI system calls, no C library): a few KB. Build:
 *   arm-linux-gnueabi-gcc -Os -marm -march=armv5te -nostdlib -static -fno-builtin -fno-pic -no-pie
 *     -Wl,--build-id=none -s -o tc100-mdnsd mdnsd.c
 */
#include "../ssp-freestanding.h"	/* the canary of -fstack-protector-strong (HARDEN=0: nothing) */
typedef unsigned int u32;
typedef unsigned short u16;

#include "mdns_pkt.h"

static long sc(long n, long a, long b, long c, long d, long e, long f)
{
	register long r7 __asm__("r7") = n, r0 __asm__("r0") = a, r1 __asm__("r1") = b, r2 __asm__("r2") = c,
		r3 __asm__("r3") = d, r4 __asm__("r4") = e, r5 __asm__("r5") = f;

	__asm__ volatile ("svc 0" : "+r"(r0) : "r"(r7), "r"(r1), "r"(r2), "r"(r3), "r"(r4), "r"(r5) : "memory");
	return r0;
}
#define SYS_exit 1
#define SYS_read 3
#define SYS_write 4
#define SYS_open 5
#define SYS_close 6
#define SYS_ioctl 54
#define SYS_getuid32 199
#define SYS_getgid32 200
#define SYS_geteuid32 201
#define SYS_getegid32 202
#define SYS_setgroups32 206
#define SYS_setuid32 213
#define SYS_setgid32 214
#define SYS_nanosleep 162
#define SYS_clock_gettime 263
#define SYS_socket 281
#define SYS_bind 282
#define SYS_sendto 290
#define SYS_recvfrom 292
#define SYS_setsockopt 294

#define AF_INET 2
#define SOCK_DGRAM 2
#define SOL_SOCKET 1
#define SO_REUSEADDR 2
#define SO_RCVTIMEO 20
#define IPPROTO_IP 0
#define IP_MULTICAST_TTL 33
#define IP_MULTICAST_LOOP 34
#define IP_ADD_MEMBERSHIP 35
#define SIOCGIFADDR 0x8915
#define SIOCGIFNETMASK 0x891b
#define EINTR 4
#define EAGAIN 11

struct sockaddr_in { u16 family; u16 port; u32 addr; unsigned char zero[8]; };
struct ifreq { char name[16]; struct sockaddr_in a; unsigned char pad[8]; };
struct ip_mreq { u32 group, iface; };
struct timeval { long sec, usec; };
struct ts { long sec, nsec; };

#define MDNS_PORT_BE 0xe914	/* 5353 in network order */
#define MDNS_GROUP_BE 0xfb0000e0u	/* 224.0.0.251 in network order (little-endian CPU) */
#define MDNS_CACHE_S 5	/* host name, address and netmask kept this long (a new name or address shows within 5 s) */

/* the compiler may call these for structure copies and clears even with -fno-builtin */
/* (volatile: GCC would otherwise turn these loops back into calls to memset / memcpy themselves) */
void *memset(void *d, int c, unsigned long n) { volatile unsigned char *p = d; while (n--) *p++ = (unsigned char)c; return d; }
void *memcpy(void *d, const void *s, unsigned long n) { volatile unsigned char *p = d; const unsigned char *q = s; while (n--) *p++ = *q++; return d; }

static int slen(const char *s) { int n = 0; while (s[n]) n++; return n; }
static void say(const char *m) { sc(SYS_write, 2, (long)m, slen(m), 0, 0, 0); }

/* the host name, as the kernel has it (autorun-linux66.sh sets it from config/hostname.conf) */
static int hostname(char *h, int max)
{
	int f = (int)sc(SYS_open, (long)"/proc/sys/kernel/hostname", 0, 0, 0, 0, 0), n, k = 0;
	char b[80];

	if (f < 0) return 0;
	n = (int)sc(SYS_read, f, (long)b, sizeof b - 1, 0, 0, 0);
	sc(SYS_close, f, 0, 0, 0, 0, 0);
	for (int i = 0; i < n && k < max - 1; i++) {
		char c = b[i];

		if (c == '\n' || c == 0) break;
		if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-')) return 0;
		h[k++] = c;
	}
	h[k] = 0;
	return k;
}

static u32 ifaddr(int s, const char *ifn, int req)
{
	struct ifreq r;
	int i;

	for (i = 0; i < (int)sizeof r; i++) ((volatile char *)&r)[i] = 0;
	for (i = 0; ifn[i] && i < 15; i++) r.name[i] = ifn[i];
	if (sc(SYS_ioctl, s, req, (long)&r, 0, 0, 0) < 0) return 0;
	return r.a.addr;
}

/* first line (or first word with word = 1) of a small file into b; returns the length */
static int first(const char *path, char *b, int max, int word)
{
	int f = (int)sc(SYS_open, (long)path, 0, 0, 0, 0, 0), n, k = 0;
	char t[96];

	b[0] = 0;
	if (f < 0) return 0;
	n = (int)sc(SYS_read, f, (long)t, sizeof t - 1, 0, 0, 0);
	sc(SYS_close, f, 0, 0, 0, 0, 0);
	for (int i = 0; i < n && k < max - 1; i++) {
		char c = t[i];

		if (c == '\n' || c == 0 || (word && c == ' ')) break;
		if (c < ' ' || c > '~') continue;
		b[k++] = c;
	}
	b[k] = 0;
	return k;
}

static void add(char *d, int *l, int max, const char *s) { while (*s && *l < max - 1) d[(*l)++] = *s++; d[*l] = 0; }

/* -v: "model=TC100\nfw=<version>\nload=<1 min>\nrssi=<dBm>" (strings of the TXT records), read for each DNS-SD
 * answer and only then (mdns_sd_answer_lazy) */
static void info_txt(char *t, int max)
{
	char b[64], w[16];
	int l = 0;

	t[0] = 0;
	add(t, &l, max, "model=TC100");
	if (first("/mnt/VERSION", b, sizeof b, 0)) { add(t, &l, max, "\nfw="); add(t, &l, max, b); }
	if (first("/proc/loadavg", b, sizeof b, 1)) { add(t, &l, max, "\nload="); add(t, &l, max, b); }
	if (first("/tmp/wifi-signal.avg", b, sizeof b, 0)) {	/* "<uptime s> <dBm>" (wifi-quality.sh) */
		int i = 0, k = 0;

		while (b[i] && b[i] != ' ') i++;
		while (b[i] == ' ') i++;
		while (b[i] && b[i] != ' ' && k < (int)sizeof w - 1) w[k++] = b[i++];
		w[k] = 0;
		if (k) { add(t, &l, max, "\nrssi="); add(t, &l, max, w); }
	}
}

/* seconds of the monotonic clock, -1 when it cannot be read (the limit is then not applied) */
static long mono(void)
{
	struct ts t;

	if (sc(SYS_clock_gettime, 1, (long)&t, 0, 0, 0, 0) < 0) return -1;
	return t.sec;
}

static void join(int s)
{
	struct ip_mreq m = { MDNS_GROUP_BE, 0 };

	sc(SYS_setsockopt, s, IPPROTO_IP, IP_ADD_MEMBERSHIP, (long)&m, sizeof m, 0);	/* EADDRINUSE: already in */
}

/* [up-privdrop] -D UID:GID (PRIVDROP=1 in boot.conf, controlscripts/mdns passes it): once the socket is bound and has joined
 * the group, give up root for good: setgroups(0), setgid, setuid, each checked, and root must not come back. A failure
 * stops the daemon. Same rules as priv_drop() of src/onvifd (tests/test_privdrop.py), with raw system calls. */
static int priv_drop(const char *spec)
{
	unsigned long v[2] = { 0, 0 };
	int k, n;

	if (!spec) return 0;
	for (k = 0; k < 2; k++) {
		for (n = 0; *spec >= '0' && *spec <= '9' && n < 6; n++) v[k] = v[k] * 10 + (unsigned long)(*spec++ - '0');
		if (!n || (k == 0 && *spec++ != ':')) return -1;
	}
	if (*spec || !v[0] || !v[1] || v[0] > 65534 || v[1] > 65534) return -1;	/* never "drop" to root */
	if (sc(SYS_setgroups32, 0, 0, 0, 0, 0, 0) || sc(SYS_setgid32, (long)v[1], 0, 0, 0, 0, 0) ||
	    sc(SYS_setuid32, (long)v[0], 0, 0, 0, 0, 0)) return -1;
	if (sc(SYS_getuid32, 0, 0, 0, 0, 0, 0) != (long)v[0] || sc(SYS_geteuid32, 0, 0, 0, 0, 0, 0) != (long)v[0] ||
	    sc(SYS_getgid32, 0, 0, 0, 0, 0, 0) != (long)v[1] || sc(SYS_getegid32, 0, 0, 0, 0, 0, 0) != (long)v[1]) return -1;
	if (sc(SYS_setuid32, 0, 0, 0, 0, 0, 0) == 0) return -1;	/* root must be gone for good */
	return 0;
}

int run(int argc, char **argv)
{
	const char *ifn = "wlan0", *drop = 0;
	struct sockaddr_in a = { AF_INET, MDNS_PORT_BE, 0, { 0 } }, src, dst = { AF_INET, MDNS_PORT_BE, MDNS_GROUP_BE, { 0 } };
	struct timeval tv = { 60, 0 };
	unsigned char q[1500], out[1500];
	int s, on = 1, ttl = 255, loop = 0, svcs = 0, info = 0;
	char txt[160], h[64];
	struct mdns_ip_rl rl;
	u32 ip = 0, mask = 0;	/* the cache of W6: h, ip and mask read at c_at (monotonic s), -1 = not read */
	long c_at = -1;

	memset(&rl, 0, sizeof rl);
	rl.global.sec = -1;

	for (int i = 1; i < argc; i++) {
		if (argv[i][0] == '-' && argv[i][1] == 'i' && !argv[i][2] && i + 1 < argc) ifn = argv[++i];
		else if (argv[i][0] == '-' && argv[i][1] == 'D' && !argv[i][2] && i + 1 < argc) drop = argv[++i];
		else if (argv[i][0] == '-' && argv[i][1] == 's' && !argv[i][2]) svcs = MDNS_SD_HTTP | MDNS_SD_RTSP;
		else if (argv[i][0] == '-' && argv[i][1] == 'v' && !argv[i][2]) info = 1;
		else { say("usage: tc100-mdnsd [-i IFACE] [-s] [-v] [-D UID:GID]\n"); return 2; }
	}
	s = (int)sc(SYS_socket, AF_INET, SOCK_DGRAM, 0, 0, 0, 0);
	if (s < 0) return 1;
	sc(SYS_setsockopt, s, SOL_SOCKET, SO_REUSEADDR, (long)&on, sizeof on, 0);
	sc(SYS_setsockopt, s, SOL_SOCKET, SO_RCVTIMEO, (long)&tv, sizeof tv, 0);
	sc(SYS_setsockopt, s, IPPROTO_IP, IP_MULTICAST_TTL, (long)&ttl, sizeof ttl, 0);
	sc(SYS_setsockopt, s, IPPROTO_IP, IP_MULTICAST_LOOP, (long)&loop, sizeof loop, 0);
	if (sc(SYS_bind, s, (long)&a, sizeof a, 0, 0, 0)) { say("tc100-mdnsd: cannot bind UDP port 5353\n"); return 1; }
	join(s);
	/* [up-privdrop] port 5353 is bound (it is not privileged, but nothing after needs root): the group is joined again
	 * every quiet minute, which any user may do */
	if (priv_drop(drop)) { say("tc100-mdnsd: cannot drop root (-D): stopping\n"); return 1; }
	for (;;) {
		int sl = sizeof src, n, r;
		long now;

		n = (int)sc(SYS_recvfrom, s, (long)q, sizeof q, 0, (long)&src, (long)&sl);
		if (n == -EAGAIN) { join(s); continue; }	/* quiet minute: join again (Wi-Fi may have come back) */
		if (n < 12) { if (n < 0 && n != -EINTR) { struct ts t = { 1, 0 }; sc(SYS_nanosleep, (long)&t, 0, 0, 0, 0, 0); } continue; }
		/* cheap checks first: other hosts' responses and odd packets cost no system call */
		if ((q[2] & 0x80) || (q[2] & 0x78) || (q[4] << 8 | q[5]) < 1 || (q[4] << 8 | q[5]) > 16) continue;
		now = mono();
		if (now >= 0 && mdns_ip_rl_full(&rl, src.addr, now)) continue;	/* flood: per-IP + total answers/sec cap */
		if (c_at < 0 || now < 0 || now - c_at >= MDNS_CACHE_S) {	/* W6: read again at most every few seconds */
			c_at = -1;
			ip = ifaddr(s, ifn, SIOCGIFADDR); mask = ifaddr(s, ifn, SIOCGIFNETMASK);
			if (!ip || !mask || !hostname(h, sizeof h)) continue;	/* a failed read is not kept: tried again next time */
			c_at = now;
		}
		if ((src.addr & mask) != (ip & mask)) continue;	/* same subnet only */
		for (int pass = 0; pass < 2; pass++) {	/* the A record, then the DNS-SD records (-s) */
			if (pass == 0) r = mdns_answer(q, n, h, (const unsigned char *)&ip, src.port != MDNS_PORT_BE, out, sizeof out);
			else {
				if (!svcs) break;
				r = mdns_sd_answer_lazy(q, n, h, (const unsigned char *)&ip, src.port != MDNS_PORT_BE, svcs,
							info ? info_txt : 0, txt, sizeof txt, out, sizeof out);
			}
			if (r <= 0) continue;
			if (now >= 0 && !mdns_ip_rl_take(&rl, src.addr, now)) break;
			if (src.port != MDNS_PORT_BE) sc(SYS_sendto, s, (long)out, r, 0, (long)&src, sizeof src);
			else sc(SYS_sendto, s, (long)out, r, 0, (long)&dst, sizeof dst);
		}
	}
}

/* entry point: argc at [sp], argv after it; the stack canary first (ssp-freestanding.h) */
__attribute__((naked, noreturn)) void _start(void)
{
	__asm__ volatile (
		"add r0, sp, #4\n"
		"bl tc100_ssp_init\n"
		"ldr r0, [sp]\n"
		"add r1, sp, #4\n"
		"bl run\n"
		"mov r7, #1\n"
		"svc 0\n");
}
