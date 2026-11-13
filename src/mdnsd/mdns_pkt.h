/* mdns_pkt.h: the packet part of tc100-mdnsd (no C library, no system calls), shared with the host test.
 *
 * mdns_answer() reads one mDNS query and, when it asks for the A record (or ANY) of "<host>.local", writes the
 * answer: one A record, TTL 120, cache-flush bit set. Nothing else is ever answered (no services, no reverse
 * lookups, no version or key in any record). A query from a port other than 5353 is a "legacy unicast" query
 * (RFC 6762 6.7): the answer then repeats the query id and the question and goes back to the sender only.
 *
 *   int mdns_answer(q, qn, host, ip, legacy, out, outmax)
 *     q, qn    the received packet
 *     host     the host name (no ".local"), compared without case
 *     ip       the IPv4 address in network byte order, as 4 bytes
 *     legacy   1 when the query came from a source port other than 5353
 *     returns  the length of the answer written to out, or 0 (nothing to answer)
 */
#ifndef MDNS_PKT_H
#define MDNS_PKT_H

#define MDNS_TTL 120
#define MDNS_LTTL(legacy, ttl) ((legacy) ? 10 : (ttl))	/* legacy unicast answers: short TTL (RFC 6762 6.7) */

static int mdns_lc(int c) { return c >= 'A' && c <= 'Z' ? c + 32 : c; }

/* the name at q[*p] as lower-case dotted text in out (compression pointers followed: at most 8 jumps, each to an earlier
 * place of the packet, never to itself; the name stays under 255 characters);
 * *p moves past the name as it is in the packet; returns the length, -1 on a broken name */
static int mdns_get_name(const unsigned char *q, int qn, int *p, char *out, int max)
{
	int i = *p, n = 0, jumps = 0, after = -1;

	for (;;) {
		int l;

		if (i >= qn) return -1;
		l = q[i];
		if ((l & 0xc0) == 0xc0) {
			int t;

			if (i + 1 >= qn || ++jumps > 8) return -1;
			t = (l & 0x3f) << 8 | q[i + 1];
			if (t >= i) return -1;			/* forward or onto itself: loop or garbage */
			if (after < 0) after = i + 2;
			i = t;
			continue;
		}
		if (l & 0xc0) return -1;
		i++;
		if (l == 0) break;
		if (i + l > qn || n + l + 2 > max) return -1;
		if (n) out[n++] = '.';
		for (int k = 0; k < l; k++) out[n++] = (char)mdns_lc(q[i + k]);
		i += l;
	}
	out[n] = 0;
	*p = after >= 0 ? after : i;
	return n;
}

static int mdns_eq(const char *a, const char *b) { while (*a && *a == *b) { a++; b++; } return *a == *b; }

/* the name at q[*p] (compression followed) equals host + ".local", compared without case? *p moves past it.
 * 1 yes, 0 another name, -1 a broken name */
static int mdns_name_is(const unsigned char *q, int qn, int *p, const char *host)
{
	char name[256];
	int n = mdns_get_name(q, qn, p, name, sizeof name), k = 0;
	static const char local[] = ".local";

	if (n < 0) return -1;
	while (host[k] && name[k] && mdns_lc((unsigned char)host[k]) == name[k]) k++;
	if (host[k]) return 0;
	for (int j = 0; j < 7; j++, k++) if (name[k] != local[j]) return 0;	/* the NUL too */
	return 1;
}

static int mdns_put_name(unsigned char *o, int n, int max, const char *host)
{
	int l = 0;

	while (host[l]) l++;
	if (l < 1 || l > 63 || n + l + 8 > max) return -1;
	o[n++] = (unsigned char)l;
	for (int k = 0; k < l; k++) o[n++] = (unsigned char)host[k];
	o[n++] = 5; o[n++] = 'l'; o[n++] = 'o'; o[n++] = 'c'; o[n++] = 'a'; o[n++] = 'l'; o[n++] = 0;
	return n;
}

