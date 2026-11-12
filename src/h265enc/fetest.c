/*
 * fetest: freeenc.h on the build host (tests/test_h265cmdlist.py FreeEnc). The core is simulated: it writes a length
 * into list word 0x41 and that many bytes (0xab, the first one 0x80) at stream + 0x820.
 *   fetest hevc|avc PICTURES QP GOP   prints, per picture: "pic <n> idr <0|1> len <bytes> list <words 0-0x3f>" then
 *                                     "data <hex of the access unit>"
 *   fetest ... [MODE SCRIPT [GOP_LONG [QMAX [MS_PER_PICTURE [MAX_SECONDS [START_MS]]]]]]
 *                                     MODE cbr|vbr|smart (smart = VBR + smart mode; default cbr); SCRIPT: one character per
 *                                     picture before it is coded: s = scene still, m = motion, w = still and a client
 *                                     waits for a keyframe, . = no change (a short script ends in '.'); the QP range is
 *                                     QP..QMAX (default QP..QP); the QP of a picture is list word 3 bits 16-23;
 *                                     MS_PER_PICTURE (default 40) is the clock step, MAX_SECONDS (default 12) the smart time cap,
 *                                     START_MS (default 0) the clock at picture 0 (the clock wraps at 2^32)
 * License: GPL-2.0-or-later
 */
#define FE_HOST_TEST
#include <stdio.h>
#include <stdlib.h>
#include "freeenc.h"

static uint8_t pool[16 << 20] __attribute__((aligned(4096)));
static unsigned long used;
static uint32_t sim_len = 1000;

static unsigned long t_alloc(int n) { unsigned long v = (unsigned long)(pool + used); used += (unsigned long)(n + 4095) & ~4095ul; return used <= sizeof pool ? v : 0; }
static void t_release(unsigned long v) { (void)v; }
static int t_v2p(unsigned long v) { return (int)(0x81800000u + (uint32_t)(v - (unsigned long)pool)); }
static void t_wait(unsigned long r) { (void)r; }

static int fe_run(struct fe_enc *e, uint32_t list_pa)
{
	uint32_t *l = (uint32_t *)(void *)(e->mem + (list_pa - e->pa));

	memset(e->mem + e->stream_off + FE_STREAM_HEAD, 0xab, sim_len);
	e->mem[e->stream_off + FE_STREAM_HEAD] = 0x80;
	l[0x41] = sim_len;
	return 0;
}

int main(int argc, char **argv)
{
	static const struct fe_env env = { NULL, t_alloc, t_release, t_v2p, t_wait, NULL };
	static struct fe_enc e;
	int hevc, w, h, n, qp, gop, k, i, qmax, glong = 0, vbr = 0, smart = 0, ms = 40, maxs = 12;
	uint32_t start = 0;
	const char *script = "";

	if (argc != 5 && !(argc >= 7 && argc <= 12)) {
		fprintf(stderr, "usage: fetest hevc|hevc720|avc|avc720|avc1080 PICTURES QP GOP [cbr|vbr|smart SCRIPT [GOP_LONG [QMAX [MS [MAXS [START]]]]]]\n");
		return 2;
	}
	hevc = !strncmp(argv[1], "hevc", 4);
	if (strstr(argv[1], "1080")) { w = 1920; h = 1080; }
	else if (strstr(argv[1], "720")) { w = 1280; h = 720; }
	else { w = hevc ? 1920 : 640; h = hevc ? 1080 : 360; }
	n = atoi(argv[2]); qp = atoi(argv[3]); gop = atoi(argv[4]); qmax = qp;
	if (argc >= 7) {
		vbr = !strcmp(argv[5], "vbr") || !strcmp(argv[5], "smart"); smart = !strcmp(argv[5], "smart"); script = argv[6];
		if (argc >= 8) glong = atoi(argv[7]);
		if (argc >= 9) qmax = atoi(argv[8]);
		if (argc >= 10) ms = atoi(argv[9]);
		if (argc >= 11) maxs = atoi(argv[10]);
		if (argc >= 12) start = (uint32_t)strtoul(argv[11], NULL, 10);
	}
	if (!fe_open_wh(&env, &e, hevc, w, h, 0, 25, gop, 0, qp, qmax)) { fprintf(stderr, "fe_open failed\n"); return 1; }
	fe_set_vbr(&e, vbr);
	fe_set_smart(&e, smart, glong, 0, maxs);
	for (k = 0; k < n; k++) {
		uint8_t *d;
		uint32_t len, *l;
		int idr, pred, c = k < (int)strlen(script) ? script[k] : '.';

		fe_set_time(&e, start + (uint32_t)(k * ms));
		if (c == 's' || c == 'w') fe_set_still(&e, 1);
		if (c == 'm') fe_set_still(&e, 0);
		if (c == 'w') fe_want_idr(&e);
		pred = fe_next_idr(&e);
		sim_len = 100 + 10u * (uint32_t)k;
		if (fe_encode(&e, 0x82d00000u, &d, &len, &idr)) { fprintf(stderr, "fe_encode failed\n"); return 1; }
		if (pred != idr) { fprintf(stderr, "fe_next_idr said %d, the picture was %d\n", pred, idr); return 3; }
		l = (uint32_t *)(void *)(e.mem + e.list_off);
		printf("pic %d idr %d len %u list", k, idr, len);
		for (i = 0; i < 0x40; i++) printf(" %08x", l[i]);
		printf("\ndata ");
		for (i = 0; i < (int)len; i++) printf("%02x", d[i]);
		printf("\n");
	}
	fe_close(&e);
	return 0;
}
