/* tc100-onvifd: free ONVIF daemon of the camera (replaces the closed binary bin/monvifd).
 *
 * One process, one select() loop, no thread, static buffers only (nothing grows while it runs):
 *   - WS-Discovery on UDP 3702 (multicast 239.255.255.250 joined on the Wi-Fi interface): Probe -> ProbeMatches,
 *     Resolve -> ResolveMatches, Hello at start, Bye on SIGTERM;
 *   - HTTP/1.1 SOAP 1.2 on ONVIF_PORT, one request per connection (Connection: close), at most 6 connections at
 *     once, 5 s to send the request, request limit 16 KB (larger: 413);
 *   - Device service (tds), Media (trt, ver10) and Media2 (tr2, ver20). Media2's profile carries the audio output and
 *     audio decoder configurations: that is the ONVIF backchannel that tc100_rtsp serves as track3 (Profile T, go2rtc,
 *     Home Assistant two-way audio);
 *   - WS-Security UsernameToken (PasswordDigest and PasswordText), same user and password as the RTSP server. The
 *     calls the ONVIF specification leaves open (GetSystemDateAndTime, GetServices, GetCapabilities,
 *     GetServiceCapabilities, GetWsdlUrl) need no credentials; the rest answers ter:NotAuthorized (HTTP 400).
 *     No password in user.pwd: no authentication, as the RTSP server.
 *   - TC100_NET_ALLOW (as src/httpfront): networks that may connect, 127/8 always, empty = no filter.
 * Events service: PullPoint subscriptions (max 4) for tns1:VideoSource/MotionAlarm and tns1:RuleEngine/CellMotionDetector/Motion, from the
 * motion file of tc100_rtsp (/tmp/rec_control, polled every 500 ms). A PullMessages with a Timeout stays pending (max 10 s) without
 * blocking the loop. Not implemented: PTZ, imaging, HTTP Digest, setters (answered with a fault).
 *
 * usage (the options of monvifd that controlscripts/onvif passes):
 *   tc100-onvifd -p PORT -w WEBPORT -wp http -r RTSPPORT -hwn NAME -vnn VENDOR -loc LOCATION -dn NAME -mod MODEL
 *                [-sp main-primary|sub-primary|main-only|sub-only]
 *                [-rp1 PATH -vw1 W -vh1 H -vc1 H264|H265 -vcb1 KBPS -fps1 N] [-en2 1 -rp2 ... -vw2 ... as 1]
 * Without -rp1 the streams come from rtspserver.conf / boot.conf (read at start and on SIGHUP).
 * Paths can be moved for tests: ONVIFD_CONF_DIR, ONVIFD_SCALE_PARAM, ONVIFD_VERSION_FILE, ONVIFD_SERIAL_FILE,
 * ONVIFD_IFACE, ONVIFD_MAC_FILE, ONVIFD_IP, ONVIFD_DISCOVERY_PORT.
 *
 * Built like src/mqttd: glibc cross compiler, linked to run under the camera's uClibc (Makefile). No sscanf, strtol,
 * atoi or libm on purpose (the uClibc of the camera lacks the glibc 2.38 C2x redirects). Host build for the tests:
 *   cc -O1 -Wall -Wextra -o tc100-onvifd-host onvifd.c
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <net/if.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#define REQ_MAX 16384		/* request (headers + body) */
#define OUT_MAX 24576		/* one answer */
#define MAXCONN 6
#define WSD_RATE 20	/* WS-Discovery answers per second (several controllers may scan at once) */
#define PERIP 4		/* connections at once from one address (an NVR may send a few requests in parallel) */
#define READ_MS 5000
#define MAXNET 16
#define SKEW_S 300
#define CLOCK_SET_MIN 1735689600L	/* 2025-01-01: before this the camera's clock is not set */
#define WSD_ADDR "239.255.255.250"

static const char *NS_S = "http://www.w3.org/2003/05/soap-envelope";

/* ---- settings ---- */

struct stream { char name[16]; char rp[16]; int w, h, codec, fps, kbps, gop; };

static struct {
	int port, web_port, rtsp_port, explicit_streams;
	char web_proto[8], policy[16];
	char hw[48], vendor[48], loc[64], dname[64], model[48];
	char tz[64], user[64], pass[128], fw[64], serial[64], mac[20], uuid[48];
	int audio, talk, sub, mw, mh;
	struct stream st[2];
	int nst;
	struct stream ex[2];	/* from the command line */
	int nex;
} G;

static const char *p_conf = "/mnt/config", *p_scale = "/sys/module/ak39_vi/parameters/main_scale",
	*p_version = "/mnt/VERSION", *p_serial = "/mnt/SerialNumber", *p_iface = "wlan0", *p_mac = NULL, *p_ip = NULL;
static int g_dport = 3702, rtsp_cli;

static volatile sig_atomic_t g_term, g_hup;
static int g_ufd = -1, g_lfd = -1;
static unsigned g_seq, g_instance;
static u_int32_t net_a[MAXNET], net_m[MAXNET];
static int nnet;

