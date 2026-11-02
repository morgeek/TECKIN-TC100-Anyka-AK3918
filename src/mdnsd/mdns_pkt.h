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

static int mdns_lc(int c) { return c >= 'A' && c <= 'Z' ? c + 32 : c; }

/* the name at q[*p] (labels only: a compressed name is not ours) equals host + ".local"? *p moves past it */
static int mdns_name_is(const unsigned char *q, int qn, int *p, const char *host)
{
	int i = *p, l, k, ok = 1, part = 0;
	static const char local[] = "local";

	for (;;) {
		if (i >= qn) return -1;
		l = q[i++];
		if (l == 0) break;
		if (l & 0xc0) return -1;			/* compression pointer in a question: not handled, not ours */
		if (i + l > qn) return -1;
		if (part == 0) {				/* first label: the host name */
			for (k = 0; k < l; k++) if (!host[k] || mdns_lc(q[i + k]) != mdns_lc((unsigned char)host[k])) ok = 0;
			if (host[l]) ok = 0;
		} else if (part == 1) {				/* second label: "local" */
			if (l != 5) ok = 0;
			else for (k = 0; k < 5; k++) if (mdns_lc(q[i + k]) != local[k]) ok = 0;
		} else ok = 0;
		i += l; part++;
	}
	*p = i;
	return ok && part == 2;
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

#endif
