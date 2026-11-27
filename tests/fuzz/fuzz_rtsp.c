/* fuzz_rtsp: what tc100_rtsp (src/tc100rtsp/tc100_rtsp.c, built with TC100_HOST_TEST as `make test_rtsp` does, no camera
 * and no encoder) reads from an RTSP client on TCP port 554 and from its backchannel.
 *   MODE_REQ   cli_read(): the byte stream of a client over a socket: RTSP requests (request line, headers, CSeq,
 *              Content-Length and body, Transport of SETUP, track URLs, Require: backchannel), interleaved "$" frames
 *              (RTCP, and the talk RTP of the backchannel on its channel), blank lines between requests; handle() with
 *              the password check on or off. The input is cut in up to three reads (partial requests).
 *   MODE_AUTH  auth_ok() alone, fast: the Authorization header (Basic and Digest: field(), url_path(), uri_covers(),
 *              b64dec(), md5) of a request text.
 *   MODE_TALK  talk_rtp() (src/tc100rtsp/talk.c): one RTP packet of the client's backchannel (G.711 A-law, CSRC list,
 *              header extension, padding), through the speaker pipe to a script of ours that discards it.
 * Input: byte 0 = switches, the rest = the bytes of the client (MODE_REQ), the request text (MODE_AUTH), the packet (MODE_TALK). */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <poll.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include "fz.h"
#define CONF "/tmp/fuzz-conf/"
#define main tc100_rtsp_main
#include "../../src/tc100rtsp/tc100_rtsp.c"
#undef main

int LLVMFuzzerInitialize(int *argc, char ***argv)
{
	(void)argc; (void)argv;
	for (int i = 0; i < MAXCLI; i++) cl[i].fd = -1;
	snprintf(au_user, sizeof au_user, "root");
	snprintf(au_pass, sizeof au_pass, "s3cret-pass");
	au_rand_init();
#if defined(MODE_TALK)
	{	/* the player of a backchannel session: a script that reads and discards the sound */
		FILE *f = fopen("/tmp/fuzz-speaker.sh", "w");

		if (f) { fputs("#!/bin/sh\nexec cat >/dev/null\n", f); fclose(f); }
		setenv("TC100_SPEAKER_SCRIPT", "/tmp/fuzz-speaker.sh", 1);
	}
#else
	setenv("TC100_SPEAKER_SCRIPT", "/nonexistent/fuzz-speaker.sh", 1);	/* never start a program */
#endif
	/* a stream the server pretends to have: DESCRIBE answers 200, PLAY starts the burst code */
	for (int k = 0; k < 2; k++) {
		S[k].sps_len = 4; S[k].pps_len = 4; memcpy(S[k].sps, "\x67\x42\xc0\x1f", 4); memcpy(S[k].pps, "\x68\xce\x3c\x80", 4);
		snprintf(S[k].sprop, sizeof S[k].sprop, "Z0LAH5ZUBQHtAA==,aM48gA==");
		snprintf(S[k].plid, sizeof S[k].plid, "42c01f");
	}
	S[1].on = 1;
	return 0;
}

#if defined(MODE_AUTH)
int LLVMFuzzerTestOneInput(const uint8_t *d, size_t n)
{
	static const char *const methods[] = { "DESCRIBE", "SETUP", "PLAY", "OPTIONS" };
	static const char *const urls[] = { "rtsp://192.168.1.11:554/video0_unicast", "/video0_unicast/track1", "/", "rtsp://h/video1" };
	int sw;
	char *req;

	FZ_SPLIT(d, n, sw);
	if (n > 4096) return 0;
	req = fz_dup(d, n);
	au_on = 1;
	(void)auth_ok(req, methods[sw & 3], urls[sw >> 2 & 3], sw & 0x10 ? "0123456789abcdef0123456789abcdef" : "");
	au_on = 0;
	free(req);
	return 0;
}
#elif defined(MODE_TALK)
int LLVMFuzzerTestOneInput(const uint8_t *d, size_t n)
{
	static uint64_t now = 5000000;
	int sw;
	unsigned char *p;

	FZ_SPLIT(d, n, sw);
	if (n > 2048) return 0;
	p = malloc(n ? n : 1);
	memcpy(p, d, n);
	now += 20000;
	if (sw & 4) now += 3000000;		/* a pause: the ownership of the speaker may change hands */
	talk_rtp(sw & 3, p, (int)n, now);
	if (sw & 0x80) talk_release(sw & 3);
	free(p);
	return 0;
}
#else
static void drain(int fd)
{
	char b[4096];

	while (recv(fd, b, sizeof b, MSG_DONTWAIT) > 0) ;
}

int LLVMFuzzerTestOneInput(const uint8_t *d, size_t n)
{
	int sw, sv[2], cuts[2], pos = 0;
	struct cli *c = &cl[0];

	FZ_SPLIT(d, n, sw);
	if (n > 12288) return 0;
	au_on = sw & 1;
	audio_on = sw >> 1 & 1;
	talk_cfg = sw >> 2 & 1;
	srv_rtp = 5004;
	if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv)) abort();
	fcntl(sv[0], F_SETFL, fcntl(sv[0], F_GETFL) | O_NONBLOCK);
	fcntl(sv[1], F_SETFL, fcntl(sv[1], F_GETFL) | O_NONBLOCK);
	memset(c, 0, sizeof *c);
	c->fd = sv[0];
	c->peer = htonl(sw & 8 ? 0x7f000001u : 0xc0a80105u);	/* 127/8 is never locked out: the password check runs for every input */
	c->last = c->t_acc = mono_t();
	c->qprog = mono_t();
	if (sw & 0x10) { au_nonce(c->nonce); c->nonce_t = mono_t(); }	/* a Digest response can be checked against it */
	if (sw & 0x20) c->authed = 1;
	cuts[0] = (int)(n * (unsigned)(sw >> 6 & 3) / 4); cuts[1] = (int)(n * 3 / 4);
	for (int k = 0; k < 3 && c->fd >= 0; k++) {
		int end = k < 2 ? cuts[k] : (int)n;

		if (end <= pos) continue;
		if (send(sv[1], d + pos, (size_t)(end - pos), MSG_NOSIGNAL) < 0) break;
		pos = end;
		for (int guard = 0; guard < 64 && c->fd >= 0; guard++) {
			struct pollfd pf = { c->fd, POLLIN, 0 };

			if (poll(&pf, 1, 0) <= 0) break;
			cli_read(c);
		}
		drain(sv[1]);
	}
	if (c->fd >= 0) cli_close(c);
	else if (c->q) { free(c->q); c->q = NULL; }
	close(sv[1]);
	memset(c, 0, sizeof *c); c->fd = -1;
	return 0;
}
#endif