static long long now_ms(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return (long long)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

/* ---- small helpers (no scanf family) ---- */

static int num_at(const char *s, int dflt)
{
	long v = 0;
	int d = 0;

	if (!s) return dflt;
	while (*s == ' ') s++;
	while (*s >= '0' && *s <= '9' && d < 9) { v = v * 10 + *s++ - '0'; d++; }
	return d ? (int)v : dflt;
}

static void scpy(char *d, size_t n, const char *s)
{
	size_t l = strlen(s);

	if (l >= n) l = n - 1;
	memcpy(d, s, l);
	d[l] = 0;
}

static const char *env_or(const char *k, const char *d)
{
	const char *v = getenv(k);

	return v && *v ? v : d;
}

static int slurp(const char *path, char *buf, int max)
{
	int f = open(path, O_RDONLY), k = 0;
	long n;

	if (f < 0) return -1;
	while (k < max - 1 && (n = read(f, buf + k, max - 1 - k)) > 0) k += (int)n;
	close(f);
	buf[k] = 0;
	return k;
}

/* "key=value" lines of KEY=VALUE files and of the [section] files of rwconf; sect "" = before the first section.
 * The last match wins (as sed ... | tail -n 1 in the scripts); quotes around a value are dropped. */
static int ini_get(const char *b, const char *sect, const char *key, char *out, int on)
{
	size_t kl = strlen(key), sl = strlen(sect);
	int found = 0, in = sl == 0;
	const char *p = b;

	while (*p) {
		const char *e = strchr(p, '\n'), *s = p;
		size_t ll;

		if (!e) e = p + strlen(p);
		ll = (size_t)(e - p);
		p = *e ? e + 1 : e;
		while (ll && (*s == ' ' || *s == '\t')) { s++; ll--; }
		while (ll && (s[ll - 1] == '\r' || s[ll - 1] == ' ' || s[ll - 1] == '\t')) ll--;
		if (!ll || *s == '#') continue;
		if (*s == '[') {
			in = ll > 2 && s[ll - 1] == ']' && ll - 2 == sl && !memcmp(s + 1, sect, sl);
			continue;
		}
		if (in && ll > kl && !memcmp(s, key, kl) && s[kl] == '=') {
			const char *v = s + kl + 1;
			size_t vl = ll - kl - 1;

			if (vl >= 2 && (v[0] == '"' || v[0] == '\'') && v[vl - 1] == v[0]) { v++; vl -= 2; }
			if (vl >= (size_t)on) vl = on - 1;
			memcpy(out, v, vl);
			out[vl] = 0;
			found = 1;
		}
	}
	return found;
}

/* ---- SHA-1 and Base64 ---- */

static uint32_t rol(uint32_t v, int n) { return v << n | v >> (32 - n); }

static void sha1_block(uint32_t h[5], const unsigned char *p)
{
	uint32_t w[80], a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f, k, t;
	int i;

	for (i = 0; i < 16; i++) w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 | (uint32_t)p[4 * i + 2] << 8 | p[4 * i + 3];
	for (; i < 80; i++) w[i] = rol(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
	for (i = 0; i < 80; i++) {
		if (i < 20) { f = (b & c) | (~b & d); k = 0x5a827999; }
		else if (i < 40) { f = b ^ c ^ d; k = 0x6ed9eba1; }
		else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8f1bbcdc; }
		else { f = b ^ c ^ d; k = 0xca62c1d6; }
		t = rol(a, 5) + f + e + k + w[i];
		e = d; d = c; c = rol(b, 30); b = a; a = t;
	}
	h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e;
}

static void sha1(const unsigned char *d, size_t n, unsigned char out[20])
{
	uint32_t h[5] = { 0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476, 0xc3d2e1f0 };
	unsigned char tail[128];
	size_t i, full = n / 64, rem = n % 64, tl;
	uint64_t bits = (uint64_t)n * 8;

	for (i = 0; i < full; i++) sha1_block(h, d + 64 * i);
	memset(tail, 0, sizeof tail);
	memcpy(tail, d + 64 * full, rem);
	tail[rem] = 0x80;
	tl = rem < 56 ? 64 : 128;
	for (i = 0; i < 8; i++) tail[tl - 1 - i] = (unsigned char)(bits >> (8 * i));
	sha1_block(h, tail);
	if (tl == 128) sha1_block(h, tail + 64);
	for (i = 0; i < 20; i++) out[i] = (unsigned char)(h[i / 4] >> (24 - 8 * (i % 4)));
}

static const char B64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static int b64enc(const unsigned char *s, int n, char *o)
{
	int i, k = 0;

	for (i = 0; i < n; i += 3) {
		uint32_t v = (uint32_t)s[i] << 16 | (i + 1 < n ? (uint32_t)s[i + 1] << 8 : 0) | (i + 2 < n ? s[i + 2] : 0);

		o[k++] = B64[v >> 18 & 63];
		o[k++] = B64[v >> 12 & 63];
		o[k++] = i + 1 < n ? B64[v >> 6 & 63] : '=';
		o[k++] = i + 2 < n ? B64[v & 63] : '=';
	}
	o[k] = 0;
	return k;
}

/* returns the decoded length, -1 on a bad character; spaces and newlines are skipped */
static int b64dec(const char *s, int n, unsigned char *o, int max)
{
	uint32_t acc = 0;
	int bits = 0, k = 0;

	for (int i = 0; i < n; i++) {
		const char *q;

		if (s[i] == '=' || s[i] == ' ' || s[i] == '\r' || s[i] == '\n' || s[i] == '\t') continue;
		q = s[i] ? strchr(B64, s[i]) : NULL;
		if (!q) return -1;
		acc = acc << 6 | (uint32_t)(q - B64);
		bits += 6;
		if (bits >= 8) {
			bits -= 8;
			if (k >= max) return -1;
			o[k++] = (unsigned char)(acc >> bits & 255);
		}
	}
	return k;
}

static int ct_eq(const char *a, const char *b)
{
	size_t la = strlen(a), lb = strlen(b), i;
	unsigned char d = la != lb;

	for (i = 0; i < la && i < lb; i++) d |= (unsigned char)(a[i] ^ b[i]);
	return d == 0;
}

/* ---- allowed networks (as src/httpfront) ---- */

static void parse_allow(const char *s)
{
	nnet = 0;
	while (s && *s && nnet < MAXNET) {
		u_int32_t a = 0;
		int ok = 1, bits = 32;

		while (*s == ' ') s++;
		if (!*s) break;
		for (int i = 0; i < 4 && ok; i++) {
			int v = 0, d = 0;

			while (*s >= '0' && *s <= '9' && d < 4) { v = v * 10 + *s++ - '0'; d++; }
			if (!d || v > 255) ok = 0;
			a = a << 8 | (u_int32_t)v;
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
			u_int32_t m = bits ? 0xffffffffu << (32 - bits) : 0;

			net_a[nnet] = a & m;
			net_m[nnet] = m;
			nnet++;
		}
		while (*s && *s != ' ') s++;
	}
}

/* network to host order by hand: ntohl() calls __bswapsi2 of libgcc, which the uClibc of the camera does not have */
static u_int32_t n2h(u_int32_t v) { return v >> 24 | (v >> 8 & 0xff00) | (v << 8 & 0xff0000) | v << 24; }

static int allowed(u_int32_t ip)	/* host order */
{
	if (!nnet || (ip >> 24) == 127) return 1;
	for (int i = 0; i < nnet; i++)
		if ((ip & net_m[i]) == net_a[i]) return 1;
	return 0;
}

/* ---- configuration (start and SIGHUP) ---- */

static char cbuf[8192];

static void load_config(void)
{
	char path[160], v[160];
	int n, i;
	struct stream *m, *s;
	int mainres = 1080;

	/* rtspserver.conf: port, user, the two streams */
	snprintf(path, sizeof path, "%s/rtspserver.conf", p_conf);
	n = slurp(path, cbuf, sizeof cbuf);
	if (n < 0) cbuf[0] = 0;
	G.rtsp_port = ini_get(cbuf, "", "PORT", v, sizeof v) ? num_at(v, 554) : 554;
	if (G.rtsp_port < 1 || G.rtsp_port > 65535) G.rtsp_port = 554;
	if (rtsp_cli) G.rtsp_port = rtsp_cli;
	scpy(G.user, sizeof G.user, ini_get(cbuf, "", "USERNAME", v, sizeof v) && v[0] ? v : "root");

	m = &G.st[0];
	memset(G.st, 0, sizeof G.st);
	scpy(m->name, sizeof m->name, "MainStream");
	scpy(m->rp, sizeof m->rp, "video0_unicast");
	if (ini_get(cbuf, "0", "mainres", v, sizeof v)) mainres = num_at(v, 1080);
	if (mainres == 720 && access(p_scale, F_OK) == 0) { m->w = 1280; m->h = 720; } else { m->w = 1920; m->h = 1080; }
	m->codec = ini_get(cbuf, "0", "codec", v, sizeof v) && (num_at(v, 2) == 0 || num_at(v, 2) == 1) ? 0 : 2;
	m->kbps = ini_get(cbuf, "0", "bps", v, sizeof v) ? num_at(v, 1500) : 1500;
	s = &G.st[1];
	scpy(s->name, sizeof s->name, "SubStream");
	scpy(s->rp, sizeof s->rp, "video1_unicast");
	s->w = 640; s->h = 360;
	s->codec = ini_get(cbuf, "1", "codec", v, sizeof v) && num_at(v, 0) == 2 ? 2 : 0;
	s->kbps = ini_get(cbuf, "1", "bps", v, sizeof v) ? num_at(v, 400) : 400;
	for (i = 0; i < 2; i++) {	/* one rate for both streams, as rtsp-launch.sh passes it */
		const char *sec = i ? "1" : "0";
		int f = ini_get(cbuf, sec, "fps", v, sizeof v) ? num_at(v, 15) : 15, g;

		G.st[i].fps = f == 10 || f == 12 || f == 15 || f == 20 || f == 25 ? f : 15;
		g = ini_get(cbuf, sec, "goplen", v, sizeof v) ? num_at(v, 30) : 30;
		G.st[i].gop = g >= 1 && g <= 300 ? g : 30;
		if (G.st[i].kbps < 32 || G.st[i].kbps > 20000) G.st[i].kbps = i ? 400 : 1500;
	}

	/* boot.conf: sub-stream, audio, backchannel */
	snprintf(path, sizeof path, "%s/boot.conf", p_conf);
	n = slurp(path, cbuf, sizeof cbuf);
	if (n < 0) cbuf[0] = 0;
	G.sub = 1;
	if (ini_get(cbuf, "", "RTSP_SUBSTREAM", v, sizeof v) && (!strcmp(v, "0") || !strcmp(v, "no") || !strcmp(v, "off") || !strcmp(v, "false"))) G.sub = 0;
	G.audio = 1;
	if (ini_get(cbuf, "", "RTSP_AUDIO", v, sizeof v) && (!strcmp(v, "0") || !strcmp(v, "no") || !strcmp(v, "off") || !strcmp(v, "false"))) G.audio = 0;
	G.talk = 1;
	if (ini_get(cbuf, "", "RTSP_LITE_TALK", v, sizeof v) && (!strcmp(v, "0") || !strcmp(v, "no") || !strcmp(v, "off") || !strcmp(v, "false"))) G.talk = 0;

	/* the RTSP user can be set in rtsp.env (RTSP_USER, what rtsp-launch.sh passes as -u) */
	snprintf(path, sizeof path, "%s/rtsp.env", p_conf);
	n = slurp(path, cbuf, sizeof cbuf);
	if (n >= 0 && ini_get(cbuf, "", "RTSP_USER", v, sizeof v) && v[0]) scpy(G.user, sizeof G.user, v);

	/* the password: first line of user.pwd, empty or missing = no authentication */
	G.pass[0] = 0;
	snprintf(path, sizeof path, "%s/user.pwd", p_conf);
	n = slurp(path, cbuf, 256);
	if (n > 0) {
		cbuf[strcspn(cbuf, "\r\n")] = 0;
		scpy(G.pass, sizeof G.pass, cbuf);
	}

	/* time zone (first line that is not a comment) */
	snprintf(path, sizeof path, "%s/timezone.conf", p_conf);
	G.tz[0] = 0;
	n = slurp(path, cbuf, 512);
	if (n > 0) {
		char *p = cbuf;

		while (*p) {
			char *e = p + strcspn(p, "\r\n");

			if (*p != '#' && e > p) { *e = 0; scpy(G.tz, sizeof G.tz, p); break; }
			p = *e ? e + 1 : e;
			while (*p == '\r' || *p == '\n') p++;
		}
	}
	if (!G.tz[0]) scpy(G.tz, sizeof G.tz, "UTC0");
	setenv("TZ", G.tz, 1);
	tzset();

	n = slurp(p_version, cbuf, 128);
	scpy(G.fw, sizeof G.fw, n > 0 ? (cbuf[strcspn(cbuf, "\r\n")] = 0, cbuf) : "unknown");
	n = slurp(p_serial, cbuf, 128);
	if (n > 0) { cbuf[strcspn(cbuf, "\r\n")] = 0; scpy(G.serial, sizeof G.serial, cbuf); }
	else G.serial[0] = 0;
	if (!G.serial[0]) {	/* the MAC address without colons */
		int k = 0;

		for (i = 0; G.mac[i] && k < 14; i++) if (G.mac[i] != ':') G.serial[k++] = G.mac[i];
		G.serial[k] = 0;
	}

	/* the streams: command line, else the two above in the order of the policy */
	if (G.explicit_streams) {
		G.nst = G.nex;
		memcpy(G.st, G.ex, sizeof G.st);
	} else {
		struct stream a = G.st[0], b = G.st[1];

		if (!G.sub || !strcmp(G.policy, "main-only")) { G.st[0] = a; G.nst = 1; }
		else if (!strcmp(G.policy, "sub-only")) { G.st[0] = b; G.nst = 1; }
		else if (!strcmp(G.policy, "sub-primary")) { G.st[0] = b; G.st[1] = a; G.nst = 2; }
		else { G.nst = 2; }
	}
	G.mw = G.st[0].w; G.mh = G.st[0].h;	/* the sensor picture: the biggest stream */
	for (i = 1; i < G.nst; i++) if (G.st[i].w > G.mw) { G.mw = G.st[i].w; G.mh = G.st[i].h; }
}

/* ---- network helpers ---- */

static int iface_ioctl(int req, struct sockaddr_in *out)
{
	struct ifreq r;
	int s = socket(AF_INET, SOCK_DGRAM, 0), ok;

	if (s < 0) return -1;
	memset(&r, 0, sizeof r);
	scpy(r.ifr_name, sizeof r.ifr_name, p_iface);
	ok = ioctl(s, req, &r);
	close(s);
	if (ok) return -1;
	memcpy(out, &r.ifr_addr, sizeof *out);
	return 0;
}

/* address of the interface, text; 0 on failure */
static int iface_ip(char *out, size_t n)
{
	struct sockaddr_in a;

	if (p_ip) { scpy(out, n, p_ip); return 1; }
	if (iface_ioctl(SIOCGIFADDR, &a) || !a.sin_addr.s_addr) return 0;
	scpy(out, n, inet_ntoa(a.sin_addr));
	return 1;
}

static int iface_prefix(void)
{
	struct sockaddr_in a;
	u_int32_t m;
	int n = 0;

	if (iface_ioctl(SIOCGIFNETMASK, &a)) return 24;
	m = n2h(a.sin_addr.s_addr);
	while (m & 0x80000000u) { n++; m <<= 1; }
	return n;
}

static void uuid_make(char *o, size_t n, uint32_t a, uint32_t b)
{
	snprintf(o, n, "%08x-%04x-4%03x-8%03x-%08x%04x", (unsigned)a, (unsigned)(b >> 16 & 0xffff), (unsigned)(b & 0xfff),
		(unsigned)(a >> 20 & 0xfff), (unsigned)(a ^ b * 2654435761u), (unsigned)(b ^ a >> 7) & 0xffff);
}

static void device_uuid(void)	/* stable: from the MAC address */
{
	char h[16] = "";
	int k = 0;

	for (int i = 0; G.mac[i] && k < 12; i++) if (G.mac[i] != ':') h[k++] = G.mac[i];
	h[k] = 0;
	snprintf(G.uuid, sizeof G.uuid, "urn:uuid:7e57c100-0000-4000-8000-%.12s", h);
}

/* ---- output buffer ---- */

static char ob[OUT_MAX];
static int ol, oerr;

static void PS(const char *s)
{
	size_t l = strlen(s);

	if (oerr || ol + (int)l >= OUT_MAX) { oerr = 1; return; }
	memcpy(ob + ol, s, l);
	ol += (int)l;
}

static void P(const char *fmt, ...)
{
	va_list ap;
	int n;

	if (oerr) return;
	va_start(ap, fmt);
	n = vsnprintf(ob + ol, OUT_MAX - ol, fmt, ap);
	va_end(ap);
	if (n < 0 || n >= OUT_MAX - ol) { oerr = 1; return; }
	ol += n;
}

static void PX(const char *s)	/* escaped text */
{
	for (; *s; s++) {
		switch (*s) {
		case '&': PS("&amp;"); break;
		case '<': PS("&lt;"); break;
		case '>': PS("&gt;"); break;
		case '"': PS("&quot;"); break;
		case '\'': PS("&apos;"); break;
		default:
			if ((unsigned char)*s >= 32 && ol + 1 < OUT_MAX) ob[ol++] = *s;
		}
	}
}

static void PXe(const char *tag, const char *s)	/* <tag>escaped s</tag> */
{
	P("<%s>", tag);
	PX(s);
	P("</%s>", tag);
}

/* onvif:// scope items, text percent-encoded */
static void scope_enc(const char *s)
{
	for (; *s; s++) {
		if ((*s >= 'a' && *s <= 'z') || (*s >= 'A' && *s <= 'Z') || (*s >= '0' && *s <= '9') || *s == '.' || *s == '-' || *s == '_')
			P("%c", *s);
		else
			P("%%%02X", (unsigned char)*s);
	}
}

#define NSALL "xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:tt=\"http://www.onvif.org/ver10/schema\" " \
	"xmlns:tds=\"http://www.onvif.org/ver10/device/wsdl\" xmlns:trt=\"http://www.onvif.org/ver10/media/wsdl\" " \
	"xmlns:tr2=\"http://www.onvif.org/ver20/media/wsdl\" xmlns:ter=\"http://www.onvif.org/ver10/error\" " \
	"xmlns:tev=\"http://www.onvif.org/ver10/events/wsdl\" xmlns:wsnt=\"http://docs.oasis-open.org/wsn/b-2\" xmlns:wstop=\"http://docs.oasis-open.org/wsn/t-1\" " \
	"xmlns:tns1=\"http://www.onvif.org/ver10/topics\" xmlns:wsa=\"http://www.w3.org/2005/08/addressing\" xmlns:xs=\"http://www.w3.org/2001/XMLSchema\""

static void env_begin(void)
{
	ol = 0;
	oerr = 0;
	PS("<?xml version=\"1.0\" encoding=\"UTF-8\"?><s:Envelope " NSALL "><s:Body>");
}

static void env_end(void) { PS("</s:Body></s:Envelope>"); }

/* a fault replaces whatever was written. sub2 may be NULL. */
static int fault(int sender, const char *sub1, const char *sub2, const char *reason)
{
	env_begin();
	P("<s:Fault><s:Code><s:Value>s:%s</s:Value><s:Subcode><s:Value>%s</s:Value>", sender ? "Sender" : "Receiver", sub1);
	if (sub2) P("<s:Subcode><s:Value>%s</s:Value></s:Subcode>", sub2);
	P("</s:Subcode></s:Code><s:Reason><s:Text xml:lang=\"en\">");
	PX(reason);
	PS("</s:Text></s:Reason></s:Fault>");
	env_end();
	return sender ? 400 : 500;
}

/* ---- XML reading: bounded, text content only ---- */

/* first element with local name `name` (prefix ignored) in [b, end): returns its text start, sets the length of the
 * text (up to the next '<') and the attribute text */
static const char *find_elem(const char *b, const char *end, const char *name, const char **attrs, int *alen, int *clen)
{
	size_t nl = strlen(name);

	for (const char *p = b; p < end; p++) {
		const char *q, *s, *a, *c;

		if (*p != '<') continue;
		q = p + 1;
		if (q >= end || *q == '/' || *q == '!' || *q == '?') continue;
		s = q;
		while (q < end && *q != ' ' && *q != '>' && *q != '/' && *q != '\t' && *q != '\r' && *q != '\n') {
			if (*q == ':') s = q + 1;
			q++;
		}
		if ((size_t)(q - s) != nl || memcmp(s, name, nl)) continue;
		a = q;
		while (a < end && *a != '>') a++;
		if (a >= end) return NULL;
		if (attrs) { *attrs = q; *alen = (int)(a - q); }
		if (a > q && a[-1] == '/') { *clen = 0; return a + 1; }
		a++;
		c = a;
		while (c < end && *c != '<') c++;
		*clen = (int)(c - a);
		return a;
	}
	return NULL;
}

/* the text of an element, trimmed, into out (empty when absent); returns 1 when the element exists */
static int get_text(const char *b, const char *end, const char *name, char *out, int on)
{
	int cl;
	const char *t = find_elem(b, end, name, NULL, NULL, &cl);

	out[0] = 0;
	if (!t) return 0;
	while (cl && (*t == ' ' || *t == '\r' || *t == '\n' || *t == '\t')) { t++; cl--; }
	while (cl && (t[cl - 1] == ' ' || t[cl - 1] == '\r' || t[cl - 1] == '\n' || t[cl - 1] == '\t')) cl--;
	if (cl >= on) cl = on - 1;
	memcpy(out, t, cl);
	out[cl] = 0;
	return 1;
}

/* local name of the first element inside <Body>; *rest = just after its tag name */
static int body_action(const char *b, int n, char *act, int an, const char **rest)
{
	const char *end = b + n, *p = b;

	for (;;) {
		const char *q, *s;

		while (p < end && *p != '<') p++;
		if (p >= end) return 0;
		q = p + 1;
		if (q < end && (*q == '/' || *q == '!' || *q == '?')) { p++; continue; }
		s = q;
		while (q < end && *q != ' ' && *q != '>' && *q != '/' && *q != '\t' && *q != '\r' && *q != '\n') {
			if (*q == ':') s = q + 1;
			q++;
		}
		if (q - s == 4 && !memcmp(s, "Body", 4)) { p = q; break; }
		p = q;
	}
	while (p < end && *p != '>') p++;
	if (p >= end || p[-1] == '/') return 0;
	for (;;) {
		const char *q, *s;

		while (p < end && *p != '<') p++;
		if (p >= end) return 0;
		q = p + 1;
		if (q < end && (*q == '/' || *q == '!' || *q == '?')) { if (*q == '/') return 0; p++; continue; }
		s = q;
		while (q < end && *q != ' ' && *q != '>' && *q != '/' && *q != '\t' && *q != '\r' && *q != '\n') {
			if (*q == ':') s = q + 1;
			q++;
		}
		if (q - s <= 0 || q - s >= an) return 0;
		memcpy(act, s, q - s);
		act[q - s] = 0;
		*rest = q;
		return 1;
	}
}

/* ---- authentication ---- */

static long days_from_civil(long y, unsigned m, unsigned d)
{
	long era;
	unsigned yoe, doy, doe;

	y -= m <= 2;
	era = (y >= 0 ? y : y - 399) / 400;
	yoe = (unsigned)(y - era * 400);
	doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
	doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
	return era * 146097 + (long)doe - 719468;
}

static int dig(const char *s, int n, int *v)
{
	*v = 0;
	for (int i = 0; i < n; i++) {
		if (s[i] < '0' || s[i] > '9') return 0;
		*v = *v * 10 + s[i] - '0';
	}
	return 1;
}

/* "2024-05-01T12:00:00(.fff)Z" -> epoch seconds, 0 when it does not parse */
static long parse_iso(const char *s)
{
	int y, mo, d, h, mi, se;

	if (strlen(s) < 19 || s[4] != '-' || s[7] != '-' || (s[10] != 'T' && s[10] != ' ') || s[13] != ':' || s[16] != ':') return 0;
	if (!dig(s, 4, &y) || !dig(s + 5, 2, &mo) || !dig(s + 8, 2, &d) || !dig(s + 11, 2, &h) || !dig(s + 14, 2, &mi) || !dig(s + 17, 2, &se)) return 0;
	if (mo < 1 || mo > 12 || d < 1 || d > 31 || h > 23 || mi > 59 || se > 60) return 0;
	return days_from_civil(y, (unsigned)mo, (unsigned)d) * 86400L + h * 3600L + mi * 60L + se;
}

/* wrong logins counted per address (review 2026-11-12: one global counter let any LAN host lock the NVR out by sending
 * 20 bad tokens a minute): FAIL_MAX failures within a minute refuse that address only; 127/8 is never counted */
#define FAIL_MAX 20
#define FAIL_SLOTS 32
static struct { u_int32_t ip; int n; long long t0; } g_fail[FAIL_SLOTS];
static u_int32_t g_peer;	/* host order, set by process() for the request being answered */

static int fail_find(u_int32_t ip, long long t)
{
	for (int i = 0; i < FAIL_SLOTS; i++)
		if (g_fail[i].n && g_fail[i].ip == ip) {
			if (t - g_fail[i].t0 > 60000) { g_fail[i].n = 0; return -1; }
			return i;
		}
	return -1;
}

static int fail_locked(u_int32_t ip, long long t)
{
	int i = fail_find(ip, t);

	return (ip >> 24) != 127 && i >= 0 && g_fail[i].n >= FAIL_MAX;
}

static void fail_note(u_int32_t ip, long long t)
{
	int i = fail_find(ip, t), o = 0;

	if ((ip >> 24) == 127) return;
	if (i < 0) {	/* a free or expired slot, else the oldest one that is not locked (a locked address is never
			 * evicted: cycling through more addresses than slots must not unlock one) */
		o = -1;
		for (i = 0; i < FAIL_SLOTS && g_fail[i].n && t - g_fail[i].t0 <= 60000; i++)
			if (g_fail[i].n < FAIL_MAX && (o < 0 || g_fail[i].t0 < g_fail[o].t0)) o = i;
		if (i == FAIL_SLOTS) {
			if (o < 0) return;	/* every slot holds a locked address: more than FAIL_SLOTS guessers */
			i = o;
		}
		g_fail[i].ip = ip; g_fail[i].n = 0; g_fail[i].t0 = t;
	}
	g_fail[i].n++;
}

/* the five predefined XML entities and ASCII character references, in place (credentials only: a decoded '<' must never be echoed in an answer) */
static void xml_unescape(char *s)
{
	static const struct { const char *e; char c; } E[] = { { "&amp;", '&' }, { "&lt;", '<' }, { "&gt;", '>' },
							       { "&quot;", '"' }, { "&apos;", '\'' } };
	char *d = s;

	while (*s) {
		int k, done = 0;

		if (*s == '&' && s[1] == '#') {	/* &#39; &#x27; ... (Go's encoding/xml escapes ' and " that way): ASCII only */
			const char *q = s + 2;
			int v = 0, hex = (*q == 'x' || *q == 'X'), nd = 0;

			if (hex) q++;
			for (; nd < 6; q++, nd++) {
				int c = *q, dv = c >= '0' && c <= '9' ? c - '0' : hex && c >= 'a' && c <= 'f' ? c - 'a' + 10 :
					 hex && c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;

				if (dv < 0) break;
				v = v * (hex ? 16 : 10) + dv;
			}
			if (nd && *q == ';' && v > 0 && v < 128) { *d++ = (char)v; s = q + 1; done = 1; }
		}
		if (*s == '&' && !done)
			for (k = 0; k < 5 && !done; k++)
				if (!strncmp(s, E[k].e, strlen(E[k].e))) { *d++ = E[k].c; s += strlen(E[k].e); done = 1; }
		if (!done) *d++ = *s++;
	}
	*d = 0;
}

static int has_sub(const char *h, int n, const char *needle)
{
	int l = (int)strlen(needle);

	for (int i = 0; h && i + l <= n; i++) if (!memcmp(h + i, needle, l)) return 1;
	return 0;
}

/* 1: credentials accepted (or none needed) */
static int check_auth(const char *b, int n)
{
	char user[96], pw[160], nonce[96], created[48];
	const char *end = b + n, *attrs = NULL;
	int al = 0, cl = 0;
	long long t = now_ms();

	if (!G.pass[0]) return 1;
	if (fail_locked(g_peer, t)) return 0;	/* guessing from this address: refused for the rest of its minute */
	if (!find_elem(b, end, "UsernameToken", NULL, NULL, &cl)) return 0;
	get_text(b, end, "Username", user, sizeof user);
	if (!find_elem(b, end, "Password", &attrs, &al, &cl)) return 0;
	get_text(b, end, "Password", pw, sizeof pw);
	xml_unescape(user); xml_unescape(pw);	/* a password with & < > " ' arrives escaped */
	if (!ct_eq(user, G.user)) goto bad;
	if (has_sub(attrs, al, "PasswordDigest")) {
		unsigned char raw[64], dg[20], buf[256];
		char enc[40];
		int nl, kl, cn;

		get_text(b, end, "Nonce", nonce, sizeof nonce);
		get_text(b, end, "Created", created, sizeof created);
		nl = b64dec(nonce, (int)strlen(nonce), raw, sizeof raw);
		kl = (int)strlen(created);
		if (nl <= 0 || !kl) goto bad;
		if (time(NULL) > CLOCK_SET_MIN) {	/* clock set: the token must be recent */
			long c = parse_iso(created), d;

			if (!c) goto bad;
			d = (long)time(NULL) - c;
			if (d > SKEW_S || d < -SKEW_S) goto bad;
		}
		cn = nl + kl + (int)strlen(G.pass);
		if (cn > (int)sizeof buf) goto bad;
		memcpy(buf, raw, nl);
		memcpy(buf + nl, created, kl);
		memcpy(buf + nl + kl, G.pass, strlen(G.pass));
		sha1(buf, cn, dg);
		b64enc(dg, 20, enc);
		if (!ct_eq(enc, pw)) goto bad;
		return 1;
	}
	if (!ct_eq(pw, G.pass)) goto bad;
	return 1;
bad:
	fail_note(g_peer, t);
	return 0;
}

/* ---- the parts of the answers ---- */

static char g_ip[48];		/* address the request came to */
static int g_ver2;		/* the Media2 service is being answered */

static void url_web(const char *path)
{
	P("%s://%s", G.web_proto, g_ip);
	if (G.web_port != 80) P(":%d", G.web_port);
	P("%s", path);
}

static void x_mc(void)
{
	PS("<tt:Multicast><tt:Address><tt:Type>IPv4</tt:Type><tt:IPv4Address>0.0.0.0</tt:IPv4Address></tt:Address><tt:Port>0</tt:Port><tt:TTL>0</tt:TTL><tt:AutoStart>false</tt:AutoStart></tt:Multicast>");
}

enum { K_VSC, K_VEC, K_ASC, K_AEC, K_AOC, K_ADC };
static const char *const kname[] = { "VideoSource", "VideoEncoder", "AudioSource", "AudioEncoder", "AudioOutput", "AudioDecoder" };

static int kcount(int k)
{
	switch (k) {
	case K_VSC: return 1;
	case K_VEC: return G.nst;
	case K_ASC: case K_AEC: return G.audio ? 1 : 0;
	default: return G.audio && G.talk ? 1 : 0;
	}
}

static void ktok(int k, int i, char *o, size_t n)
{
	if (k == K_VEC) snprintf(o, n, "VideoEncoderConfig_%d", i + 1);
	else snprintf(o, n, "%sConfig_1", kname[k]);
}

static const char *codec_name(int c) { return c == 2 ? "H265" : "H264"; }

/* inside of a configuration element */
static void kbody(int k, int i, int v2)
{
	char t[40];
	int uses = k == K_VEC ? 1 : G.nst;

	ktok(k, i, t, sizeof t);
	P("<tt:Name>%s</tt:Name><tt:UseCount>%d</tt:UseCount>", t, uses);
	switch (k) {
	case K_VSC:
		P("<tt:SourceToken>VideoSource_1</tt:SourceToken><tt:Bounds x=\"0\" y=\"0\" width=\"%d\" height=\"%d\"/>", G.mw, G.mh);
		break;
	case K_VEC: {
		const struct stream *s = &G.st[i];

		P("<tt:Encoding>%s</tt:Encoding><tt:Resolution><tt:Width>%d</tt:Width><tt:Height>%d</tt:Height></tt:Resolution>", codec_name(s->codec), s->w, s->h);
		if (v2) {
			P("<tt:RateControl ConstantBitRate=\"false\"><tt:FrameRateLimit>%d</tt:FrameRateLimit><tt:BitrateLimit>%d</tt:BitrateLimit></tt:RateControl>", s->fps, s->kbps);
			x_mc();
			PS("<tt:Quality>5</tt:Quality>");
		} else {
			P("<tt:Quality>5</tt:Quality><tt:RateControl><tt:FrameRateLimit>%d</tt:FrameRateLimit><tt:EncodingInterval>1</tt:EncodingInterval><tt:BitrateLimit>%d</tt:BitrateLimit></tt:RateControl>", s->fps, s->kbps);
			if (s->codec != 2) P("<tt:H264><tt:GovLength>%d</tt:GovLength><tt:H264Profile>Main</tt:H264Profile></tt:H264>", s->gop);
			x_mc();
			PS("<tt:SessionTimeout>PT60S</tt:SessionTimeout>");
		}
		break;
	}
	case K_ASC:
		PS("<tt:SourceToken>AudioSource_1</tt:SourceToken>");
		break;
	case K_AEC:
		if (v2) { PS("<tt:Encoding>PCMA</tt:Encoding>"); x_mc(); PS("<tt:Bitrate>64</tt:Bitrate><tt:SampleRate>8</tt:SampleRate>"); }
		else { PS("<tt:Encoding>G711</tt:Encoding><tt:Bitrate>64</tt:Bitrate><tt:SampleRate>8</tt:SampleRate>"); x_mc(); PS("<tt:SessionTimeout>PT60S</tt:SessionTimeout>"); }
		break;
	case K_AOC:
		PS("<tt:OutputToken>AudioOutput_1</tt:OutputToken><tt:SendPrimacy>www.onvif.org/ver20/HalfDuplex/Auto</tt:SendPrimacy><tt:OutputLevel>100</tt:OutputLevel>");
		break;
	default:
		break;
	}
}

/* <tag token=...[ media2 attributes]> */
static void kopen(const char *tag, int k, int i, int v2)
{
	char t[40];

	ktok(k, i, t, sizeof t);
	P("<%s token=\"%s\"", tag, t);
	if (v2 && k == K_VEC) P(" GovLength=\"%d\" Profile=\"Main\"", G.st[i].gop);
	PS(">");
}

static void kemit(const char *tag, int k, int i, int v2)
{
	kopen(tag, k, i, v2);
	kbody(k, i, v2);
	P("</%s>", tag);
}

static void profile_name(int i, char *o, size_t n) { snprintf(o, n, "profile_%d", i + 1); }

static void profile1(const char *tag, int i)
{
	char t[24];

	profile_name(i, t, sizeof t);
	P("<%s token=\"%s\" fixed=\"true\"><tt:Name>%s</tt:Name>", tag, t, G.st[i].name);
	kemit("tt:VideoSourceConfiguration", K_VSC, 0, 0);
	if (kcount(K_ASC)) kemit("tt:AudioSourceConfiguration", K_ASC, 0, 0);
	kemit("tt:VideoEncoderConfiguration", K_VEC, i, 0);
	if (kcount(K_AEC)) kemit("tt:AudioEncoderConfiguration", K_AEC, 0, 0);
	if (kcount(K_AOC)) {
		PS("<tt:Extension>");
		kemit("tt:AudioOutputConfiguration", K_AOC, 0, 0);
		kemit("tt:AudioDecoderConfiguration", K_ADC, 0, 0);
		PS("</tt:Extension>");
	}
	P("</%s>", tag);
}

static void profile2(const char *tag, int i)
{
	char t[24];

	profile_name(i, t, sizeof t);
	P("<%s token=\"%s\" fixed=\"true\"><tr2:Name>%s</tr2:Name><tr2:Configurations>", tag, t, G.st[i].name);
	kemit("tr2:VideoSource", K_VSC, 0, 1);
	if (kcount(K_ASC)) kemit("tr2:AudioSource", K_ASC, 0, 1);
	kemit("tr2:VideoEncoder", K_VEC, i, 1);
	if (kcount(K_AEC)) kemit("tr2:AudioEncoder", K_AEC, 0, 1);
	if (kcount(K_AOC)) {
		kemit("tr2:AudioOutput", K_AOC, 0, 1);
		kemit("tr2:AudioDecoder", K_ADC, 0, 1);
	}
	P("</tr2:Configurations></%s>", tag);
}

static void scopes_text(char sep_is_space)
{
	const char *base = "onvif://www.onvif.org/";
	static const char *const fixed[] = { "Profile/Streaming", "Profile/T", "type/video_encoder", "type/audio_encoder", "type/NetworkVideoTransmitter" };
	int first = 1;

	for (int i = 0; i < 5; i++) {
		if (!first) PS(sep_is_space ? " " : "|");
		first = 0;
		P("%s%s", base, fixed[i]);
	}
	P(" %shardware/", base); scope_enc(G.hw);
	P(" %sname/", base); scope_enc(G.dname);
	P(" %slocation/", base); scope_enc(G.loc);
}

static void x_scopes_soap(void)
{
	static const char *const fixed[] = { "Profile/Streaming", "Profile/T", "type/video_encoder", "type/audio_encoder", "type/NetworkVideoTransmitter" };

	for (int i = 0; i < 5; i++)
		P("<tds:Scopes><tt:ScopeDef>Fixed</tt:ScopeDef><tt:ScopeItem>onvif://www.onvif.org/%s</tt:ScopeItem></tds:Scopes>", fixed[i]);
	PS("<tds:Scopes><tt:ScopeDef>Configurable</tt:ScopeDef><tt:ScopeItem>onvif://www.onvif.org/hardware/"); scope_enc(G.hw); PS("</tt:ScopeItem></tds:Scopes>");
	PS("<tds:Scopes><tt:ScopeDef>Configurable</tt:ScopeDef><tt:ScopeItem>onvif://www.onvif.org/name/"); scope_enc(G.dname); PS("</tt:ScopeItem></tds:Scopes>");
	PS("<tds:Scopes><tt:ScopeDef>Configurable</tt:ScopeDef><tt:ScopeItem>onvif://www.onvif.org/location/"); scope_enc(G.loc); PS("</tt:ScopeItem></tds:Scopes>");
}

static void xaddr(const char *svc) { P("http://%s:%d/onvif/%s", g_ip, G.port, svc); }

/* capability roots of the three services */
static void cap_device(void)
{
	PS("<tds:Capabilities><tds:Network IPFilter=\"false\" ZeroConfiguration=\"false\" IPVersion6=\"false\" DynDNS=\"false\" Dot11Configuration=\"false\" HostnameFromDHCP=\"false\" NTP=\"0\"/>"
	   "<tds:Security UsernameToken=\"true\" HttpDigest=\"false\" RELToken=\"false\"/>"
	   "<tds:System DiscoveryResolve=\"true\" DiscoveryBye=\"true\" RemoteDiscovery=\"false\" SystemBackup=\"false\" SystemLogging=\"false\" FirmwareUpgrade=\"false\"/></tds:Capabilities>");
}

static void cap_media(void)
{
	P("<trt:Capabilities SnapshotUri=\"true\" Rotation=\"false\" VideoSourceMode=\"false\" OSD=\"false\"><trt:ProfileCapabilities MaximumNumberOfProfiles=\"%d\"/>"
	  "<trt:StreamingCapabilities RTPMulticast=\"false\" RTP_TCP=\"true\" RTP_RTSP_TCP=\"true\"/></trt:Capabilities>", G.nst);
}

static void cap_media2(void)
{
	P("<tr2:Capabilities SnapshotUri=\"true\" Rotation=\"false\" VideoSourceMode=\"false\" OSD=\"false\" TemporaryOSDText=\"false\" Mask=\"false\">"
	  "<tr2:ProfileCapabilities MaximumNumberOfProfiles=\"%d\" ConfigurationsSupported=\"VideoSource VideoEncoder%s\"/>"
	  "<tr2:StreamingCapabilities RTSPStreaming=\"true\" RTPMulticast=\"false\" RTP_RTSP_TCP=\"true\"/></tr2:Capabilities>",
	  G.nst, G.audio ? (G.talk ? " AudioSource AudioEncoder AudioOutput AudioDecoder" : " AudioSource AudioEncoder") : "");
}

enum { SV_DEVICE, SV_MEDIA, SV_MEDIA2, SV_EVENT, SV_SUB };

static void cap_events(void);

/* ---- the services ---- */

static int stream_of_token(const char *b, const char *end, int *idx)
{
	char t[48];

	*idx = 0;
	if (!get_text(b, end, "ProfileToken", t, sizeof t) || !t[0]) return 1;
	for (int i = 0; i < G.nst; i++) {
		char p[24];

		profile_name(i, p, sizeof p);
		if (!strcmp(t, p)) { *idx = i; return 1; }
	}
	return 0;
}

static int no_profile(void) { return fault(1, "ter:InvalidArgs", "ter:NoProfile", "The requested profile token does not exist"); }

static int op_datetime(void)
{
	time_t t = time(NULL);
	struct tm u, l;

	gmtime_r(&t, &u);
	localtime_r(&t, &l);
	P("<tds:GetSystemDateAndTimeResponse><tds:SystemDateAndTime><tt:DateTimeType>%s</tt:DateTimeType><tt:DaylightSavings>%s</tt:DaylightSavings>",
	  "NTP", l.tm_isdst > 0 ? "true" : "false");
	PS("<tt:TimeZone><tt:TZ>"); PX(G.tz); PS("</tt:TZ></tt:TimeZone>");
	P("<tt:UTCDateTime><tt:Time><tt:Hour>%d</tt:Hour><tt:Minute>%d</tt:Minute><tt:Second>%d</tt:Second></tt:Time><tt:Date><tt:Year>%d</tt:Year><tt:Month>%d</tt:Month><tt:Day>%d</tt:Day></tt:Date></tt:UTCDateTime>",
	  u.tm_hour, u.tm_min, u.tm_sec, u.tm_year + 1900, u.tm_mon + 1, u.tm_mday);
	P("<tt:LocalDateTime><tt:Time><tt:Hour>%d</tt:Hour><tt:Minute>%d</tt:Minute><tt:Second>%d</tt:Second></tt:Time><tt:Date><tt:Year>%d</tt:Year><tt:Month>%d</tt:Month><tt:Day>%d</tt:Day></tt:Date></tt:LocalDateTime>",
	  l.tm_hour, l.tm_min, l.tm_sec, l.tm_year + 1900, l.tm_mon + 1, l.tm_mday);
	PS("</tds:SystemDateAndTime></tds:GetSystemDateAndTimeResponse>");
	return 200;
}

static int op_device(const char *act, const char *b, const char *end)
{
	if (!strcmp(act, "GetSystemDateAndTime")) return op_datetime();
	if (!strcmp(act, "GetDeviceInformation")) {
		PS("<tds:GetDeviceInformationResponse>");
		PXe("tds:Manufacturer", G.vendor); PXe("tds:Model", G.model); PXe("tds:FirmwareVersion", G.fw);
		PXe("tds:SerialNumber", G.serial); PXe("tds:HardwareId", G.hw);
		PS("</tds:GetDeviceInformationResponse>");
		return 200;
	}
	if (!strcmp(act, "GetCapabilities")) {
		PS("<tds:GetCapabilitiesResponse><tds:Capabilities><tt:Device><tt:XAddr>"); xaddr("device_service");
		PS("</tt:XAddr><tt:Network><tt:IPFilter>false</tt:IPFilter><tt:ZeroConfiguration>false</tt:ZeroConfiguration><tt:IPVersion6>false</tt:IPVersion6><tt:DynDNS>false</tt:DynDNS></tt:Network>"
		   "<tt:System><tt:DiscoveryResolve>true</tt:DiscoveryResolve><tt:DiscoveryBye>true</tt:DiscoveryBye><tt:RemoteDiscovery>false</tt:RemoteDiscovery><tt:SystemBackup>false</tt:SystemBackup>"
		   "<tt:SystemLogging>false</tt:SystemLogging><tt:FirmwareUpgrade>false</tt:FirmwareUpgrade><tt:SupportedVersions><tt:Major>2</tt:Major><tt:Minor>5</tt:Minor></tt:SupportedVersions></tt:System>"
		   "<tt:Security><tt:TLS1.1>false</tt:TLS1.1><tt:TLS1.2>false</tt:TLS1.2><tt:OnboardKeyGeneration>false</tt:OnboardKeyGeneration><tt:AccessPolicyConfig>false</tt:AccessPolicyConfig><tt:X.509Token>false</tt:X.509Token><tt:SAMLToken>false</tt:SAMLToken><tt:KerberosToken>false</tt:KerberosToken><tt:RELToken>false</tt:RELToken></tt:Security>"
		   "</tt:Device><tt:Events><tt:XAddr>"); xaddr("event_service");
		PS("</tt:XAddr><tt:WSSubscriptionPolicySupport>false</tt:WSSubscriptionPolicySupport><tt:WSPullPointSupport>true</tt:WSPullPointSupport><tt:WSPausableSubscriptionManagerInterfaceSupport>false</tt:WSPausableSubscriptionManagerInterfaceSupport></tt:Events><tt:Media><tt:XAddr>"); xaddr("media_service");
		PS("</tt:XAddr><tt:StreamingCapabilities><tt:RTPMulticast>false</tt:RTPMulticast><tt:RTP_TCP>true</tt:RTP_TCP><tt:RTP_RTSP_TCP>true</tt:RTP_RTSP_TCP></tt:StreamingCapabilities></tt:Media>"
		   "</tds:Capabilities></tds:GetCapabilitiesResponse>");
		return 200;
	}
	if (!strcmp(act, "GetServices")) {
		char v[16];
		int cap = get_text(b, end, "IncludeCapability", v, sizeof v) && (!strcmp(v, "true") || !strcmp(v, "1"));

		PS("<tds:GetServicesResponse><tds:Service><tds:Namespace>http://www.onvif.org/ver10/device/wsdl</tds:Namespace><tds:XAddr>"); xaddr("device_service");
		PS("</tds:XAddr>"); if (cap) { PS("<tds:Capabilities>"); cap_device(); PS("</tds:Capabilities>"); }
		PS("<tds:Version><tt:Major>2</tt:Major><tt:Minor>5</tt:Minor></tds:Version></tds:Service>");
		PS("<tds:Service><tds:Namespace>http://www.onvif.org/ver10/media/wsdl</tds:Namespace><tds:XAddr>"); xaddr("media_service");
		PS("</tds:XAddr>"); if (cap) { PS("<tds:Capabilities>"); cap_media(); PS("</tds:Capabilities>"); }
		PS("<tds:Version><tt:Major>2</tt:Major><tt:Minor>6</tt:Minor></tds:Version></tds:Service>");
		PS("<tds:Service><tds:Namespace>http://www.onvif.org/ver20/media/wsdl</tds:Namespace><tds:XAddr>"); xaddr("media2_service");
		PS("</tds:XAddr>"); if (cap) { PS("<tds:Capabilities>"); cap_media2(); PS("</tds:Capabilities>"); }
		PS("<tds:Version><tt:Major>2</tt:Major><tt:Minor>0</tt:Minor></tds:Version></tds:Service>");
		PS("<tds:Service><tds:Namespace>http://www.onvif.org/ver10/events/wsdl</tds:Namespace><tds:XAddr>"); xaddr("event_service");
		PS("</tds:XAddr>"); if (cap) { PS("<tds:Capabilities>"); cap_events(); PS("</tds:Capabilities>"); }
		PS("<tds:Version><tt:Major>2</tt:Major><tt:Minor>6</tt:Minor></tds:Version></tds:Service></tds:GetServicesResponse>");
		return 200;
	}
	if (!strcmp(act, "GetServiceCapabilities")) {
		PS("<tds:GetServiceCapabilitiesResponse>"); cap_device(); PS("</tds:GetServiceCapabilitiesResponse>");
		return 200;
	}
	if (!strcmp(act, "GetScopes")) {
		PS("<tds:GetScopesResponse>"); x_scopes_soap(); PS("</tds:GetScopesResponse>");
		return 200;
	}
	if (!strcmp(act, "GetHostname")) {
		char h[64];

		if (gethostname(h, sizeof h - 1)) scpy(h, sizeof h, "camera");
		h[sizeof h - 1] = 0;
		PS("<tds:GetHostnameResponse><tds:HostnameInformation><tt:FromDHCP>false</tt:FromDHCP>"); PXe("tt:Name", h);
		PS("</tds:HostnameInformation></tds:GetHostnameResponse>");
		return 200;
	}
	if (!strcmp(act, "GetNetworkInterfaces")) {
		char ip[48];

		scpy(ip, sizeof ip, g_ip);
		iface_ip(ip, sizeof ip);
		PS("<tds:GetNetworkInterfacesResponse><tds:NetworkInterfaces token=\""); PX(p_iface);
		PS("\"><tt:Enabled>true</tt:Enabled><tt:Info><tt:Name>"); PX(p_iface);
		P("</tt:Name><tt:HwAddress>%s</tt:HwAddress><tt:MTU>1500</tt:MTU></tt:Info>", G.mac);
		P("<tt:IPv4><tt:Enabled>true</tt:Enabled><tt:Config><tt:Manual><tt:Address>%s</tt:Address><tt:PrefixLength>%d</tt:PrefixLength></tt:Manual><tt:DHCP>false</tt:DHCP></tt:Config></tt:IPv4>", ip, iface_prefix());
		PS("</tds:NetworkInterfaces></tds:GetNetworkInterfacesResponse>");
		return 200;
	}
	if (!strcmp(act, "GetDNS")) {
		PS("<tds:GetDNSResponse><tds:DNSInformation><tt:FromDHCP>true</tt:FromDHCP></tds:DNSInformation></tds:GetDNSResponse>");
		return 200;
	}
	if (!strcmp(act, "GetNTP")) {
		PS("<tds:GetNTPResponse><tds:NTPInformation><tt:FromDHCP>false</tt:FromDHCP></tds:NTPInformation></tds:GetNTPResponse>");
		return 200;
	}
	if (!strcmp(act, "GetUsers")) { PS("<tds:GetUsersResponse/>"); return 200; }
	if (!strcmp(act, "GetDiscoveryMode")) {
		PS("<tds:GetDiscoveryModeResponse><tds:DiscoveryMode>Discoverable</tds:DiscoveryMode></tds:GetDiscoveryModeResponse>");
		return 200;
	}
	if (!strcmp(act, "GetWsdlUrl")) {
		PS("<tds:GetWsdlUrlResponse><tds:WsdlUrl>http://www.onvif.org/Documents/Specifications.aspx</tds:WsdlUrl></tds:GetWsdlUrlResponse>");
		return 200;
	}
	return 0;
}

/* Get[Compatible]<Kind>Configuration[s] of Media (ver10): returns 0 when the name is not of that shape */
static int op_media_cfg(const char *act, const char *b, const char *end)
{
	const char *p = act;
	int compat = 0, k = -1, plural = 0;
	size_t l;

	if (strncmp(p, "Get", 3)) return 0;
	p += 3;
	if (!strncmp(p, "Compatible", 10)) { compat = 1; p += 10; }
	for (int i = 0; i < 6; i++) {
		l = strlen(kname[i]);
		if (!strncmp(p, kname[i], l) && !strncmp(p + l, "Configuration", 13)) { k = i; p += l + 13; break; }
	}
	if (k < 0) return 0;
	if (*p == 's' && !p[1]) plural = 1;
	else if (*p || compat) return 0;
	{
		char tok[48], t[40];
		int have = plural ? 0 : get_text(b, end, "ConfigurationToken", tok, sizeof tok);
		int cnt = kcount(k), done = 0;

		P("<trt:Get%s%sConfiguration%sResponse>", compat ? "Compatible" : "", kname[k], plural ? "s" : "");
		for (int i = 0; i < cnt; i++) {
			ktok(k, i, t, sizeof t);
			if (have && strcmp(tok, t)) continue;
			kemit(plural ? "trt:Configurations" : "trt:Configuration", k, i, 0);
			done++;
		}
		if (!plural && (!done)) return fault(1, "ter:InvalidArgs", "ter:NoConfig", "The configuration token does not exist");
		P("</trt:Get%s%sConfiguration%sResponse>", compat ? "Compatible" : "", kname[k], plural ? "s" : "");
	}
	return 200;
}

static int op_media(const char *act, const char *b, const char *end)
{
	int i, r;

	if (!strcmp(act, "GetServiceCapabilities")) { PS("<trt:GetServiceCapabilitiesResponse>"); cap_media(); PS("</trt:GetServiceCapabilitiesResponse>"); return 200; }
	if (!strcmp(act, "GetProfiles")) {
		PS("<trt:GetProfilesResponse>");
		for (i = 0; i < G.nst; i++) profile1("trt:Profiles", i);
		PS("</trt:GetProfilesResponse>");
		return 200;
	}
	if (!strcmp(act, "GetProfile")) {
		char t[48];

		if (!get_text(b, end, "ProfileToken", t, sizeof t) || !stream_of_token(b, end, &i)) return no_profile();
		PS("<trt:GetProfileResponse>"); profile1("trt:Profile", i); PS("</trt:GetProfileResponse>");
		return 200;
	}
	if (!strcmp(act, "GetStreamUri") || !strcmp(act, "GetSnapshotUri")) {
		int snap = act[3] == 'S' && act[4] == 'n';

		if (!stream_of_token(b, end, &i)) return no_profile();
		P("<trt:Get%sUriResponse><trt:MediaUri><tt:Uri>", snap ? "Snapshot" : "Stream");
		if (snap) url_web("/cgi-bin/currentpic.cgi"); else P("rtsp://%s:%d/%s", g_ip, G.rtsp_port, G.st[i].rp);
		P("</tt:Uri><tt:InvalidAfterConnect>false</tt:InvalidAfterConnect><tt:InvalidAfterReboot>false</tt:InvalidAfterReboot><tt:Timeout>PT0S</tt:Timeout></trt:MediaUri></trt:Get%sUriResponse>", snap ? "Snapshot" : "Stream");
		return 200;
	}
	if (!strcmp(act, "GetVideoSources")) {
		P("<trt:GetVideoSourcesResponse><trt:VideoSources token=\"VideoSource_1\"><tt:Framerate>%d</tt:Framerate><tt:Resolution><tt:Width>%d</tt:Width><tt:Height>%d</tt:Height></tt:Resolution></trt:VideoSources></trt:GetVideoSourcesResponse>",
		  G.st[0].fps, G.mw, G.mh);
		return 200;
	}
	if (!strcmp(act, "GetAudioSources")) {
		PS("<trt:GetAudioSourcesResponse>");
		if (G.audio) PS("<trt:AudioSources token=\"AudioSource_1\"><tt:Channels>1</tt:Channels></trt:AudioSources>");
		PS("</trt:GetAudioSourcesResponse>");
		return 200;
	}
	if (!strcmp(act, "GetAudioOutputs")) {
		PS("<trt:GetAudioOutputsResponse>");
		if (kcount(K_AOC)) PS("<trt:AudioOutputs token=\"AudioOutput_1\"/>");
		PS("</trt:GetAudioOutputsResponse>");
		return 200;
	}
	if (!strcmp(act, "GetGuaranteedNumberOfVideoEncoderInstances")) {
		P("<trt:GetGuaranteedNumberOfVideoEncoderInstancesResponse><trt:TotalNumber>%d</trt:TotalNumber><trt:H264>%d</trt:H264></trt:GetGuaranteedNumberOfVideoEncoderInstancesResponse>", G.nst, G.nst);
		return 200;
	}
	r = op_media_cfg(act, b, end);
	if (r) return r;
	if (!strncmp(act, "Set", 3) || !strncmp(act, "Add", 3) || !strncmp(act, "Remove", 6))
		return fault(0, "ter:Action", "ter:ConfigModify", "The configuration is read-only");
	return 0;
}

static int op_media2(const char *act, const char *b, const char *end)
{
	const char *p = act;
	int i, k = -1;
	size_t l;

	if (!strcmp(act, "GetServiceCapabilities")) { PS("<tr2:GetServiceCapabilitiesResponse>"); cap_media2(); PS("</tr2:GetServiceCapabilitiesResponse>"); return 200; }
	if (!strcmp(act, "GetProfiles")) {
		char t[48];
		int only = get_text(b, end, "Token", t, sizeof t) && t[0], n = 0;

		PS("<tr2:GetProfilesResponse>");
		for (i = 0; i < G.nst; i++) {
			char pn[24];

			profile_name(i, pn, sizeof pn);
			if (only && strcmp(pn, t)) continue;
			profile2("tr2:Profiles", i);
			n++;
		}
		if (only && !n) return no_profile();
		PS("</tr2:GetProfilesResponse>");
		return 200;
	}
	if (!strcmp(act, "GetStreamUri") || !strcmp(act, "GetSnapshotUri")) {
		int snap = act[3] == 'S' && act[4] == 'n';

		if (!stream_of_token(b, end, &i)) return no_profile();
		P("<tr2:Get%sUriResponse><tr2:Uri>", snap ? "Snapshot" : "Stream");
		if (snap) url_web("/cgi-bin/currentpic.cgi"); else P("rtsp://%s:%d/%s", g_ip, G.rtsp_port, G.st[i].rp);
		P("</tr2:Uri></tr2:Get%sUriResponse>", snap ? "Snapshot" : "Stream");
		return 200;
	}
	if (strncmp(p, "Get", 3) == 0) {
		p += 3;
		for (i = 0; i < 6; i++) {
			l = strlen(kname[i]);
			if (!strncmp(p, kname[i], l) && !strcmp(p + l, "Configurations")) { k = i; break; }
		}
	}
	if (k >= 0) {
		char tok[48], t[40];
		int have = get_text(b, end, "ConfigurationToken", tok, sizeof tok) && tok[0];

		P("<tr2:Get%sConfigurationsResponse>", kname[k]);
		for (i = 0; i < kcount(k); i++) {
			ktok(k, i, t, sizeof t);
			if (have && strcmp(tok, t)) continue;
			kemit("tr2:Configurations", k, i, 1);
		}
		P("</tr2:Get%sConfigurationsResponse>", kname[k]);
		return 200;
	}
	if (!strncmp(act, "Set", 3) || !strncmp(act, "Create", 6) || !strncmp(act, "Delete", 6) || !strncmp(act, "Add", 3) || !strncmp(act, "Remove", 6))
		return fault(0, "ter:Action", "ter:ConfigModify", "The configuration is read-only");
	return 0;
}

/* ---- Events service: PullPoint subscriptions on the motion state tc100_rtsp writes ---- */

#define MAXSUB 4
#define PULL_MAX_S 10		/* longest PullMessages wait (the connection stays pending, the loop never blocks) */

struct sub { int id; long long expire; int reported; };	/* id 0 = free; reported -1: next pull says Initialized */
static struct sub subs[MAXSUB];
static int g_subseq, g_motion;
static long g_motion_t;
static const char *p_motion = "/tmp/rec_control";
static int g_req_sub, g_defer_wait, g_defer_sub;	/* id in the request path; PullMessages left pending */

static int motion_read(void)	/* "1" in the file = motion */
{
	char b[8];
	int n = slurp(p_motion, b, sizeof b);

	return n > 0 && b[0] == '1';
}

static void motion_poll(void)
{
	int m = motion_read();

	if (m != g_motion) { g_motion = m; g_motion_t = (long)time(NULL); }
}

static void subs_sweep(long long t)
{
	for (int i = 0; i < MAXSUB; i++) if (subs[i].id && t >= subs[i].expire) subs[i].id = 0;
}

static struct sub *find_sub(int id)
{
	for (int i = 0; id && i < MAXSUB; i++) if (subs[i].id == id) return &subs[i];
	return NULL;
}

/* "PT10S", "PT1M30S", "PT1.5S" -> seconds; d when it is not such a duration */
static int dur_s(const char *s, int d)
{
	int tot = 0, n = 0, dg = 0;

	if (s[0] != 'P' || s[1] != 'T') return d;
	for (s += 2; *s; s++) {
		if (*s >= '0' && *s <= '9') { if (n < 100000) n = n * 10 + *s - '0'; dg = 1; }
		else if (*s == '.' && dg) { while (s[1] >= '0' && s[1] <= '9') s++; }
		else if (!dg) return d;
		else {
			if (*s == 'H') tot += n * 3600; else if (*s == 'M') tot += n * 60; else if (*s == 'S') tot += n; else return d;
			if (tot > 1000000) tot = 1000000;	/* no int overflow on "PT99999H99999H..."; callers clamp further */
			n = 0; dg = 0;
		}
	}
	return dg ? d : tot;
}

static void iso(long t, char *o, size_t n)
{
	time_t tt = (time_t)t;
	struct tm u;

	gmtime_r(&tt, &u);
	snprintf(o, n, "%04d-%02d-%02dT%02d:%02d:%02dZ", u.tm_year + 1900, u.tm_mon + 1, u.tm_mday, u.tm_hour, u.tm_min, u.tm_sec);
}

static long sub_term(const struct sub *s) { return (long)time(NULL) + (long)((s->expire - now_ms()) / 1000); }

/* the two notifications of the motion state: the video source alarm and the cell motion detector rule */
static void emit_motion_msgs(const char *op)
{
	char ut[32];

	iso(strcmp(op, "Initialized") ? g_motion_t : (long)time(NULL), ut, sizeof ut);
	for (int k = 0; k < 2; k++) {
		P("<wsnt:NotificationMessage><wsnt:Topic Dialect=\"http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet\">%s</wsnt:Topic><wsnt:Message>"
		  "<tt:Message UtcTime=\"%s\" PropertyOperation=\"%s\"><tt:Source>", k ? "tns1:RuleEngine/CellMotionDetector/Motion" : "tns1:VideoSource/MotionAlarm", ut, op);
		if (k) PS("<tt:SimpleItem Name=\"VideoSourceConfigurationToken\" Value=\"VideoSourceConfig_1\"/><tt:SimpleItem Name=\"VideoAnalyticsConfigurationToken\" Value=\"VideoAnalyticsConfig_1\"/><tt:SimpleItem Name=\"Rule\" Value=\"MotionRule\"/>");
		else PS("<tt:SimpleItem Name=\"VideoSourceToken\" Value=\"VideoSource_1\"/>");
		P("</tt:Source><tt:Data><tt:SimpleItem Name=\"%s\" Value=\"%s\"/></tt:Data></tt:Message></wsnt:Message></wsnt:NotificationMessage>",
		  k ? "IsMotion" : "State", g_motion ? "true" : "false");
	}
}

/* PullMessagesResponse of a subscription (s may have vanished: nothing to report) */
static void emit_pull(struct sub *s)
{
	char a[32], b[32];

	iso((long)time(NULL), a, sizeof a);
	iso(s ? sub_term(s) : (long)time(NULL), b, sizeof b);
	P("<tev:PullMessagesResponse><tev:CurrentTime>%s</tev:CurrentTime><tev:TerminationTime>%s</tev:TerminationTime>", a, b);
	if (s && s->reported != g_motion) {
		emit_motion_msgs(s->reported < 0 ? "Initialized" : "Changed");
		s->reported = g_motion;
	}
	PS("</tev:PullMessagesResponse>");
}

#define TOPIC_DESC "<tt:MessageDescription IsProperty=\"true\"><tt:Source><tt:SimpleItemDescription Name=\"%s\" Type=\"tt:ReferenceToken\"/>%s</tt:Source>" \
	"<tt:Data><tt:SimpleItemDescription Name=\"%s\" Type=\"xs:boolean\"/></tt:Data></tt:MessageDescription>"

static void cap_events(void)
{
	PS("<tev:Capabilities WSSubscriptionPolicySupport=\"false\" WSPullPointSupport=\"true\" WSPausableSubscriptionManagerInterfaceSupport=\"false\" "
	   "MaxNotificationProducers=\"4\" MaxPullPoints=\"4\" PersistentNotificationStorage=\"false\"/>");
}

static int op_events(int svc, const char *act, const char *b, const char *end)
{
	char v[48];
	struct sub *s;

	if (!strcmp(act, "GetServiceCapabilities")) { PS("<tev:GetServiceCapabilitiesResponse>"); cap_events(); PS("</tev:GetServiceCapabilitiesResponse>"); return 200; }
	if (svc == SV_EVENT) {
		if (!strcmp(act, "GetEventProperties")) {
			PS("<tev:GetEventPropertiesResponse><tev:TopicNamespaceLocation>http://www.onvif.org/onvif/ver10/topics/topicns.xml</tev:TopicNamespaceLocation>"
			   "<wsnt:FixedTopicSet>true</wsnt:FixedTopicSet><wstop:TopicSet><tns1:RuleEngine><tns1:CellMotionDetector><tns1:Motion wstop:topic=\"true\">");
			P(TOPIC_DESC, "VideoSourceConfigurationToken", "<tt:SimpleItemDescription Name=\"VideoAnalyticsConfigurationToken\" Type=\"tt:ReferenceToken\"/><tt:SimpleItemDescription Name=\"Rule\" Type=\"xs:string\"/>", "IsMotion");
			PS("</tns1:Motion></tns1:CellMotionDetector></tns1:RuleEngine><tns1:VideoSource><tns1:MotionAlarm wstop:topic=\"true\">");
			P(TOPIC_DESC, "VideoSourceToken", "", "State");
			PS("</tns1:MotionAlarm></tns1:VideoSource></wstop:TopicSet>"
			   "<wsnt:TopicExpressionDialect>http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet</wsnt:TopicExpressionDialect>"
			   "<wsnt:TopicExpressionDialect>http://docs.oasis-open.org/wsn/t-1/TopicExpression/Concrete</wsnt:TopicExpressionDialect>"
			   "<tev:MessageContentFilterDialect>http://www.onvif.org/ver10/tev/messageContentFilter/ItemFilter</tev:MessageContentFilterDialect>"
			   "<tev:MessageContentSchemaLocation>http://www.onvif.org/onvif/ver10/schema/onvif.xsd</tev:MessageContentSchemaLocation></tev:GetEventPropertiesResponse>");
			return 200;
		}
		if (!strcmp(act, "CreatePullPointSubscription")) {
			int secs = 60, i;
			char a[32], tm[32];

			if (get_text(b, end, "InitialTerminationTime", v, sizeof v)) secs = dur_s(v, 60);
			if (secs < 5) secs = 5;
			if (secs > 3600) secs = 3600;
			subs_sweep(now_ms());
			for (i = 0; i < MAXSUB && subs[i].id; i++) ;
			if (i == MAXSUB) return fault(0, "ter:Action", "ter:TooManySubscriptions", "Too many pull point subscriptions");
			if (++g_subseq <= 0) g_subseq = 1;
			subs[i].id = g_subseq;
			subs[i].expire = now_ms() + secs * 1000LL;
			subs[i].reported = -1;
			iso((long)time(NULL), a, sizeof a);
			iso(sub_term(&subs[i]), tm, sizeof tm);
			P("<tev:CreatePullPointSubscriptionResponse><tev:SubscriptionReference><wsa:Address>http://%s:%d/onvif/subscription?id=%d</wsa:Address></tev:SubscriptionReference>"
			  "<wsnt:CurrentTime>%s</wsnt:CurrentTime><wsnt:TerminationTime>%s</wsnt:TerminationTime></tev:CreatePullPointSubscriptionResponse>", g_ip, G.port, subs[i].id, a, tm);
			return 200;
		}
		return 0;
	}
	if (strcmp(act, "PullMessages") && strcmp(act, "Renew") && strcmp(act, "Unsubscribe") && strcmp(act, "SetSynchronizationPoint")) return 0;
	s = find_sub(g_req_sub);
	if (!s) return fault(1, "ter:InvalidArgs", "ter:ResourceUnknown", "The subscription does not exist or has expired");
	if (!strcmp(act, "Unsubscribe")) { s->id = 0; PS("<wsnt:UnsubscribeResponse/>"); return 200; }
	if (!strcmp(act, "SetSynchronizationPoint")) { s->reported = -1; PS("<tev:SetSynchronizationPointResponse/>"); return 200; }
	if (!strcmp(act, "Renew")) {
		char a[32], tm[32];
		int secs = get_text(b, end, "TerminationTime", v, sizeof v) ? dur_s(v, 60) : 60;

		if (secs < 5) secs = 5;
		if (secs > 3600) secs = 3600;
		s->expire = now_ms() + secs * 1000LL;
		iso((long)time(NULL), a, sizeof a);
		iso(sub_term(s), tm, sizeof tm);
		P("<wsnt:RenewResponse><wsnt:TerminationTime>%s</wsnt:TerminationTime><wsnt:CurrentTime>%s</wsnt:CurrentTime></wsnt:RenewResponse>", tm, a);
		return 200;
	}
	{	/* PullMessages: answer now when there is something, else keep the connection until a change or the timeout */
		int wait = get_text(b, end, "Timeout", v, sizeof v) ? dur_s(v, 0) : 0;

		if (wait > PULL_MAX_S) wait = PULL_MAX_S;
		if (s->reported != g_motion || wait <= 0) { emit_pull(s); return 200; }
		g_defer_wait = wait;
		g_defer_sub = s->id;
		return -1;
	}
}

static int pre_auth(const char *act)
{
	return !strcmp(act, "GetSystemDateAndTime") || !strcmp(act, "GetServices") || !strcmp(act, "GetCapabilities") ||
		!strcmp(act, "GetServiceCapabilities") || !strcmp(act, "GetWsdlUrl");
}

/* one SOAP request; the answer (without HTTP header) is left in ob; returns the HTTP status */
static int handle_soap(int svc, const char *b, int n)
{
	char act[64];
	const char *rest = NULL, *end = b + n;
	int r = 0;

	if (!body_action(b, n, act, sizeof act, &rest)) return fault(1, "ter:InvalidArgs", NULL, "Not a SOAP request");
	if (!pre_auth(act) && !check_auth(b, n)) {
		dprintf(2, "tc100-onvifd: %s refused (not authorized)\n", act);
		return fault(1, "ter:NotAuthorized", NULL, "Sender not authorized");
	}
	env_begin();
	g_ver2 = svc == SV_MEDIA2;
	if (svc == SV_DEVICE) r = op_device(act, rest, end);
	else if (svc == SV_MEDIA) r = op_media(act, rest, end);
	else if (svc == SV_EVENT || svc == SV_SUB) r = op_events(svc, act, rest, end);
	else r = op_media2(act, rest, end);
	if (!r) return fault(0, "ter:ActionNotSupported", NULL, "Optional action not implemented");
	if (r == -1) return -1;	/* PullMessages left pending */
	if (r != 200) return r;	/* a fault replaced the output */
	env_end();
	if (oerr) return fault(0, "ter:Action", NULL, "Answer too large");
	return 200;
}

/* ---- HTTP ---- */

struct conn { int fd, len, pending, subid; u_int32_t ip; long long deadline, pend_end; char buf[REQ_MAX + 2]; };
static struct conn cn[MAXCONN];

static void send_all(int fd, const char *p, int n)
{
	struct timeval tv;
	int fl = fcntl(fd, F_GETFL);
	long long t0 = now_ms(), left;

	/* the accepted sockets are non-blocking (select loop): blocking again here, so that SO_SNDTIMEO bounds the send
	 * instead of an EAGAIN cutting an answer larger than the socket buffer (GetProfiles, Media2: up to 24 KB) */
	if (fl >= 0 && (fl & O_NONBLOCK)) fcntl(fd, F_SETFL, fl & ~O_NONBLOCK);
	while (n > 0) {	/* 3 s for the whole answer, not per send(): a peer trickling its ACKs cannot hold the loop longer */
		left = 3000 - (now_ms() - t0);
		if (left <= 0) return;
		if (left < 100) left = 100;
		tv.tv_sec = (time_t)(left / 1000); tv.tv_usec = (suseconds_t)(left % 1000 * 1000);
		setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);
		long w = send(fd, p, n, MSG_NOSIGNAL);

		if (w <= 0) {
			if (w < 0 && errno == EINTR) continue;
			return;
		}
		p += w;
		n -= (int)w;
	}
}

