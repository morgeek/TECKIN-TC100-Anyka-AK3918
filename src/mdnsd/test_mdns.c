/* Host test of mdns_pkt.h (tests/test_regressions.py builds and runs it): cc -o test_mdns test_mdns.c && ./test_mdns */
#define _GNU_SOURCE
#include <stdio.h>
#include <string.h>
#include "mdns_pkt.h"

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)

static int query(unsigned char *q, const char *name, int type, int id)
{
	int n = 12, l;
	const char *p = name;

	memset(q, 0, 12);
	q[0] = (unsigned char)(id >> 8); q[1] = (unsigned char)id; q[5] = 1;
	while (*p) {
		const char *d = strchr(p, '.');

		l = d ? (int)(d - p) : (int)strlen(p);
		q[n++] = (unsigned char)l; memcpy(q + n, p, (size_t)l); n += l;
		p += l; if (*p == '.') p++;
	}
	q[n++] = 0;
	q[n++] = 0; q[n++] = (unsigned char)type; q[n++] = 0; q[n++] = 1;
	return n;
}

/* qd questions: the first the plain name (AAAA), question k a pointer to question k-1's name (A): k jumps to the name */
static int chain(unsigned char *q, int qd)
{
	int n = query(q, "ipcam1.local", 28, 0), prev = 12;

	q[5] = (unsigned char)qd;
	for (int k = 1; k < qd; k++) {
		int at = n;

		q[n++] = 0xc0; q[n++] = (unsigned char)prev;
		q[n++] = 0; q[n++] = 1; q[n++] = 0; q[n++] = 1;
		prev = at;
	}
	return n;
}

