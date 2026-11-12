/* whep_test.c: host tests of whep_proto.h (item 35): the STUN test vectors of RFC 5769, the binding response the
 * gateway makes, the SDP offer of a browser and the answer. Prints "whep_test: all ok" and exits 0, else the failing
 * check and 1. Build: gcc -O2 -Wall -Wextra -Werror -Wno-unused-function -o whep_test whep_test.c */
#include "whep_proto.h"

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)

static int hex(const char *h, uint8_t *out)
{
	int n = 0;

	for (; h[0] && h[1]; h += 2) {
		unsigned v;

		if (sscanf(h, "%2x", &v) != 1) return -1;
		out[n++] = (uint8_t)v;
	}
	return n;
}

static const char *CHROME_OFFER =
	"v=0\r\no=- 4611731400430051336 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\na=group:BUNDLE 0 1 2\r\n"
	"a=extmap-allow-mixed\r\na=msid-semantic: WMS\r\n"
	"m=video 9 UDP/TLS/RTP/SAVPF 96 97 102 103 104\r\nc=IN IP4 0.0.0.0\r\na=rtcp:9 IN IP4 0.0.0.0\r\n"
	"a=ice-ufrag:Zk9f\r\na=ice-pwd:0123456789abcdef01234567\r\n"
	"a=fingerprint:sha-256 AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99\r\n"
	"a=setup:actpass\r\na=mid:0\r\na=recvonly\r\na=rtcp-mux\r\n"
	"a=rtpmap:96 VP8/90000\r\na=rtpmap:97 rtx/90000\r\na=fmtp:97 apt=96\r\n"
	"a=rtpmap:102 H264/90000\r\na=fmtp:102 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42001f\r\n"
	"a=rtpmap:103 H264/90000\r\na=fmtp:103 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=4d001f\r\n"
	"a=rtpmap:104 H264/90000\r\na=fmtp:104 level-asymmetry-allowed=1;packetization-mode=0;profile-level-id=4d001f\r\n"
	"m=audio 9 UDP/TLS/RTP/SAVPF 111 63 0 8\r\nc=IN IP4 0.0.0.0\r\na=mid:1\r\na=recvonly\r\na=rtcp-mux\r\n"
	"a=rtpmap:111 opus/48000/2\r\na=rtpmap:63 red/48000/2\r\na=rtpmap:0 PCMU/8000\r\na=rtpmap:8 PCMA/8000\r\n"
	"m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\nc=IN IP4 0.0.0.0\r\na=mid:2\r\na=sctp-port:5000\r\n";