static void reply(int fd, int status, const char *ctype, const char *body, int blen)
{
	char h[256];
	const char *st = status == 200 ? "200 OK" : status == 400 ? "400 Bad Request" : status == 405 ? "405 Method Not Allowed" :
		status == 413 ? "413 Payload Too Large" : status == 503 ? "503 Service Unavailable" : "500 Internal Server Error";
	int hl = snprintf(h, sizeof h, "HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nConnection: close\r\n\r\n", st, ctype, blen);

	send_all(fd, h, hl);
	send_all(fd, body, blen);
}

static void conn_close(struct conn *c)
{
	if (c->fd >= 0) close(c->fd);
	c->fd = -1;
	c->len = 0;
	c->pending = 0;
}

/* returns 1 when the connection stays open (a pending PullMessages) */
static int process(struct conn *c, int hdr_end, int clen)
{
	char *b = c->buf, path[128], method[8];
	struct sockaddr_in la;
	socklen_t ll = sizeof la;
	int i = 0, k = 0, st, svc;

	while (b[i] && b[i] != ' ' && k < 7) method[k++] = b[i++];
	method[k] = 0;
	while (b[i] == ' ') i++;
	k = 0;
	while (b[i] && b[i] != ' ' && b[i] != '\r' && k < 127) path[k++] = b[i++];
	path[k] = 0;
	if (!getsockname(c->fd, (struct sockaddr *)&la, &ll)) scpy(g_ip, sizeof g_ip, inet_ntoa(la.sin_addr));
	else scpy(g_ip, sizeof g_ip, "127.0.0.1");
	if (!strcmp(method, "GET") || !strcmp(method, "HEAD")) {
		reply(c->fd, 200, "text/plain", "tc100-onvifd\n", 13);
		return 0;
	}
	if (strcmp(method, "POST")) { reply(c->fd, 405, "text/plain", "", 0); return 0; }
	svc = strstr(path, "subscription") ? SV_SUB : strstr(path, "event") ? SV_EVENT : strstr(path, "media2") ? SV_MEDIA2 : strstr(path, "media") ? SV_MEDIA : SV_DEVICE;
	g_req_sub = 0;
	g_peer = c->ip;
	{
		const char *q = strstr(path, "id=");

		if (q) g_req_sub = num_at(q + 3, 0);
	}
	st = handle_soap(svc, b + hdr_end, clen);
	if (st == -1) {
		c->pending = 1;
		c->subid = g_defer_sub;
		c->pend_end = now_ms() + g_defer_wait * 1000LL;
		c->deadline = c->pend_end + 3000;
		return 1;
	}
	reply(c->fd, st, "application/soap+xml; charset=utf-8", ob, ol);
	return 0;
}

