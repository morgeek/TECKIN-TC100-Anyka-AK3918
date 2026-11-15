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
 *                                     ENC-02 (2026-11-15) script characters: n = the capture rate is 10 fps from here
 *                                     (fe_set_fps), d = the configured rate again, F = this picture gets no interrupt
 *                                     (lost), O = this picture is larger than the stream buffer (lost), o = every
 *                                     picture is as large as the model below says, from here on.
 *                                     A lost picture prints "pic <n> idr -1 len 0 list <words>" and "data 00".
 *                                     On stderr, per picture: "info <n> ok <0|1> row <failures in a row> act <fe_fail_action
 *                                     for the main stream> budget <bytes per picture> cur <frame buffer of the next
 *                                     picture> cap <IDR size limit> alloc <stream buffer>".
 *                                     Environment FE_T_MODEL=<bytes>: the simulated core codes a P picture of that many
 *                                     bytes at QP 32, half of it every 6 QP more, an IDR 4 times a P picture (default:
 *                                     100 + 10 x picture number, whatever the QP); FE_T_KBPS: the bit rate (default 1000);
 *                                     FE_T_VBRQP: the VBR quality QP (fe_set_vbr_qp);
 *                                     FE_T_SUBBUF=vendor: the 640x360 stream buffer of the vendor (fe_sub_stream)
 *   fetest actions                    fe_fail_action for 1..31 failures in a row: "<row> <main> <sub>" per line
 * License: GPL-2.0-or-later
 */
#define FE_HOST_TEST
#include <stdio.h>
#include <stdlib.h>
#include "freeenc.h"

static uint8_t pool[16 << 20] __attribute__((aligned(4096)));
static unsigned long used;
static uint32_t sim_len = 1000, sim_model;
static int sim_fail;

static unsigned long t_alloc(int n) { unsigned long v = (unsigned long)(pool + used); used += (unsigned long)(n + 4095) & ~4095ul; return used <= sizeof pool ? v : 0; }
static void t_release(unsigned long v) { (void)v; }
static int t_v2p(unsigned long v) { return (int)(0x81800000u + (uint32_t)(v - (unsigned long)pool)); }
static void t_wait(unsigned long r) { (void)r; }

static int fe_run(struct fe_enc *e, uint32_t list_pa)
{
	uint32_t *l = (uint32_t *)(void *)(e->mem + (list_pa - e->pa)), room = e->stream_alloc - FE_STREAM_HEAD;

	if (sim_fail) return -1;
	if (sim_model) {	/* bytes at QP 32, x 2^((32 - qp) / 6), an IDR 4 x */
		static const uint32_t f6[6] = { 1024, 1149, 1290, 1448, 1625, 1825 };	/* 1024 x 2^(i / 6) */
		int q = (int)((l[3] >> 16) & 0xff), d = 32 - q, sh = d >= 0 ? d / 6 : -((-d + 5) / 6);
		uint64_t v = (uint64_t)sim_model * f6[d - 6 * sh] * (((l[3] >> 28) & 3) == 2 ? 4 : 1);

		v = sh >= 0 ? v << sh : v >> -sh;
		sim_len = (uint32_t)(v >> 10);
		if (!sim_len) sim_len = 1;
	}
	if (sim_len > room) { memset(e->mem + e->stream_off + FE_STREAM_HEAD, 0xab, room); l[0x41] = sim_len; return 0; }
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
	int model_on = 0;

	if (argc == 2 && !strcmp(argv[1], "actions")) {
		for (k = 1; k <= FE_FAILS_EXIT + 1; k++) printf("%d %d %d\n", k, fe_fail_action(k, 1), fe_fail_action(k, 0));
		return 0;
	}
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
	if (getenv("FE_T_SUBBUF") && !strcmp(getenv("FE_T_SUBBUF"), "vendor")) fe_sub_stream(FE_SUB_STREAM_VENDOR);
	if (!fe_open_wh(&env, &e, hevc, w, h, 0, 25, gop, getenv("FE_T_KBPS") ? atoi(getenv("FE_T_KBPS")) : 0, qp, qmax)) { fprintf(stderr, "fe_open failed\n"); return 1; }
	fe_set_vbr(&e, vbr);
	if (getenv("FE_T_VBRQP")) fe_set_vbr_qp(&e, atoi(getenv("FE_T_VBRQP")));
	fe_set_smart(&e, smart, glong, 0, maxs);
	for (k = 0; k < n; k++) {
		uint8_t *d;
		uint32_t len, *l;
		int idr, pred, c = k < (int)strlen(script) ? script[k] : '.';

		fe_set_time(&e, start + (uint32_t)(k * ms));
		if (c == 's' || c == 'w') fe_set_still(&e, 1);
		if (c == 'm') fe_set_still(&e, 0);
		if (c == 'w') fe_want_idr(&e);
		if (c == 'n') fe_set_fps(&e, 10);
		if (c == 'd') fe_set_fps(&e, 0);
		if (c == 'o') model_on = 1;
		pred = fe_next_idr(&e);
		sim_len = c == 'O' ? e.stream_alloc : 100 + 10u * (uint32_t)k;
		sim_model = model_on && c != 'O' && getenv("FE_T_MODEL") ? (uint32_t)strtoul(getenv("FE_T_MODEL"), NULL, 10) : 0;
		sim_fail = c == 'F';
		l = (uint32_t *)(void *)(e.mem + e.list_off);
		if (fe_encode(&e, 0x82d00000u, &d, &len, &idr)) {
			if (c != 'F' && c != 'O' && !sim_model) { fprintf(stderr, "fe_encode failed\n"); return 1; }
			fprintf(stderr, "info %d ok 0 row %d act %d budget %ld cur %d cap %ld alloc %u\n", k, e.row, fe_fail_action(e.row, 1),
				(long)e.rc.budget, e.cur, (long)e.rc.idr_cap, e.stream_alloc);
			printf("pic %d idr -1 len 0 list", k);
			for (i = 0; i < 0x40; i++) printf(" %08x", l[i]);
			printf("\ndata 00\n");
			continue;
		}
		fprintf(stderr, "info %d ok 1 row %d act %d budget %ld cur %d cap %ld alloc %u\n", k, e.row, fe_fail_action(e.row, 1),
			(long)e.rc.budget, e.cur, (long)e.rc.idr_cap, e.stream_alloc);
		if (pred != idr) { fprintf(stderr, "fe_next_idr said %d, the picture was %d\n", pred, idr); return 3; }
		printf("pic %d idr %d len %u list", k, idr, len);
		for (i = 0; i < 0x40; i++) printf(" %08x", l[i]);
		printf("\ndata ");
		for (i = 0; i < (int)len; i++) printf("%02x", d[i]);
		printf("\n");
	}
	fe_close(&e);
	return 0;
}
