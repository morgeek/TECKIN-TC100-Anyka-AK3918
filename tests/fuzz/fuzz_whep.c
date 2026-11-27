/* fuzz_whep: the parts of the WebRTC gateway that read what a browser or a LAN host sends and that need no TLS library:
 * src/whep/whep_proto.h, shared by tc100_whep.c and whep_test.c. This harness includes the header only, never
 * tc100_whep.c (which carries Mbed TLS: the DTLS handshake itself, the SRTP keys and the HTTP framing of tc100_whep.c
 * http_handle() are out of its reach, see docs/linux-port/upgrade-3.2/fuzz.md).
 *   MODE_STUN   stun_parse + stun_check_integrity + stun_binding_response  (UDP, before any session exists)
 *   MODE_SDP    sdp_parse_offer + sdp_pick_h264 / sdp_pick_pcma + sdp_answer  (the body of POST /whep)
 *   MODE_HELLO  wh_chello_feed  (the first DTLS datagrams: ClientHello with cookie exchange, fragments)
 *   MODE_MISC   wh_b64 (sprop-parameter-sets), wh_nets_parse (TC100_NET_ALLOW) and wh_nets_ok
 * Input: the datagram, or the SDP text; byte 0 of MODE_SDP / MODE_HELLO is a switch byte. */
#define _GNU_SOURCE
#include <stdint.h>
#include "fz.h"
#include "../../src/whep/whep_proto.h"

#if defined(MODE_STUN)
int LLVMFuzzerTestOneInput(const uint8_t *d, size_t n)
{
	static struct hmac_sha1 key;
	static int init;
	struct stun_msg m;
	uint8_t out[512];
	uint8_t *b = (uint8_t *)fz_dup(d, n);

	if (!init) { hmac_sha1_key(&key, (const uint8_t *)"VOkJxbRl1RmTxUk/WvJxBt", 22); init = 1; }
	if (stun_parse(b, n, &m) == 0) {
		(void)stun_check_integrity(b, &m, &key);
		if (m.tid) {
			size_t r = stun_binding_response(out, m.tid, 0x7f000001u, 5004, &key);

			if (r > sizeof out) abort();
		}
	}
	free(b);
	return 0;
}
#elif defined(MODE_SDP)
/* as whep_post() in tc100_whep.c: parse the offer, pick the H.264 and PCMA sections, build the answer */
int LLVMFuzzerTestOneInput(const uint8_t *d, size_t n)
{
	struct sdp_offer of;
	struct sdp_answer_in ai;
	int sw, i, vm = -1, am = -1, vi, aidx;
	char *t, *ans;

	FZ_SPLIT(d, n, sw);
	if (n > 12000) return 0;	/* WH_MAX_OFFER of tc100_whep.c */
	t = fz_dup(d, n);
	if (sdp_parse_offer(t, &of) == 0) {
		for (i = 0; i < of.nm; i++) {
			if (vm < 0 && !strcmp(of.m[i].kind, "video") && sdp_pick_h264(&of.m[i], NULL) >= 0) vm = i;
			if (am < 0 && !strcmp(of.m[i].kind, "audio") && sdp_pick_pcma(&of.m[i]) >= 0) am = i;
		}
		if (vm >= 0) {
			vi = sdp_pick_h264(&of.m[vm], sw & 1 ? "42e0" : "640028");
			aidx = sw & 2 && am >= 0 ? sdp_pick_pcma(&of.m[am]) : -1;
			memset(&ai, 0, sizeof ai);
			ai.offer = &of; ai.ufrag = "abcdefgh"; ai.pwd = "abcdefghijklmnopqrstuvwx";
			ai.fp = "AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99";
			ai.ip = "192.168.1.11"; ai.port = 8554; ai.v_media = vm; ai.v_idx = vi;
			ai.a_media = aidx >= 0 ? am : -1; ai.a_idx = aidx; ai.v_ssrc = 1; ai.a_ssrc = 2; ai.sess_id = 3;
			ans = malloc(3000);	/* the size of whep_post()'s buffer, exact: an overflow is a report */
			if (sdp_answer(ans, 3000, &ai) > 3000) abort();
			free(ans);
		}
	}
	free(t);
	return 0;
}
#elif defined(MODE_HELLO)
int LLVMFuzzerTestOneInput(const uint8_t *d, size_t n)
{
	struct wh_chello c;
	uint8_t out[512];
	size_t off = 0;

	memset(&c, 0, sizeof c);
	/* the input cut in datagrams of 1..64 + len bytes: the cut points come from the data itself */
	while (off < n) {
		size_t l = (size_t)d[off] % 200 + 1;

		off++;
		if (l > n - off) l = n - off;
		{
			uint8_t *b = malloc(l ? l : 1);

			memcpy(b, d + off, l);
			(void)wh_chello_feed(&c, b, l, out, sizeof out);
			free(b);
		}
		off += l;
	}
	return 0;
}
#else
int LLVMFuzzerTestOneInput(const uint8_t *d, size_t n)
{
	uint8_t out[256];
	struct wh_nets w;
	char *t;

	if (n > 4096) return 0;
	t = fz_dup(d, n);
	(void)wh_b64(t, n, out, sizeof out);
	memset(&w, 0, sizeof w);
	wh_nets_parse(&w, t);
	(void)wh_nets_ok(&w, 0xc0a80101u);
	(void)wh_nets_ok(&w, 0x7f000001u);
	free(t);
	return 0;
}
#endif