/* answer a pending PullMessages (change, timeout or vanished subscription) and close */
static void pull_finish(struct conn *c)
{
	env_begin();
	emit_pull(find_sub(c->subid));
	env_end();
	reply(c->fd, oerr ? 500 : 200, "application/soap+xml; charset=utf-8", ob, ol);
	conn_close(c);
}

/* the value of a header (case-insensitive name incl. colon) in [h, h+n), or NULL */
static const char *hdr_val(const char *h, int n, const char *name)
{
	size_t l = strlen(name);

	for (const char *p = h; p + l < h + n; p++) {
		if ((p == h || p[-1] == '\n') && !strncasecmp(p, name, l)) {
			p += l;
			while (*p == ' ') p++;
			return p;
		}
	}
	return NULL;
}

static void conn_read(struct conn *c)
{
	long r;
	char *he;

	if (c->pending) {	/* a pull is waiting: only a closed connection matters */
		char t[64];

		r = recv(c->fd, t, sizeof t, 0);
		if (r == 0 || (r < 0 && errno != EAGAIN && errno != EINTR)) conn_close(c);
		return;
	}
	r = recv(c->fd, c->buf + c->len, REQ_MAX + 1 - c->len, 0);

	if (r < 0) { if (errno == EAGAIN || errno == EINTR) return; conn_close(c); return; }
	if (r == 0) { conn_close(c); return; }
	c->len += (int)r;
	c->buf[c->len] = 0;
	he = strstr(c->buf, "\r\n\r\n");
	if (he) {
		int hdr_end = (int)(he - c->buf) + 4, clen = 0, need;
		const char *v = hdr_val(c->buf, hdr_end, "content-length:");

		if (v) clen = num_at(v, 0);
		if (v && clen > REQ_MAX - hdr_end) { reply(c->fd, 413, "text/plain", "", 0); conn_close(c); return; }
		need = hdr_end + clen;
		if (c->len >= need) {
			c->buf[need] = 0;
			if (!process(c, hdr_end, clen)) conn_close(c);
			return;
		}
	}
	if (c->len > REQ_MAX) { reply(c->fd, 413, "text/plain", "", 0); conn_close(c); }
}

