/* Host test of mdns_pkt.h (tests/test_regressions.py builds and runs it): cc -o test_mdns test_mdns.c && ./test_mdns */
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

	if (!fails) printf("mdns: ok\n");
	return fails != 0;
}
