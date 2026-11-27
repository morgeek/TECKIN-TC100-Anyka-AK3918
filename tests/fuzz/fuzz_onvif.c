/* fuzz_onvif: what tc100-onvifd (src/onvifd/onvifd.c) reads from the network.
 *   MODE_SOAP  handle_soap() for each service (device, media, media2, events, subscription manager): the SOAP envelope,
 *              body_action(), find_elem() / get_text(), the WS-Security UsernameToken (PasswordText and PasswordDigest:
 *              check_auth(), b64dec, parse_iso, sha1) with a password set, and every operation's argument parsing.
 *   MODE_HTTP  conn_read() over a socket: the HTTP request of an ONVIF client (request line, Content-Length, header
 *              scan, body limit, service from the path, subscription id) down to the same handlers.
 *   MODE_WSD   udp_in(): a WS-Discovery datagram on UDP 3702 (Probe, Resolve, Types, MessageID, the rate limit).
 * Input: byte 0 = switches, the rest = the envelope, the HTTP bytes or the datagram. The settings come from a directory
 * of ours under /tmp (no camera files), the clock is the fake clock of fz.h (the replay and skew rules still run). */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <poll.h>
#include <fcntl.h>
#include <errno.h>
#include <net/if.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <signal.h>
#include <stdarg.h>
#include <sys/ioctl.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include "fz.h"
#define main onvifd_main
#include "../../src/onvifd/onvifd.c"
#undef main

#if defined(MODE_WSD)
static unsigned short g_wsd_port;
#endif
int LLVMFuzzerInitialize(int *argc, char ***argv)
{
	static const char dir[] = "/tmp/fuzz-onvif";
	FILE *f;

	(void)argc; (void)argv;
	mkdir(dir, 0700);
	f = fopen("/tmp/fuzz-onvif/user.pwd", "w"); if (f) { fputs("s3cret-pass\n", f); fclose(f); }
	f = fopen("/tmp/fuzz-onvif/rtspserver.conf", "w"); if (f) { fputs("[0]\nmainres=1080\n", f); fclose(f); }
	p_conf = dir;
	p_scale = "/nonexistent"; p_version = "/nonexistent"; p_serial = "/nonexistent"; p_motion = "/nonexistent";
	G.port = 8081; G.web_port = 80;
	scpy(G.web_proto, sizeof G.web_proto, "http");
	scpy(G.policy, sizeof G.policy, "main-primary");
	scpy(G.vendor, sizeof G.vendor, "Anyka"); scpy(G.hw, sizeof G.hw, "AK3918"); scpy(G.loc, sizeof G.loc, "Earth");
	scpy(G.dname, sizeof G.dname, "Teckin"); scpy(G.model, sizeof G.model, "TC100");
	scpy(G.mac, sizeof G.mac, "02:11:22:33:44:55");
	device_uuid();
	cfg_poll(NCFG, 0);
	load_config();
	cfg_loaded = 1;
	G.talk = 1; G.audio = 1;
	for (int i = 0; i < MAXCONN; i++) cn[i].fd = -1;
	signal(SIGPIPE, SIG_IGN);
#if defined(MODE_WSD)
	{	/* the discovery socket: a UDP socket on loopback; the answers go back to the sender socket, drained */
		struct sockaddr_in a;
		socklen_t l = sizeof a;

		g_ufd = socket(AF_INET, SOCK_DGRAM, 0);
		memset(&a, 0, sizeof a); a.sin_family = AF_INET; a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
		if (g_ufd < 0 || bind(g_ufd, (struct sockaddr *)&a, sizeof a) || getsockname(g_ufd, (struct sockaddr *)&a, &l)) abort();
		fcntl(g_ufd, F_SETFL, fcntl(g_ufd, F_GETFL) | O_NONBLOCK);
		g_wsd_port = a.sin_port;
	}
#endif
	return 0;
}

#if defined(MODE_SOAP)
int LLVMFuzzerTestOneInput(const uint8_t *d, size_t n)
{
	static const int svcs[] = { SV_DEVICE, SV_MEDIA, SV_MEDIA2, SV_EVENT, SV_SUB };
	int sw, st;
	char *b;

	FZ_SPLIT(d, n, sw);
	if (n > REQ_MAX) return 0;
	b = fz_dup(d, n);
	ol = 0; oerr = 0;
	g_peer = sw & 0x80 ? 0x7f000001u : 0xc0a80105u;	/* 127/8 is never locked out: the password check runs for every input */
	g_req_sub = sw >> 4 & 7;
	G.pass[0] = sw & 8 ? 0 : 's';		/* no password: every operation is reached without a token */
	if (G.pass[0]) snprintf(G.pass, sizeof G.pass, "s3cret-pass");
	st = handle_soap(svcs[(sw & 7) % 5], b, (int)n);
	if (st != -1 && (ol < 0 || ol > OUT_MAX)) abort();
	free(b);
	return 0;
}
#elif defined(MODE_HTTP)
int LLVMFuzzerTestOneInput(const uint8_t *d, size_t n)
{
	int sw, sv[2];
	struct conn *c = &cn[0];
	size_t half;

	FZ_SPLIT(d, n, sw);
	if (n > 2 * REQ_MAX) return 0;
	if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv)) abort();
	fcntl(sv[0], F_SETFL, fcntl(sv[0], F_GETFL) | O_NONBLOCK);
	memset(c, 0, sizeof *c);
	c->fd = sv[0];
	c->ip = sw & 0x80 ? 0x7f000001u : 0xc0a80105u;
	c->deadline = now_ms() + READ_MS;
	snprintf(G.pass, sizeof G.pass, "%s", sw & 1 ? "s3cret-pass" : "");
	half = (size_t)(sw >> 1 & 7) * n / 8;	/* up to two reads */
	for (int k = 0; k < 2 && c->fd >= 0; k++) {
		size_t from = k ? half : 0, to = k ? n : half;
		char sink[8192];

		if (to <= from) continue;
		if (send(sv[1], d + from, to - from, MSG_NOSIGNAL | MSG_DONTWAIT) < 0) break;
		conn_read(c);
		while (recv(sv[1], sink, sizeof sink, MSG_DONTWAIT) > 0) ;
	}
	if (c->fd >= 0) conn_close(c);
	close(sv[1]);
	memset(c, 0, sizeof *c); c->fd = -1;
	return 0;
}
#else
static int g_wsd_port_dummy;
int LLVMFuzzerTestOneInput(const uint8_t *d, size_t n)
{
	static int snd = -1;
	struct sockaddr_in to;
	char sink[8192];
	int sw;

	FZ_SPLIT(d, n, sw);
	if (n > 4096) return 0;
	if (snd < 0) {
		struct sockaddr_in a;

		snd = socket(AF_INET, SOCK_DGRAM, 0);
		memset(&a, 0, sizeof a); a.sin_family = AF_INET; a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
		if (snd < 0 || bind(snd, (struct sockaddr *)&a, sizeof a)) abort();
		fcntl(snd, F_SETFL, fcntl(snd, F_GETFL) | O_NONBLOCK);
	}
	memset(&to, 0, sizeof to); to.sin_family = AF_INET; to.sin_addr.s_addr = htonl(INADDR_LOOPBACK); to.sin_port = g_wsd_port;
	if (sendto(snd, d, n, 0, (struct sockaddr *)&to, sizeof to) < 0) return 0;
	ol = 0; oerr = 0;
	udp_in();
	while (recv(snd, sink, sizeof sink, MSG_DONTWAIT) > 0) ;
	(void)g_wsd_port_dummy;
	return 0;
}
#endif