int main(void)
{
	unsigned char q[512], o[256], ip[4] = { 192, 168, 1, 11 }, noip[4] = { 0, 0, 0, 0 };
	int n, r;

	/* A query for our name, any case: one A record with our address, cache flush, id 0 */
	n = query(q, "IPCam1.LOCAL", 1, 0x1234);
	r = mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o);
	CHECK(r == 12 + 14 + 14);
	CHECK(o[0] == 0 && o[1] == 0 && o[2] == 0x84 && o[5] == 0 && o[7] == 1);
	CHECK(o[12] == 6 && !memcmp(o + 13, "ipcam1", 6) && o[19] == 5 && !memcmp(o + 20, "local", 5) && o[25] == 0);
	CHECK(o[26] == 0 && o[27] == 1 && o[28] == 0x80 && o[29] == 1);
	CHECK(o[33] == MDNS_TTL && o[35] == 4 && !memcmp(o + 36, ip, 4));

	/* ANY is answered too; AAAA, PTR and other names are not */
	n = query(q, "ipcam1.local", 255, 0); CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) > 0);
	n = query(q, "ipcam1.local", 28, 0); CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 0);
	n = query(q, "ipcam2.local", 1, 0); CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 0);
	n = query(q, "ipcam.local", 1, 0); CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 0);
	n = query(q, "ipcam10.local", 1, 0); CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 0);
	n = query(q, "ipcam1.lan", 1, 0); CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 0);
	n = query(q, "ipcam1.local.x", 1, 0); CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 0);
	n = query(q, "_http._tcp.local", 12, 0); CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 0);

	/* legacy unicast (source port not 5353): id and question repeated, no cache flush, short TTL */
	n = query(q, "ipcam1.local", 1, 0xbeef);
	r = mdns_answer(q, n, "ipcam1", ip, 1, o, sizeof o);
	CHECK(r == 12 + 18 + 28);
	CHECK(o[0] == 0xbe && o[1] == 0xef && o[5] == 1 && o[7] == 1);
	CHECK(o[r - 12] == 0 && o[r - 10] == 0 && o[r - 7] == 10 && !memcmp(o + r - 4, ip, 4));

	/* compressed names in questions (MDNS-01): "A host.local" + "AAAA host.local" written as a pointer to the first */
	n = query(q, "ipcam1.local", 1, 0);
	q[5] = 2; q[n++] = 0xc0; q[n++] = 12; q[n++] = 0; q[n++] = 28; q[n++] = 0; q[n++] = 1;
	CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 12 + 14 + 14);
	n = query(q, "ipcam1.local", 28, 0);					/* AAAA first, then A as a pointer */
	q[5] = 2; q[n++] = 0xc0; q[n++] = 12; q[n++] = 0; q[n++] = 1; q[n++] = 0; q[n++] = 1;
	CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 12 + 14 + 14);
	n = query(q, "ipcam1.local", 28, 0);					/* pointer to our name but only AAAA: no answer */
	q[5] = 2; q[n++] = 0xc0; q[n++] = 12; q[n++] = 0; q[n++] = 28; q[n++] = 0; q[n++] = 1;
	CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 0);
	n = query(q, "ipcam1.local", 1, 0);					/* "ipcam1" + pointer to "local" of the first question */
	q[5] = 2; q[n++] = 6; memcpy(q + n, "ipcam1", 6); n += 6; q[n++] = 0xc0; q[n++] = 12 + 7;
	q[n++] = 0; q[n++] = 1; q[n++] = 0; q[n++] = 1;
	CHECK(mdns_answer(q, n, "IPCAM1", ip, 0, o, sizeof o) == 12 + 14 + 14);
	n = query(q, "other.local", 28, 0);					/* pointer to another host's name: nothing */
	q[5] = 2; q[n++] = 0xc0; q[n++] = 12; q[n++] = 0; q[n++] = 1; q[n++] = 0; q[n++] = 1;
	CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 0);
	/* chains of pointers: 8 jumps are read, the 9th is refused (the whole packet then stays unanswered) */
	n = chain(q, 9); CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) > 0);
	n = chain(q, 10); CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 0);
	/* malformed pointers: onto itself, forward, out of the packet, truncated */
	n = query(q, "ipcam1.local", 1, 0);
	q[5] = 2; q[n] = 0xc0; q[n + 1] = (unsigned char)n; q[n + 2] = 0; q[n + 3] = 1; q[n + 4] = 0; q[n + 5] = 1;
	CHECK(mdns_answer(q, n + 6, "ipcam1", ip, 0, o, sizeof o) == 0);	/* itself */
	q[n + 1] = (unsigned char)(n + 4);
	CHECK(mdns_answer(q, n + 6, "ipcam1", ip, 0, o, sizeof o) == 0);	/* forward, into the question tail */
	q[n] = 0xc0 | 0x3f; q[n + 1] = 0xff;
	CHECK(mdns_answer(q, n + 6, "ipcam1", ip, 0, o, sizeof o) == 0);	/* outside */
	q[n] = 0xc0;
	CHECK(mdns_answer(q, n + 1, "ipcam1", ip, 0, o, sizeof o) == 0);	/* cut inside the pointer */
	n = query(q, "ipcam1.local", 1, 0); q[12] = 0xc0; q[13] = 12;		/* the first name points at itself */
	CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 0);
	{	/* a name over 254 characters: five labels of 63 */
		int m = 12;

		memset(q, 0, 12); q[5] = 1;
		for (int k = 0; k < 5; k++) { q[m++] = 63; memset(q + m, 'a', 63); m += 63; }
		q[m++] = 0; q[m++] = 0; q[m++] = 1; q[m++] = 0; q[m++] = 1;
		CHECK(mdns_answer(q, m, "ipcam1", ip, 0, o, sizeof o) == 0);
		CHECK(mdns_sd_answer(q, m, "ipcam1", ip, 0, 3, "", o, sizeof o) == 0);
	}

	/* rate limit: MDNS_RATE tokens a second, a new second starts again, peeking takes nothing */
	{
		struct mdns_rl rl = { -1, 0 };
		int got = 0;

		CHECK(!mdns_rl_full(&rl, 100));
		for (int k = 0; k < 100; k++) got += mdns_rl_take(&rl, 100);
		CHECK(got == MDNS_RATE && mdns_rl_full(&rl, 100) && !mdns_rl_take(&rl, 100));
		CHECK(!mdns_rl_full(&rl, 101) && mdns_rl_take(&rl, 101));
		got = 0; for (int k = 0; k < 100; k++) got += mdns_rl_take(&rl, 101);
		CHECK(got == MDNS_RATE - 1);
	}

	/* responses, other opcodes, no address yet, truncated or garbage packets: nothing */
	n = query(q, "ipcam1.local", 1, 0); q[2] = 0x84; CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 0);
	n = query(q, "ipcam1.local", 1, 0); q[2] = 0x28; CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 0);
	n = query(q, "ipcam1.local", 1, 0); CHECK(mdns_answer(q, n, "ipcam1", noip, 0, o, sizeof o) == 0);
	for (int cut = 0; cut < n; cut++) CHECK(mdns_answer(q, cut, "ipcam1", ip, 0, o, sizeof o) == 0);
	n = query(q, "ipcam1.local", 1, 0); q[12] = 0xc0; CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 0);
	n = query(q, "ipcam1.local", 1, 0); q[12] = 60; CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 0);
	n = query(q, "ipcam1.local", 1, 0); q[5] = 0; CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 0);
	n = query(q, "ipcam1.local", 1, 0); q[5] = 200; CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, sizeof o) == 0);
	n = query(q, "ipcam1.local", 1, 0); CHECK(mdns_answer(q, n, "", ip, 0, o, sizeof o) == 0);
	n = query(q, "ipcam1.local", 1, 0); CHECK(mdns_answer(q, n, "ipcam1", ip, 0, o, 40) == 0);

	/* DNS-SD (item 38): off without services; the browse of _http._tcp gives PTR + SRV + TXT + A */
	{
		unsigned char big[700];
		const int both = MDNS_SD_HTTP | MDNS_SD_RTSP;

		n = query(q, "_http._tcp.local", 12, 0);
		CHECK(mdns_sd_answer(q, n, "ipcam1", ip, 0, 0, "", big, sizeof big) == 0);	/* -s not given */
		r = mdns_sd_answer(q, n, "ipcam1", ip, 0, both, "fw=3.0.1\nload=0.5", big, sizeof big);
		CHECK(r > 0 && big[7] == 4);							/* PTR, SRV, TXT, A */
		CHECK(memmem(big, (size_t)r, "\x06ipcam1\x05_http\x04_tcp\x05local", 24) != NULL);
		CHECK(memmem(big, (size_t)r, "\x00\x00\x00\x00\x00\x50\x06ipcam1\x05local", 19) != NULL);	/* SRV port 80 */
		CHECK(memmem(big, (size_t)r, "\x06path=/\x08" "fw=3.0.1\x08load=0.5", 24) != NULL);
		CHECK(!memcmp(big + r - 4, ip, 4));
		n = query(q, "_rtsp._tcp.local", 12, 0);
		r = mdns_sd_answer(q, n, "ipcam1", ip, 0, both, "", big, sizeof big);
		CHECK(r > 0 && memmem(big, (size_t)r, "\x02\x2a", 2) && memmem(big, (size_t)r, "\x14path=/video0_unicast", 21));
		CHECK(mdns_sd_answer(q, n, "ipcam1", ip, 0, MDNS_SD_HTTP, "", big, sizeof big) == 0);	/* only http asked for */
		n = query(q, "_services._dns-sd._udp.local", 12, 0);
		r = mdns_sd_answer(q, n, "ipcam1", ip, 0, both, "", big, sizeof big);
		CHECK(r > 0 && big[7] == 2);
		n = query(q, "IPCAM1._http._tcp.local", 33, 0);					/* SRV of the instance, any case */
		r = mdns_sd_answer(q, n, "ipcam1", ip, 0, both, "", big, sizeof big);
		CHECK(r > 0 && big[7] == 3);
		n = query(q, "other._http._tcp.local", 33, 0);
		CHECK(mdns_sd_answer(q, n, "ipcam1", ip, 0, both, "", big, sizeof big) == 0);
		/* two questions, the second compressed (pointer to "_tcp.local" of the first) */
		n = query(q, "_http._tcp.local", 12, 0);
		q[5] = 2;
		q[n++] = 5; memcpy(q + n, "_rtsp", 5); n += 5; q[n++] = 0xc0; q[n++] = 12 + 6;	/* -> "_tcp.local" */
		q[n++] = 0; q[n++] = 12; q[n++] = 0; q[n++] = 1;
		r = mdns_sd_answer(q, n, "ipcam1", ip, 0, both, "", big, sizeof big);
		CHECK(r > 0 && big[7] == 7);							/* 2 x (PTR SRV TXT) + A */
		q[n - 6] = 0xc0 | 0x3f; q[n - 5] = 0xff;					/* pointer out of the packet */
		CHECK(mdns_sd_answer(q, n, "ipcam1", ip, 0, both, "", big, sizeof big) == 0);
		for (int cut = 12; cut < n; cut++) mdns_sd_answer(q, cut, "ipcam1", ip, 0, both, "", big, sizeof big);	/* no crash */
		CHECK(mdns_sd_answer(q, n, "ipcam1", noip, 0, both, "", big, sizeof big) == 0);
	}

	/* legacy unicast DNS-SD (MDNS-01): question repeated, no cache-flush bit, TTL <= 10 in every record */
	{
		unsigned char big[1500];
		const int both = MDNS_SD_HTTP | MDNS_SD_RTSP;
		int off, rec, an;

		n = query(q, "_http._tcp.local", 12, 0xcafe);
		r = mdns_sd_answer(q, n, "ipcam1", ip, 1, both, "fw=1", big, sizeof big);
		CHECK(r > 0 && big[0] == 0xca && big[1] == 0xfe && big[4] == 0 && big[5] == 1);
		CHECK(!memcmp(big + 12, q + 12, (size_t)(n - 12)));			/* the question, byte for byte */
		an = big[6] << 8 | big[7];
		CHECK(an == 4);
		off = n;
		for (rec = 0; rec < an; rec++) {		/* walk the records: name, type, class, TTL, rdlength */
			int rd;

			while (big[off]) off += big[off] + 1;
			off++;
			CHECK((big[off + 2] & 0x80) == 0 && big[off + 3] == 1);	/* no cache flush */
			CHECK(big[off + 4] == 0 && big[off + 5] == 0 && big[off + 6] == 0 && big[off + 7] <= 10);
			rd = big[off + 8] << 8 | big[off + 9];
			off += 10 + rd;
		}
		CHECK(off == r);
		/* multicast answers keep the flush bit and the long TTL, and carry no question section */
		r = mdns_sd_answer(q, n, "ipcam1", ip, 0, both, "", big, sizeof big);
		CHECK(r > 0 && big[5] == 0 && big[4] == 0);
		CHECK(memmem(big, (size_t)r, "\x00\x21\x80\x01\x00\x00\x00\x78", 8) != NULL);	/* SRV, flush, TTL 120 */
		/* legacy question longer than the buffer: nothing rather than a cut packet */
		CHECK(mdns_sd_answer(q, n, "ipcam1", ip, 1, both, "", big, 20) == 0);
		n = query(q, "_services._dns-sd._udp.local", 12, 0x0102);
		r = mdns_sd_answer(q, n, "ipcam1", ip, 1, both, "", big, sizeof big);
		CHECK(r > 0 && big[5] == 1 && big[7] == 2 && !memcmp(big + 12, q + 12, (size_t)(n - 12)));
	}

	/* a 63 character host name (the longest the daemon takes) still gets the full DNS-SD answer in 1500 bytes */
	{
		unsigned char big[1500];
		char host[64];
		const int both = MDNS_SD_HTTP | MDNS_SD_RTSP;
		const char *txt = "model=TC100\nfw=3.0.1-rc99\nload=0.52\nrssi=-48";

		memset(host, 'h', 63); host[63] = 0;
		n = query(q, "_http._tcp.local", 12, 0);
		r = mdns_sd_answer(q, n, host, ip, 0, both, txt, big, sizeof big);
		CHECK(r > 0 && r <= 1500 && big[7] == 4 && !memcmp(big + r - 4, ip, 4));
		/* two questions at once (the second compressed): both services, SRV + TXT twice, one A */
		q[5] = 2; q[n++] = 5; memcpy(q + n, "_rtsp", 5); n += 5; q[n++] = 0xc0; q[n++] = 12 + 6;
		q[n++] = 0; q[n++] = 12; q[n++] = 0; q[n++] = 1;
		r = mdns_sd_answer(q, n, host, ip, 0, both, txt, big, sizeof big);
		CHECK(r > 0 && r <= 1500 && big[7] == 7);
		CHECK(mdns_sd_answer(q, n, host, ip, 0, both, txt, big, 700) == 0);	/* the old 700 byte buffer was too small: refused, not cut */
		/* the browse of the service list, legacy, with the question repeated */
		n = query(q, "_services._dns-sd._udp.local", 255, 0);
		q[5] = 2; q[n++] = 0xc0; q[n++] = 12; q[n++] = 0; q[n++] = 12; q[n++] = 0; q[n++] = 1;
		r = mdns_sd_answer(q, n, host, ip, 1, both, txt, big, sizeof big);
		CHECK(r > 0 && r <= 1500);
		/* the A answer for it too, multicast and legacy */
		n = query(q, "hhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhh.local", 1, 0);
		CHECK(mdns_answer(q, n, host, ip, 0, big, sizeof big) > 0);
		CHECK(mdns_answer(q, n, host, ip, 1, big, sizeof big) > 0);
	}

	if (!fails) printf("mdns: ok\n");
	return fails != 0;
}
