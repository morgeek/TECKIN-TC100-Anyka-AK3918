/* tc100-mdnsd: answers "<hostname>.local" on the local network (mDNS, RFC 6762), nothing else.
 *
 * The camera then opens as http://ipcam1.local/ (the name comes from config/hostname.conf, applied by the boot
 * script) without knowing its address. Answer only: no announcements, no services (no DNS-SD, no SSDP), no version
 * or key in any record, and only to senders on the same subnet as the camera. The packet part is mdns_pkt.h
 * (tested on the build host by tests/test_regressions.py).
 *
 * usage: tc100-mdnsd [-i IFACE]     (default wlan0)
 *
 * Freestanding like src/httpfront (raw ARM EABI system calls, no C library): a few KB. Build:
 *   arm-linux-gnueabi-gcc -Os -marm -march=armv5te -nostdlib -static -fno-builtin -fno-pic -no-pie
 *     -Wl,--build-id=none -s -o tc100-mdnsd mdnsd.c
 */
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
#define SYS_nanosleep 162
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

static void join(int s)
{
	struct ip_mreq m = { MDNS_GROUP_BE, 0 };

	sc(SYS_setsockopt, s, IPPROTO_IP, IP_ADD_MEMBERSHIP, (long)&m, sizeof m, 0);	/* EADDRINUSE: already in */
}

int run(int argc, char **argv)
{
	const char *ifn = "wlan0";
	struct sockaddr_in a = { AF_INET, MDNS_PORT_BE, 0, { 0 } }, src, dst = { AF_INET, MDNS_PORT_BE, MDNS_GROUP_BE, { 0 } };
	struct timeval tv = { 60, 0 };
	unsigned char q[1500], out[256];
	int s, on = 1, ttl = 255, loop = 0;

	for (int i = 1; i < argc; i++) {
		if (argv[i][0] == '-' && argv[i][1] == 'i' && !argv[i][2] && i + 1 < argc) ifn = argv[++i];
		else { say("usage: tc100-mdnsd [-i IFACE]\n"); return 2; }
	}
	s = (int)sc(SYS_socket, AF_INET, SOCK_DGRAM, 0, 0, 0, 0);
	if (s < 0) return 1;
	sc(SYS_setsockopt, s, SOL_SOCKET, SO_REUSEADDR, (long)&on, sizeof on, 0);
	sc(SYS_setsockopt, s, SOL_SOCKET, SO_RCVTIMEO, (long)&tv, sizeof tv, 0);
	sc(SYS_setsockopt, s, IPPROTO_IP, IP_MULTICAST_TTL, (long)&ttl, sizeof ttl, 0);
	sc(SYS_setsockopt, s, IPPROTO_IP, IP_MULTICAST_LOOP, (long)&loop, sizeof loop, 0);
	if (sc(SYS_bind, s, (long)&a, sizeof a, 0, 0, 0)) { say("tc100-mdnsd: cannot bind UDP port 5353\n"); return 1; }
	join(s);
	for (;;) {
		int sl = sizeof src, n, r;
		u32 ip, mask;
		char h[64];

		n = (int)sc(SYS_recvfrom, s, (long)q, sizeof q, 0, (long)&src, (long)&sl);
		if (n == -EAGAIN) { join(s); continue; }	/* quiet minute: join again (Wi-Fi may have come back) */
		if (n < 12) { if (n < 0 && n != -EINTR) { struct ts t = { 1, 0 }; sc(SYS_nanosleep, (long)&t, 0, 0, 0, 0, 0); } continue; }
		ip = ifaddr(s, ifn, SIOCGIFADDR); mask = ifaddr(s, ifn, SIOCGIFNETMASK);
		if (!ip || !mask || (src.addr & mask) != (ip & mask)) continue;	/* same subnet only */
		if (!hostname(h, sizeof h)) continue;
		r = mdns_answer(q, n, h, (const unsigned char *)&ip, src.port != MDNS_PORT_BE, out, sizeof out);
		if (r <= 0) continue;
		if (src.port != MDNS_PORT_BE) sc(SYS_sendto, s, (long)out, r, 0, (long)&src, sizeof src);
		else sc(SYS_sendto, s, (long)out, r, 0, (long)&dst, sizeof dst);
	}
}

__attribute__((naked, noreturn)) void _start(void)
{
	__asm__ volatile (
		"ldr r0, [sp]\n"
		"add r1, sp, #4\n"
		"bl run\n"
		"mov r7, #1\n"
		"svc 0\n");
}