static int mdns_answer(const unsigned char *q, int qn, const char *host, const unsigned char *ip, int legacy,
		       unsigned char *out, int outmax)
{
	int qd, p = 12, want = 0, n;

	if (qn < 12 || !host || !host[0]) return 0;
	if (q[2] & 0x80) return 0;			/* a response, not a query */
	if (q[2] & 0x78) return 0;			/* opcode other than standard query */
	qd = q[4] << 8 | q[5];
	if (qd < 1 || qd > 16) return 0;
	if (!(ip[0] | ip[1] | ip[2] | ip[3])) return 0;	/* no address yet: say nothing */
	for (int i = 0; i < qd; i++) {
		int r = mdns_name_is(q, qn, &p, host), type, cls;

		if (r < 0 || p + 4 > qn) return 0;
		type = q[p] << 8 | q[p + 1]; cls = (q[p + 2] << 8 | q[p + 3]) & 0x7fff;
		p += 4;
		if (r == 1 && cls == 1 && (type == 1 || type == 255)) want = 1;
	}
	if (!want) return 0;
	if (outmax < 64) return 0;
	out[0] = legacy ? q[0] : 0; out[1] = legacy ? q[1] : 0;
	out[2] = 0x84; out[3] = 0;			/* response, authoritative */
	out[4] = 0; out[5] = legacy ? 1 : 0;		/* the question is repeated for a legacy query only */
	out[6] = 0; out[7] = 1;				/* one answer */
	out[8] = out[9] = out[10] = out[11] = 0;
	n = 12;
	if (legacy) {
		if ((n = mdns_put_name(out, n, outmax, host)) < 0) return 0;
		out[n++] = 0; out[n++] = 1; out[n++] = 0; out[n++] = 1;
	}
	if ((n = mdns_put_name(out, n, outmax, host)) < 0 || n + 14 > outmax) return 0;
	out[n++] = 0; out[n++] = 1;			/* type A */
	out[n++] = legacy ? 0 : 0x80; out[n++] = 1;	/* class IN, cache flush (not for legacy) */
	out[n++] = 0; out[n++] = 0; out[n++] = 0; out[n++] = legacy ? 10 : MDNS_TTL;
	out[n++] = 0; out[n++] = 4;
	out[n++] = ip[0]; out[n++] = ip[1]; out[n++] = ip[2]; out[n++] = ip[3];
	return n;
}


/* ---- DNS-SD (item 38 of the implementer list; off unless tc100-mdnsd runs with -s, boot.conf MDNS_SERVICES=1) ----
 * mdns_sd_answer() answers the service browse of VLC, Home Assistant (zeroconf), a browser or `avahi-browse`:
 *   PTR _services._dns-sd._udp.local  -> _http._tcp.local, _rtsp._tcp.local
 *   PTR _http._tcp.local / _rtsp._tcp.local -> <host>._http._tcp.local / <host>._rtsp._tcp.local, with the SRV, TXT
 *       and A records as additional answers (one packet: the browser needs no second question)
 *   SRV / TXT / ANY <host>._http._tcp.local (or _rtsp)
 * SRV: port 80 / 554, target <host>.local. TXT: "path=/" or "path=/video0_unicast", then the strings of txt (may be
 * empty; -v / MDNS_INFO=1 puts the firmware version, the load and the Wi-Fi level there). Names in questions may
 * use compression pointers (Apple's multi-question queries do). Answers are not compressed (a few hundred bytes). */
#define MDNS_SD_HTTP 1
#define MDNS_SD_RTSP 2

/* dotted name -> labels */
static int mdns_put_dotted(unsigned char *o, int n, int max, const char *name)
{
	while (*name) {
		int l = 0;

		while (name[l] && name[l] != '.') l++;
		if (l < 1 || l > 63 || n + l + 2 > max) return -1;
		o[n++] = (unsigned char)l;
		for (int k = 0; k < l; k++) o[n++] = (unsigned char)name[k];
		name += l;
		if (*name == '.') name++;
	}
	if (n + 1 > max) return -1;
	o[n++] = 0;
	return n;
}

/* "<host>." + svc ("_http._tcp.local") into b */
static void mdns_inst(char *b, int max, const char *host, const char *svc)
{
	int n = 0;

	while (*host && n < max - 1) b[n++] = *host++;
	if (n < max - 1) b[n++] = '.';
	while (*svc && n < max - 1) b[n++] = *svc++;
	b[n] = 0;
}

