/* fuzz_mdns: the mDNS query parser of tc100-mdnsd (src/mdnsd/mdns_pkt.h, the packet part the daemon and test_mdns.c share):
 * mdns_answer (the A record), mdns_sd_answer_lazy (DNS-SD: PTR / SRV / TXT / A), and the rate limiter fed by the
 * packet's source. Entry points as in mdnsd.c run(): a datagram of at most 1500 bytes (the daemon's receive buffer)
 * from any source, whatever its content.
 * Input: byte 0 = switches (bit 0: legacy unicast source port, bits 1-2: services on), the rest = the datagram. */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "fz.h"
#include "../../src/mdnsd/mdns_pkt.h"

static void txt_fn(char *t, int max) { snprintf(t, (size_t)max, "model=TC100\nfw=3.2\nload=0.52\nrssi=-48"); }

int LLVMFuzzerTestOneInput(const uint8_t *d, size_t n)
{
	static struct mdns_ip_rl rl;
	static const char *const hosts[] = { "ipcam1", "tc100-0a1b2c", "a", "ipcam1.local" };
	unsigned char ip[4] = { 192, 168, 1, 11 }, out[1500], *o2;
	char txt[160];
	int sw, r, legacy, svcs;

	FZ_SPLIT(d, n, sw);
	if (n > 1500) return 0;
	legacy = sw & 1;
	svcs = sw >> 1 & 3;
	{
		unsigned char *q = (unsigned char *)fz_dup(d, n);	/* exact size: an over-read is a report */

		r = mdns_answer(q, (int)n, hosts[sw >> 3 & 3], ip, legacy, out, sizeof out);
		if (r < 0 || r > (int)sizeof out) abort();
		o2 = malloc(512);	/* a small output block: an overflow of the answer is a report */
		r = mdns_answer(q, (int)n, hosts[sw >> 3 & 3], ip, legacy, o2, 512);
		if (r < 0 || r > 512) abort();
		r = mdns_sd_answer_lazy(q, (int)n, hosts[sw >> 3 & 3], ip, legacy, svcs, sw & 0x80 ? txt_fn : 0, txt, sizeof txt, o2, 512);
		if (r < 0 || r > 512) abort();
		r = mdns_sd_answer_lazy(q, (int)n, hosts[sw >> 3 & 3], ip, legacy, svcs, txt_fn, txt, sizeof txt, out, sizeof out);
		if (r < 0 || r > (int)sizeof out) abort();
		/* the limiter, as run() calls it: the source address and second come from the input too */
		if (n >= 6) {
			unsigned src = (unsigned)q[2] << 24 | (unsigned)q[3] << 16 | (unsigned)q[4] << 8 | q[5];
			long now = (long)q[0] * 3 + q[1] % 3;

			if (!mdns_ip_rl_full(&rl, src, now)) mdns_ip_rl_take(&rl, src, now);
		}
		free(o2);
		free(q);
	}
	return 0;
}