static void conn_accept(void)
{
	struct sockaddr_in pa;
	socklen_t pl = sizeof pa;
	int f = accept(g_lfd, (struct sockaddr *)&pa, &pl), i;

	if (f < 0) return;
	if (!allowed(n2h(pa.sin_addr.s_addr))) { close(f); return; }
	{	/* at most PERIP of the MAXCONN slots for one address (review 2026-11-12: six idle connections from one host
		 * held every slot); 127/8 (the health check) is not limited */
		u_int32_t ip = n2h(pa.sin_addr.s_addr);
		int same = 0;

		for (i = 0; i < MAXCONN; i++) if (cn[i].fd >= 0 && cn[i].ip == ip) same++;
		if ((ip >> 24) != 127 && same >= PERIP) { reply(f, 503, "text/plain", "", 0); close(f); return; }
	}
	for (i = 0; i < MAXCONN; i++) if (cn[i].fd < 0) break;
	if (i == MAXCONN) {
		reply(f, 503, "text/plain", "", 0);
		close(f);
		return;
	}
	fcntl(f, F_SETFL, fcntl(f, F_GETFL) | O_NONBLOCK);
	cn[i].fd = f;
	cn[i].ip = n2h(pa.sin_addr.s_addr);
	cn[i].len = 0;
	cn[i].pending = 0;
	cn[i].deadline = now_ms() + READ_MS;
}