/* one record header: name, type, class (cache flush when unique), TTL; returns the offset of RDLENGTH or -1 */
static int mdns_rr(unsigned char *o, int *n, int max, const char *name, int type, int unique, int ttl)
{
	if ((*n = mdns_put_dotted(o, *n, max, name)) < 0 || *n + 10 > max) return -1;
	o[(*n)++] = (unsigned char)(type >> 8); o[(*n)++] = (unsigned char)type;
	o[(*n)++] = unique ? 0x80 : 0; o[(*n)++] = 1;
	o[(*n)++] = (unsigned char)(ttl >> 24); o[(*n)++] = (unsigned char)(ttl >> 16);
	o[(*n)++] = (unsigned char)(ttl >> 8); o[(*n)++] = (unsigned char)ttl;
	*n += 2;
	return *n - 2;
}

static void mdns_rdlen(unsigned char *o, int at, int end) { o[at] = (unsigned char)((end - at - 2) >> 8); o[at + 1] = (unsigned char)(end - at - 2); }

static int mdns_txt(unsigned char *o, int n, int max, const char *s)
{
	int l = 0;

	while (s[l]) l++;
	if (l > 255 || n + l + 1 > max) return -1;
	o[n++] = (unsigned char)l;
	for (int k = 0; k < l; k++) o[n++] = (unsigned char)s[k];
	return n;
}

/* the SRV + TXT records of one service instance; returns the new length or -1 */
static int mdns_sd_inst(unsigned char *o, int n, int max, const char *host, int svc, const char *txt, int legacy)
{
	char inst[128], target[80];
	const char *type = svc == MDNS_SD_HTTP ? "_http._tcp.local" : "_rtsp._tcp.local";
	int port = svc == MDNS_SD_HTTP ? 80 : 554, at;

	mdns_inst(inst, sizeof inst, host, type);
	mdns_inst(target, sizeof target, host, "local");
	if ((at = mdns_rr(o, &n, max, inst, 33, !legacy, MDNS_LTTL(legacy, MDNS_TTL))) < 0 || n + 6 > max) return -1;
	o[n++] = 0; o[n++] = 0; o[n++] = 0; o[n++] = 0;			/* priority, weight */
	o[n++] = (unsigned char)(port >> 8); o[n++] = (unsigned char)port;
	if ((n = mdns_put_dotted(o, n, max, target)) < 0) return -1;
	mdns_rdlen(o, at, n);
	if ((at = mdns_rr(o, &n, max, inst, 16, !legacy, MDNS_LTTL(legacy, MDNS_TTL))) < 0) return -1;
	if ((n = mdns_txt(o, n, max, svc == MDNS_SD_HTTP ? "path=/" : "path=/video0_unicast")) < 0) return -1;
	while (txt && *txt) {		/* txt: strings separated by '\n' */
		char one[256];
		int l = 0;

		while (txt[l] && txt[l] != '\n' && l < 255) { one[l] = txt[l]; l++; }
		one[l] = 0;
		if (l && (n = mdns_txt(o, n, max, one)) < 0) return -1;
		txt += l;
		if (*txt == '\n') txt++;
	}
	mdns_rdlen(o, at, n);
	return n;
}

