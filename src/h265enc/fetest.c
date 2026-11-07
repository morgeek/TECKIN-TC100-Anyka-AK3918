/*
 * fetest: freeenc.h on the build host (tests/test_h265cmdlist.py FreeEnc). The core is simulated: it writes a length
 * into list word 0x41 and that many bytes (0xab, the first one 0x80) at stream + 0x820.
 *   fetest hevc|avc PICTURES QP GOP   prints, per picture: "pic <n> idr <0|1> len <bytes> list <words 0-0x3f>" then
 *                                     "data <hex of the access unit>"
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
	int hevc, w, h, n, qp, gop, k, i;

	if (argc != 5) { fprintf(stderr, "usage: fetest hevc|hevc720|avc|avc720|avc1080 PICTURES QP GOP\n"); return 2; }
	hevc = !strncmp(argv[1], "hevc", 4);
	if (strstr(argv[1], "1080")) { w = 1920; h = 1080; }
	else if (strstr(argv[1], "720")) { w = 1280; h = 720; }
	else { w = hevc ? 1920 : 640; h = hevc ? 1080 : 360; }
	n = atoi(argv[2]); qp = atoi(argv[3]); gop = atoi(argv[4]);
	if (!fe_open_wh(&env, &e, hevc, w, h, 0, 25, gop, 0, qp, qp)) { fprintf(stderr, "fe_open failed\n"); return 1; }
	for (k = 0; k < n; k++) {
		uint8_t *d;
		uint32_t len, *l;
		int idr;

		sim_len = 100 + 10u * (uint32_t)k;
		if (fe_encode(&e, 0x82d00000u, &d, &len, &idr)) { fprintf(stderr, "fe_encode failed\n"); return 1; }
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
