/* libFuzzer target for tc100-httpsd HTTP/1.1 framing, CIDR ACL, and SAN DER helpers. */
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "httpsd_http.h"

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
	char buf[HTTPSD_MAX_HDR + 16];
	char out[HTTPSD_MAX_HDR + 256];
	uint8_t san[512];
	struct httpsd_req req;
	struct httpsd_resp resp;
	struct httpsd_nets nets;
	size_t n = size < sizeof buf - 1 ? size : sizeof buf - 1;
	int r, bm = 0;

	memcpy(buf, data, n);
	buf[n] = '\0';

	r = httpsd_parse_req(buf, n, &req);
	if (r > 0)
		(void)httpsd_rewrite_req(buf, (size_t)r, "192.168.1.50", out, sizeof out);

	r = httpsd_parse_resp(buf, n, &resp);
	if (r > 0)
		(void)httpsd_rewrite_resp(buf, (size_t)r, 0, 1, &resp, out, sizeof out, &bm);

	httpsd_nets_parse(&nets, buf);
	(void)httpsd_nets_allow(&nets, 0x0a000001u);

	(void)httpsd_build_san_der(buf, "192.168.1.24", san, sizeof san);
	return 0;
}