static int mdns_sd_answer(const unsigned char *q, int qn, const char *host, const unsigned char *ip, int legacy,
			  int svcs, const char *txt, unsigned char *out, int outmax)
{
	int qd, p = 12, n = 12, an = 0, want_ptr_svc = 0, want_ptr[3] = { 0, 0, 0 }, want_inst[3] = { 0, 0, 0 }, add_a = 0;
	char name[256], inst[128];

	if (qn < 12 || !host || !host[0] || !svcs) return 0;
	if (q[2] & 0x80) return 0;
	if (q[2] & 0x78) return 0;
	qd = q[4] << 8 | q[5];
	if (qd < 1 || qd > 16) return 0;
	if (!(ip[0] | ip[1] | ip[2] | ip[3])) return 0;
	for (int i = 0; i < qd; i++) {
		int type, cls;

		if (mdns_get_name(q, qn, &p, name, sizeof name) < 0 || p + 4 > qn) return 0;
		type = q[p] << 8 | q[p + 1]; cls = (q[p + 2] << 8 | q[p + 3]) & 0x7fff;
		p += 4;
		if (cls != 1 && cls != 255) continue;
		for (int s = 1; s <= 2; s++) {
			const char *t = s == MDNS_SD_HTTP ? "_http._tcp.local" : "_rtsp._tcp.local";

			if (!(svcs & s)) continue;
			if ((type == 12 || type == 255) && mdns_eq(name, t)) want_ptr[s] = 1;
			mdns_inst(inst, sizeof inst, host, t);
			{	/* the host part of the instance compared without case */
				char lc[128];
				int k;

				for (k = 0; inst[k] && k < 127; k++) lc[k] = (char)mdns_lc((unsigned char)inst[k]);
				lc[k] = 0;
				if ((type == 33 || type == 16 || type == 255) && mdns_eq(name, lc)) want_inst[s] = 1;
			}
		}
		if ((type == 12 || type == 255) && mdns_eq(name, "_services._dns-sd._udp.local")) want_ptr_svc = 1;
	}
	if (!want_ptr_svc && !want_ptr[1] && !want_ptr[2] && !want_inst[1] && !want_inst[2]) return 0;
	out[0] = legacy ? q[0] : 0; out[1] = legacy ? q[1] : 0;
	out[2] = 0x84; out[3] = 0;
	for (int k = 4; k < 12; k++) out[k] = 0;
	if (legacy) {	/* RFC 6762 6.7: the question section is repeated, byte for byte (compression pointers stay valid at the same offsets) */
		if (p - 12 > outmax - 12) return 0;
		out[4] = q[4]; out[5] = q[5];
		for (int k = 12; k < p; k++) out[k] = q[k];
		n = p;
	}
	if (want_ptr_svc)
		for (int s = 1; s <= 2; s++) {
			int at;

			if (!(svcs & s)) continue;
			if ((at = mdns_rr(out, &n, outmax, "_services._dns-sd._udp.local", 12, 0, MDNS_LTTL(legacy, 4500))) < 0) return 0;
			if ((n = mdns_put_dotted(out, n, outmax, s == MDNS_SD_HTTP ? "_http._tcp.local" : "_rtsp._tcp.local")) < 0) return 0;
			mdns_rdlen(out, at, n); an++;
		}
	for (int s = 1; s <= 2; s++) {
		const char *t = s == MDNS_SD_HTTP ? "_http._tcp.local" : "_rtsp._tcp.local";

		if (want_ptr[s]) {
			int at;

			mdns_inst(inst, sizeof inst, host, t);
			if ((at = mdns_rr(out, &n, outmax, t, 12, 0, MDNS_LTTL(legacy, 4500))) < 0) return 0;
			if ((n = mdns_put_dotted(out, n, outmax, inst)) < 0) return 0;
			mdns_rdlen(out, at, n); an++;
			want_inst[s] = 1;		/* SRV + TXT along with the PTR */
		}
		if (want_inst[s]) {
			if ((n = mdns_sd_inst(out, n, outmax, host, s, txt, legacy)) < 0) return 0;
			an += 2; add_a = 1;
		}
	}
	if (add_a) {	/* the address of the target, so the client needs nothing more */
		char target[80];
		int at;

		mdns_inst(target, sizeof target, host, "local");
		if ((at = mdns_rr(out, &n, outmax, target, 1, !legacy, MDNS_LTTL(legacy, MDNS_TTL))) < 0 || n + 4 > outmax) return 0;
		out[n++] = ip[0]; out[n++] = ip[1]; out[n++] = ip[2]; out[n++] = ip[3];
		mdns_rdlen(out, at, n); an++;
	}
	out[6] = (unsigned char)(an >> 8); out[7] = (unsigned char)an;
	return an ? n : 0;
}

/* ---- answer rate limit (the daemon would otherwise reflect a flood of queries at full rate) ----
 * at most MDNS_RATE answers per second, counted per whole second of a monotonic clock; the caller peeks with
 * mdns_rl_full() before any costly work and takes a token with mdns_rl_take() when it sends */
#define MDNS_RATE 20
struct mdns_rl { long sec; int cnt; };

static int mdns_rl_full(struct mdns_rl *r, long now)
{
	if (now != r->sec) { r->sec = now; r->cnt = 0; }
	return r->cnt >= MDNS_RATE;
}

static int mdns_rl_take(struct mdns_rl *r, long now)
{
	if (mdns_rl_full(r, now)) return 0;
	r->cnt++;
	return 1;
}

#endif