/* ---- WS-Discovery ---- */

static void wsd_header(const char *action, const char *relates, const char *to)
{
	char id[48];

	g_seq++;
	uuid_make(id, sizeof id, (uint32_t)time(NULL) * 2654435761u ^ g_seq, (uint32_t)getpid() + g_seq * 7919u);
	ol = 0;	/* own envelope: the discovery namespaces */
	oerr = 0;
	P("<?xml version=\"1.0\" encoding=\"UTF-8\"?><s:Envelope xmlns:s=\"%s\" xmlns:a=\"http://schemas.xmlsoap.org/ws/2004/08/addressing\" "
	  "xmlns:d=\"http://schemas.xmlsoap.org/ws/2005/04/discovery\" xmlns:dn=\"http://www.onvif.org/ver10/network/wsdl\" "
	  "xmlns:tds=\"http://www.onvif.org/ver10/device/wsdl\"><s:Header><a:MessageID>urn:uuid:%s</a:MessageID>", NS_S, id);
	if (relates && relates[0]) P("<a:RelatesTo>%s</a:RelatesTo>", relates);
	P("<a:To>%s</a:To><a:Action>%s</a:Action><d:AppSequence InstanceId=\"%u\" MessageNumber=\"%u\"/></s:Header><s:Body>", to, action, g_instance, g_seq);
}