int main(void)
{
	uint8_t b[256], m[256], mac[20];
	struct stun_msg sm;
	struct hmac_sha1 key;
	const char *pw = "VOkJxbRl1RmTxUk/WvJxBt";
	int n;

	hmac_sha1_key(&key, (const uint8_t *)pw, strlen(pw));

	/* RFC 5769 2.1: sample request, short-term credentials (password above), with SOFTWARE, PRIORITY,
	 * ICE-CONTROLLED, USERNAME "evtj:h6vY", MESSAGE-INTEGRITY and FINGERPRINT */
	n = hex("000100582112a442b7e7a701bc34d686fa87dfae802200105354554e20746573742063"
		"6c69656e74002400046e0001ff80290008932ff9b151263b3600060009657674"
		"6a3a68367659202020000800149aeaa70cbfd8cb56781ef2b5b2d3f249c1b571a2"
		"80280004e57a3bcf", b);
	CHECK(n == 108);
	CHECK(stun_parse(b, (size_t)n, &sm) == 0);
	CHECK(sm.type == 1 && sm.user_len == 9 && !memcmp(sm.user, "evtj:h6vY", 9));
	CHECK(stun_check_integrity(b, &sm, &key));
	b[30] ^= 1;				/* a changed attribute: fingerprint and integrity both fail */
	CHECK(stun_parse(b, (size_t)n, &sm) < 0);
	b[30] ^= 1;
	b[n - 1] ^= 1;
	CHECK(stun_parse(b, (size_t)n, &sm) < 0);	/* wrong fingerprint */
	b[n - 1] ^= 1;
	{	/* right fingerprint but another password: integrity fails */
		struct hmac_sha1 bad;

		hmac_sha1_key(&bad, (const uint8_t *)"another", 7);
		CHECK(stun_parse(b, (size_t)n, &sm) == 0 && !stun_check_integrity(b, &sm, &bad));
	}

	/* RFC 5769 2.2: the success response for 192.0.2.1:32853 (SOFTWARE "test vector"), checked by finishing the same
	 * message with our code */
	{
		uint8_t want[128];
		int wn = hex("0101003c2112a442b7e7a701bc34d686fa87dfae8022000b7465737420766563746f7220"
			     "002000080001a147e112a643"
			     "000800142b91f599fd9e90c38c7489f92af9ba53f06be7d7"
			     "80280004c07d4c96", want);

		CHECK(wn == 80);
		memcpy(m, want, 20 + 16 + 12);		/* header, SOFTWARE and XOR-MAPPED-ADDRESS */
		n = (int)stun_finish(m, 20 + 16 + 12, &key);
		CHECK(n == 80 && !memcmp(m, want, 80));
		CHECK(stun_parse(want, 80, &sm) == 0 && stun_check_integrity(want, &sm, &key));
		/* and our own response builder gives a valid message with the same address encoding */
		n = (int)stun_binding_response(m, want + 8, 0xc0000201u, 32853, &key);
		CHECK(n == 20 + 12 + 24 + 8);
		CHECK(stun_parse(m, (size_t)n, &sm) == 0 && sm.type == 0x0101 && stun_check_integrity(m, &sm, &key));
		CHECK(!memcmp(m + 24, want + 20 + 16 + 4, 8));	/* the XOR-MAPPED-ADDRESS value of the RFC */
	}
	(void)mac;

	/* a request that is not STUN, and one with a wrong length */
	{
		uint8_t junk[40];

		memset(junk, 0x16, sizeof junk);
		CHECK(stun_parse(junk, sizeof junk, &sm) < 0);
		hex("000100582112a442b7e7a701bc34d686fa87dfae", junk);
		CHECK(stun_parse(junk, 20, &sm) < 0);
	}

	/* base64 of an SPS and a PPS (sprop-parameter-sets) */
	{
		uint8_t o[32];

		CHECK(wh_b64("Z0IAKeKQFAe2AtwEBAaQeJEV", 24, o, sizeof o) == 18 && o[0] == 0x67 && o[1] == 0x42);
		CHECK(wh_b64("aM4xsg==", 8, o, sizeof o) == 4 && o[0] == 0x68);
		CHECK(wh_b64("a!b", 3, o, sizeof o) < 0);
	}

	/* SDP offer of a browser, then our answer */
	{
		struct sdp_offer of;
		struct sdp_answer_in ai;
		char ans[2048];
		size_t an;
		int vi, au;

		CHECK(sdp_parse_offer(CHROME_OFFER, &of) == 0);
		CHECK(of.nm == 3 && !strcmp(of.ufrag, "Zk9f") && !strcmp(of.pwd, "0123456789abcdef01234567"));
		CHECK(!strncmp(of.fp, "AA:BB:CC", 8));
		CHECK(!strcmp(of.m[0].kind, "video") && !strcmp(of.m[0].mid, "0") && !strcmp(of.m[1].mid, "1"));
		CHECK(!strcmp(of.m[2].kind, "application") && !strncmp(of.m[2].tail, "UDP/DTLS/SCTP", 13));
		vi = sdp_pick_h264(&of.m[0], "4d00");
		CHECK(vi >= 0 && of.m[0].pts[vi].pt == 103);	/* the Main profile, packetization mode 1 (104 is mode 0) */
		vi = sdp_pick_h264(&of.m[0], "6400");
		CHECK(vi >= 0 && of.m[0].pts[vi].pt == 102);	/* no match: the first mode-1 H.264 */
		vi = sdp_pick_h264(&of.m[0], "4d00");
		au = sdp_pick_pcma(&of.m[1]);
		CHECK(au >= 0 && of.m[1].pts[au].pt == 8);
		CHECK(sdp_pick_h264(&of.m[1], NULL) < 0);
		memset(&ai, 0, sizeof ai);
		ai.offer = &of; ai.ufrag = "abcd1234"; ai.pwd = "0123456789012345678901"; ai.fp = "11:22";
		ai.ip = "192.168.1.50"; ai.port = 8189; ai.v_media = 0; ai.v_idx = vi; ai.a_media = 1; ai.a_idx = au;
		ai.v_ssrc = 1111; ai.a_ssrc = 2222; ai.sess_id = 42;
		an = sdp_answer(ans, sizeof ans, &ai);
		CHECK(an > 0 && an == strlen(ans));
		CHECK(strstr(ans, "a=ice-lite\r\n") && strstr(ans, "a=group:BUNDLE 0 1\r\n"));
		CHECK(strstr(ans, "m=video 9 UDP/TLS/RTP/SAVPF 103\r\n") && strstr(ans, "a=rtpmap:103 H264/90000\r\n"));
		CHECK(strstr(ans, "a=fmtp:103 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=4d001f\r\n"));
		CHECK(strstr(ans, "m=audio 9 UDP/TLS/RTP/SAVPF 8\r\n") && strstr(ans, "a=rtpmap:8 PCMA/8000\r\n"));
		CHECK(strstr(ans, "m=application 0 UDP/DTLS/SCTP webrtc-datachannel\r\n"));	/* rejected, same position */
		CHECK(strstr(ans, "a=setup:passive\r\n") && strstr(ans, "a=sendonly\r\n") && strstr(ans, "a=rtcp-mux\r\n"));
		CHECK(strstr(ans, "a=candidate:1 1 udp 2130706431 192.168.1.50 8189 typ host\r\n"));
		CHECK(strstr(ans, "a=ssrc:1111 cname:tc100\r\n") && strstr(ans, "a=ssrc:2222 cname:tc100\r\n"));
		CHECK(strstr(ans, "a=fingerprint:sha-256 11:22\r\n") && strstr(ans, "a=ice-ufrag:abcd1234\r\n"));
		/* video only (no audio wanted) */
		ai.a_media = -1;
		an = sdp_answer(ans, sizeof ans, &ai);
		CHECK(an > 0 && strstr(ans, "a=group:BUNDLE 0\r\n") && strstr(ans, "m=audio 0 UDP/TLS/RTP/SAVPF 111 63 0 8\r\n"));
		CHECK(sdp_answer(ans, 100, &ai) == 0);			/* too small a buffer */
		/* not an offer: no ICE credentials, no fingerprint */
		CHECK(sdp_parse_offer("v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n", &of) < 0);
		CHECK(sdp_parse_offer("", &of) < 0);
	}

	{	/* a ClientHello in three fragments (Chrome's DTLS 1.3 + ML-KEM hello), out of order, with a repeat */
		static struct wh_chello ch;
		uint8_t msg[3000], dg[1600], out[4200];
		unsigned L = 2500, i;
		int r;
		size_t p, dn;
		unsigned offs[] = { 1100, 0, 1100, 2200 }, lens[] = { 1100, 1100, 1100, 300 };

		for (i = 0; i < L; i++) msg[i] = (uint8_t)(i * 7 + 3);
		for (i = 0; i < 4; i++) {
			dn = 0;
			dg[0] = 22; dg[1] = 0xfe; dg[2] = 0xfd; memset(dg + 3, 0, 8); dg[10] = (uint8_t)i;
			wh_put16(dg + 11, 12 + lens[i]);
			p = 13; dg[p] = 1; dg[p + 1] = 0; dg[p + 2] = (uint8_t)(L >> 8); dg[p + 3] = (uint8_t)L; dg[p + 4] = 0; dg[p + 5] = 0;
			dg[p + 6] = 0; dg[p + 7] = (uint8_t)(offs[i] >> 8); dg[p + 8] = (uint8_t)offs[i];
			dg[p + 9] = 0; dg[p + 10] = (uint8_t)(lens[i] >> 8); dg[p + 11] = (uint8_t)lens[i];
			memcpy(dg + p + 12, msg + offs[i], lens[i]);
			dn = p + 12 + lens[i];
			r = wh_chello_feed(&ch, dg, dn, out, sizeof out);
			if (i < 3) CHECK(r == 1);
			else {
				CHECK(r == (int)(25 + L));
				CHECK(out[0] == 22 && wh_be16(out + 11) == 12 + L && out[13] == 1 && wh_be24(out + 14) == L);
				CHECK(wh_be24(out + 19) == 0 && wh_be24(out + 22) == L && !memcmp(out + 25, msg, L));
			}
		}
		/* a ClientHello in one piece and anything else pass through */
		dg[0] = 22; wh_put16(dg + 11, 12 + 50); dg[13] = 1; dg[14] = 0; dg[15] = 0; dg[16] = 50;
		memset(dg + 19, 0, 3); dg[22] = 0; dg[23] = 0; dg[24] = 50;
		CHECK(wh_chello_feed(&ch, dg, 13 + 62, out, sizeof out) == 0);
		dg[0] = 23;
		CHECK(wh_chello_feed(&ch, dg, 13 + 62, out, sizeof out) == 0);
		/* a fragment claiming more than WH_CH_MAX */
		dg[0] = 22; dg[14] = 0; dg[15] = 0x20; dg[16] = 0; dg[24] = 50;
		CHECK(wh_chello_feed(&ch, dg, 13 + 62, out, sizeof out) == -1);
	}

	{	/* NET_LAN_ONLY on the UDP port (review 2026-11-12): the TC100_NET_ALLOW list of common_functions.sh */
		struct wh_nets w;

		wh_nets_parse(&w, "10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10");
		CHECK(w.n == 5);
		CHECK(wh_nets_ok(&w, 0xC0A8010Bu));		/* 192.168.1.11 */
		CHECK(wh_nets_ok(&w, 0x0A000001u));		/* 10.0.0.1 */
		CHECK(wh_nets_ok(&w, 0x7F000001u));		/* loopback, always */
		CHECK(!wh_nets_ok(&w, 0x08080808u));		/* 8.8.8.8 */
		CHECK(!wh_nets_ok(&w, 0xAC200001u));		/* 172.32.0.1, just outside 172.16/12 */
		wh_nets_parse(&w, "");
		CHECK(w.n == 0 && wh_nets_ok(&w, 0x08080808u));	/* no list: no filter, as libnetacl */
		wh_nets_parse(&w, "bad 1.2.3.4/33 300.1.1.1 192.168.5.0/24 0.0.0.0/0");
		CHECK(w.n == 2 && wh_nets_ok(&w, 0x08080808u));	/* unreadable entries skipped, /0 allows all */
		wh_nets_parse(&w, "192.168.5.7");
		CHECK(w.n == 1 && wh_nets_ok(&w, 0xC0A80507u) && !wh_nets_ok(&w, 0xC0A80508u));	/* a bare address = /32 */
	}
	{	/* profile-level-id= at the very end of a long fmtp line: copied without reading past the line */
		static char offer[1200];
		struct sdp_offer of;
		char fm[200];

		memset(fm, 'x', sizeof fm);
		memcpy(fm, "a=fmtp:102 ", 11);
		memcpy(fm + 159 - 17 + 11, "profile-level-id=", 17);	/* ends the 159 characters kept for the fmtp */
		fm[159 + 11] = 0;
		snprintf(offer, sizeof offer, "v=0\r\no=- 1 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\na=ice-ufrag:abcd\r\n"
			 "a=ice-pwd:0123456789abcdef01234567\r\na=fingerprint:sha-256 00:11\r\n"
			 "m=video 9 UDP/TLS/RTP/SAVPF 102\r\na=mid:0\r\na=rtpmap:102 H264/90000\r\n%s\r\n", fm);
		CHECK(sdp_parse_offer(offer, &of) == 0);
		CHECK(of.nm >= 1 && strlen(of.m[0].pts[0].plid) == 0);
	}

	if (fails) { printf("whep_test: %d failed\n", fails); return 1; }
	puts("whep_test: all ok");
	return 0;
}
