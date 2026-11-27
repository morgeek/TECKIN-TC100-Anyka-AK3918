/* fuzz_mqttd: what tc100-mqttd reads from the MQTT broker: parse_in() (the fixed header and "remaining length" of every
 * packet) and on_packet() (CONNACK, PUBLISH of a command, SUBACK, PINGRESP) of src/mqttd/mqttd.c, in the states
 * CONNACKWAIT and UP, the bytes arriving in two reads as from a socket.
 * Input: byte 0 = switches (bit 0: state UP, else CONNACKWAIT; bits 1-7: where the input is cut in two reads), rest = bytes. */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#include "fz.h"
#define main mqttd_main
#include "../../src/mqttd/mqttd.c"
#undef main

int LLVMFuzzerInitialize(int *argc, char ***argv)
{
	(void)argc; (void)argv;
	g_log = "/dev/null";		/* logf_() opens it at every call */
	g_status = "/dev/null";
	snprintf(C.root, sizeof C.root, "tc100/cam");
	snprintf(C.cmd, sizeof C.cmd, "tc100/cam/cmd");
	snprintf(C.host, sizeof C.host, "broker.lan"); snprintf(C.port, sizeof C.port, "1883");
	snprintf(C.node, sizeof C.node, "tc100"); snprintf(C.devname, sizeof C.devname, "TC100");
	snprintf(C.dprefix, sizeof C.dprefix, "homeassistant");
	C.disc_c = 1; C.ha_on = 1; C.health_s = 60; C.ping_s = 30; C.bo_init = 2; C.bo_max = 60; C.bo_mul = 2;
	return 0;
}

static void reset(void)
{
	for (int i = 0; i < g_qn; i++) job_free(&g_q[i]);
	g_qn = 0;
	bfree(&g_in); bfree(&g_out); bfree(&g_pend);
	g_started = 0;
}

int LLVMFuzzerTestOneInput(const uint8_t *d, size_t n)
{
	int sw;
	size_t cut;

	FZ_SPLIT(d, n, sw);
	reset();
	g_state = sw & 1 ? UP : CONNACKWAIT;
	cut = n ? (size_t)(sw >> 1) * n / 128 : 0;
	if (cut) {
		bput(&g_in, d, cut, MAX_FRAME + 16);
		(void)parse_in();
	}
	if (n > cut && bput(&g_in, d + cut, n - cut, MAX_FRAME + 16) == 0) (void)parse_in();
	reset();
	return 0;
}