static void wsd_match(const char *wrap, const char *item, const char *ip)
{
	P("<d:%s><d:%s><a:EndpointReference><a:Address>%s</a:Address></a:EndpointReference><d:Types>dn:NetworkVideoTransmitter tds:Device</d:Types><d:Scopes>",
	  wrap, item, G.uuid);
	scopes_text(1);
	P("</d:Scopes><d:XAddrs>http://%s:%d/onvif/device_service</d:XAddrs><d:MetadataVersion>1</d:MetadataVersion></d:%s></d:%s>", ip, G.port, item, wrap);
}

static void wsd_send(const struct sockaddr_in *to)
{
	if (oerr) return;
	sendto(g_ufd, ob, ol, 0, (const struct sockaddr *)to, sizeof *to);
}

static void wsd_multicast(const char *what)	/* Hello, Bye */
{
	struct sockaddr_in to;
	char ip[48];
	const char *act = !strcmp(what, "Hello") ? "http://schemas.xmlsoap.org/ws/2005/04/discovery/Hello" : "http://schemas.xmlsoap.org/ws/2005/04/discovery/Bye";

	if (g_ufd < 0 || !iface_ip(ip, sizeof ip)) return;
	memset(&to, 0, sizeof to);
	to.sin_family = AF_INET;
	to.sin_port = htons(3702);
	to.sin_addr.s_addr = inet_addr(WSD_ADDR);
	if (g_dport != 3702) to.sin_port = htons((uint16_t)g_dport);
	wsd_header(act, NULL, "urn:schemas-xmlsoap-org:ws:2005:04:discovery");
	if (!strcmp(what, "Hello")) {
		P("<d:Hello><a:EndpointReference><a:Address>%s</a:Address></a:EndpointReference><d:Types>dn:NetworkVideoTransmitter tds:Device</d:Types><d:Scopes>", G.uuid);
		scopes_text(1);
		P("</d:Scopes><d:XAddrs>http://%s:%d/onvif/device_service</d:XAddrs><d:MetadataVersion>1</d:MetadataVersion></d:Hello>", ip, G.port);
	} else {
		P("<d:Bye><a:EndpointReference><a:Address>%s</a:Address></a:EndpointReference></d:Bye>", G.uuid);
	}
	PS("</s:Body></s:Envelope>");
	wsd_send(&to);
}

static void udp_in(void)
{
	static char buf[4097];
	struct sockaddr_in from;
	socklen_t fl = sizeof from;
	long n = recvfrom(g_ufd, buf, sizeof buf - 1, 0, (struct sockaddr *)&from, &fl);
	const char *end;
	char mid[64], ip[48];
	int s;
	struct sockaddr_in me;
	socklen_t ml = sizeof me;
	int is_probe, is_resolve;

	if (n <= 0 || n >= (long)sizeof buf - 1) return;
	buf[n] = 0;
	if (!allowed(n2h(from.sin_addr.s_addr))) return;
	end = buf + n;
	is_probe = find_elem(buf, end, "Probe", NULL, NULL, &s) != NULL;
	is_resolve = !is_probe && find_elem(buf, end, "Resolve", NULL, NULL, &s) != NULL;
	if (!is_probe && !is_resolve) return;
	/* a SOAP envelope only, and at most WSD_RATE answers a second (review 2026-11-12: a 7-byte "<Probe>" from a
	 * spoofed source got a 1 KB answer, a reflector inside the allowed networks) */
	if (!find_elem(buf, end, "Envelope", NULL, NULL, &s)) return;
	if (is_probe) {	/* a Types filter that is not ours: no answer */
		char ty[200];

		if (get_text(buf, end, "Types", ty, sizeof ty) && ty[0] && !strstr(ty, "NetworkVideoTransmitter") && !strstr(ty, "Device")) return;
	} else {
		char ad[96];
		const char *rv = find_elem(buf, end, "Resolve", NULL, NULL, &s);

		/* the first Address after the Resolve tag (its EndpointReference), not a wsa:ReplyTo/Address of the header,
		 * which comes before the Body. find_elem's length stops at the first child tag, so search up to the end */
		if (!rv) return;
		get_text(rv, end, "Address", ad, sizeof ad);
		if (strcmp(ad, G.uuid)) return;
	}
	{	/* counted here, once the message is one we answer: probes for other types do not use the budget */
		static long long win;
		static int cnt;
		long long t = now_ms();

		if (t - win >= 1000) { win = t; cnt = 0; }
		if (++cnt > WSD_RATE) return;
	}
	get_text(buf, end, "MessageID", mid, sizeof mid);
	/* the address we have towards the sender: where the controller can reach us */
	s = socket(AF_INET, SOCK_DGRAM, 0);
	scpy(ip, sizeof ip, "127.0.0.1");
	if (s >= 0) {
		if (!connect(s, (struct sockaddr *)&from, sizeof from) && !getsockname(s, (struct sockaddr *)&me, &ml)) scpy(ip, sizeof ip, inet_ntoa(me.sin_addr));
		close(s);
	}
	if (p_ip && strcmp(ip, "127.0.0.1")) scpy(ip, sizeof ip, p_ip);
	wsd_header(is_probe ? "http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches" : "http://schemas.xmlsoap.org/ws/2005/04/discovery/ResolveMatches",
		mid, "http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous");
	if (is_probe) wsd_match("ProbeMatches", "ProbeMatch", ip);
	else wsd_match("ResolveMatches", "ResolveMatch", ip);
	PS("</s:Body></s:Envelope>");
	wsd_send(&from);
}

static int g_joined, g_hello;

/* join the group on the interface (the address may appear late: Wi-Fi), then say Hello once */
static void discovery_up(void)
{
	char ip[48];
	struct ip_mreq mr;

	if (g_ufd < 0 || !iface_ip(ip, sizeof ip)) return;
	memset(&mr, 0, sizeof mr);
	mr.imr_multiaddr.s_addr = inet_addr(WSD_ADDR);
	mr.imr_interface.s_addr = inet_addr(ip);
	if (!g_joined && setsockopt(g_ufd, IPPROTO_IP, IP_ADD_MEMBERSHIP, &mr, sizeof mr) == 0) {
		unsigned char ttl = 1;

		setsockopt(g_ufd, IPPROTO_IP, IP_MULTICAST_IF, &mr.imr_interface, sizeof mr.imr_interface);
		setsockopt(g_ufd, IPPROTO_IP, IP_MULTICAST_TTL, &ttl, sizeof ttl);
		g_joined = 1;
	}
	if (!g_hello) { wsd_multicast("Hello"); g_hello = 1; }
}

/* ---- main ---- */

static void on_term(int s) { (void)s; g_term = 1; }
static void on_hup(int s) { (void)s; g_hup = 1; }

static void set_str(const char *o, const char *v, char *d, size_t n, const char *flag)
{
	if (!strcmp(o, flag)) scpy(d, n, v);
}

int main(int argc, char **argv)
{
	int on = 1, i;
	struct sockaddr_in a;
	long long next_disc = 0, next_motion = 0;
	char buf[96];
	struct stream *ex = G.ex;

	G.port = 8081; G.web_port = 80;
	scpy(G.web_proto, sizeof G.web_proto, "http");
	scpy(G.policy, sizeof G.policy, "main-primary");
	scpy(G.vendor, sizeof G.vendor, "Anyka"); scpy(G.hw, sizeof G.hw, "AK3918"); scpy(G.loc, sizeof G.loc, "Earth");
	scpy(G.dname, sizeof G.dname, "Teckin"); scpy(G.model, sizeof G.model, "TC100");
	p_conf = env_or("ONVIFD_CONF_DIR", p_conf);
	p_scale = env_or("ONVIFD_SCALE_PARAM", p_scale);
	p_version = env_or("ONVIFD_VERSION_FILE", p_version);
	p_serial = env_or("ONVIFD_SERIAL_FILE", p_serial);
	p_iface = env_or("ONVIFD_IFACE", p_iface);
	p_ip = env_or("ONVIFD_IP", NULL);
	p_motion = env_or("ONVIFD_MOTION_FILE", p_motion);
	g_dport = num_at(env_or("ONVIFD_DISCOVERY_PORT", "3702"), 3702);
	memset(G.ex, 0, sizeof G.ex);
	for (i = 1; i + 1 < argc; i += 2) {
		const char *o = argv[i], *v = argv[i + 1];
		struct stream *s = NULL;
		int slot = 0;

		if (!strcmp(o, "-p")) G.port = num_at(v, 8081);
		else if (!strcmp(o, "-w")) G.web_port = num_at(v, 80);
		else if (!strcmp(o, "-r")) rtsp_cli = G.rtsp_port = num_at(v, 554);
		else if (!strcmp(o, "-wp")) scpy(G.web_proto, sizeof G.web_proto, !strcmp(v, "https") ? "https" : "http");
		else if (!strcmp(o, "-sp")) scpy(G.policy, sizeof G.policy, v);
		else if (!strcmp(o, "-hwn") || !strcmp(o, "-vnn") || !strcmp(o, "-loc") || !strcmp(o, "-dn") || !strcmp(o, "-mod")) {
			set_str(o, v, G.hw, sizeof G.hw, "-hwn"); set_str(o, v, G.vendor, sizeof G.vendor, "-vnn");
			set_str(o, v, G.loc, sizeof G.loc, "-loc"); set_str(o, v, G.dname, sizeof G.dname, "-dn");
			set_str(o, v, G.model, sizeof G.model, "-mod");
		} else if (!strncmp(o, "-rp", 3) || !strncmp(o, "-vw", 3) || !strncmp(o, "-vh", 3) || !strncmp(o, "-fps", 4) || !strncmp(o, "-en", 3) || !strncmp(o, "-vc", 3)) {
			size_t ol_ = strlen(o);

			slot = o[ol_ - 1] == '2' ? 1 : 0;
			s = &ex[slot];
			if (!strncmp(o, "-rp", 3)) { scpy(s->rp, sizeof s->rp, v); if (!s->name[0]) scpy(s->name, sizeof s->name, slot ? "SubStream" : "MainStream"); if (slot + 1 > G.nex) G.nex = slot + 1; }
			else if (!strncmp(o, "-vw", 3)) s->w = num_at(v, 0);
			else if (!strncmp(o, "-vh", 3)) s->h = num_at(v, 0);
			else if (!strncmp(o, "-vcb", 4)) s->kbps = num_at(v, 1000);
			else if (!strncmp(o, "-vc", 3)) s->codec = !strcmp(v, "H265") ? 2 : 0;
			else if (!strncmp(o, "-fps", 4)) s->fps = num_at(v, 15);
			else if (!strncmp(o, "-en", 3) && num_at(v, 0) == 0) { s->rp[0] = 0; }
		}
		/* anything else (monvifd options this program does not need): ignored */
	}
	if (G.nex && ex[0].rp[0] && ex[0].w && ex[0].h) {
		G.explicit_streams = 1;
		if (G.nex > 1 && !(ex[1].rp[0] && ex[1].w && ex[1].h)) G.nex = 1;
		for (i = 0; i < G.nex; i++) {
			if (ex[i].fps < 1) ex[i].fps = 15;
			if (ex[i].kbps < 1) ex[i].kbps = 1000;
			ex[i].gop = 30;
		}
	}
	/* hardware address: identity of the device */
	scpy(G.mac, sizeof G.mac, "00:00:00:00:00:00");
	if (!p_mac) {
		snprintf(buf, sizeof buf, "/sys/class/net/%s/address", p_iface);
		p_mac = strdup(env_or("ONVIFD_MAC_FILE", buf));
	}
	if (slurp(p_mac, buf, 40) >= 17) { buf[17] = 0; scpy(G.mac, sizeof G.mac, buf); }
	device_uuid();
	g_instance = (unsigned)time(NULL);
	load_config();
	motion_poll();
	parse_allow(getenv("TC100_NET_ALLOW"));

	signal(SIGTERM, on_term);
	signal(SIGINT, on_term);
	signal(SIGHUP, on_hup);
	signal(SIGPIPE, SIG_IGN);
	for (i = 0; i < MAXCONN; i++) cn[i].fd = -1;

	g_lfd = socket(AF_INET, SOCK_STREAM, 0);
	if (g_lfd < 0) return 1;
	setsockopt(g_lfd, SOL_SOCKET, SO_REUSEADDR, &on, sizeof on);
	memset(&a, 0, sizeof a);
	a.sin_family = AF_INET;
	a.sin_port = htons((uint16_t)G.port);
	if (bind(g_lfd, (struct sockaddr *)&a, sizeof a) || listen(g_lfd, 8)) {
		dprintf(2, "tc100-onvifd: cannot listen on port %d\n", G.port);
		return 1;
	}
	fcntl(g_lfd, F_SETFL, fcntl(g_lfd, F_GETFL) | O_NONBLOCK);

	g_ufd = socket(AF_INET, SOCK_DGRAM, 0);
	if (g_ufd >= 0) {
		setsockopt(g_ufd, SOL_SOCKET, SO_REUSEADDR, &on, sizeof on);
		memset(&a, 0, sizeof a);
		a.sin_family = AF_INET;
		a.sin_port = htons((uint16_t)g_dport);
		if (bind(g_ufd, (struct sockaddr *)&a, sizeof a)) {
			dprintf(2, "tc100-onvifd: no WS-Discovery (cannot bind UDP %d)\n", g_dport);
			close(g_ufd);
			g_ufd = -1;
		}
	}
	dprintf(2, "tc100-onvifd: ONVIF on port %d, %d stream(s), %s\n", G.port, G.nst, G.pass[0] ? "authentication on" : "no password set: open");

	while (!g_term) {
		fd_set rf;
		int mx = g_lfd, r;
		struct timeval tv = { 0, 500000 };
		long long t;

		if (g_hup) { g_hup = 0; load_config(); }
		FD_ZERO(&rf);
		FD_SET(g_lfd, &rf);
		if (g_ufd >= 0) { FD_SET(g_ufd, &rf); if (g_ufd > mx) mx = g_ufd; }
		for (i = 0; i < MAXCONN; i++) if (cn[i].fd >= 0) { FD_SET(cn[i].fd, &rf); if (cn[i].fd > mx) mx = cn[i].fd; }
		r = select(mx + 1, &rf, NULL, NULL, &tv);
		t = now_ms();
		if (r > 0) {
			if (FD_ISSET(g_lfd, &rf)) conn_accept();
			if (g_ufd >= 0 && FD_ISSET(g_ufd, &rf)) udp_in();
			for (i = 0; i < MAXCONN; i++) if (cn[i].fd >= 0 && FD_ISSET(cn[i].fd, &rf)) conn_read(&cn[i]);
		}
		if (t >= next_motion) { motion_poll(); next_motion = t + 500; }
		subs_sweep(t);
		for (i = 0; i < MAXCONN; i++) {
			struct sub *sb;

			if (cn[i].fd < 0 || !cn[i].pending) continue;
			sb = find_sub(cn[i].subid);
			if (!sb || t >= cn[i].pend_end || sb->reported != g_motion) pull_finish(&cn[i]);
		}
		for (i = 0; i < MAXCONN; i++) if (cn[i].fd >= 0 && t > cn[i].deadline) conn_close(&cn[i]);
		if (g_ufd >= 0 && t >= next_disc) {
			if (!g_joined || !g_hello) discovery_up();
			next_disc = t + 10000;
		}
	}
	if (g_hello) wsd_multicast("Bye");
	return 0;
}
