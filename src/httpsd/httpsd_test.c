/* httpsd_test.c: host unit tests for src/httpsd/httpsd_http.h (no Mbed TLS dependency). */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "httpsd_http.h"

static void test_req_parsing_and_smuggling(void)
{
	struct httpsd_req r;
	char out[512];
	const char *p1 = "GET /cgi-bin/statusline.cgi HTTP/1.1\r\nHost: tc100\r\nX-Forwarded-Proto: http\r\nConnection: keep-alive\r\n\r\n";
	int hl = httpsd_parse_req(p1, strlen(p1), &r);
	assert(hl == (int)strlen(p1));
	assert(r.http_minor == 1 && r.keepalive == 1 && !r.is_head && !r.has_cl);

	int rw = httpsd_rewrite_req(p1, (size_t)hl, "192.168.1.50", out, sizeof out);
	assert(rw > 0);
	out[rw] = 0;
	assert(strstr(out, "Connection: close\r\n") != NULL);
	assert(strstr(out, "X-Forwarded-Proto: https\r\n") != NULL);
	assert(strstr(out, "X-Forwarded-For: 192.168.1.50\r\n") != NULL);
	assert(strstr(out, "X-Forwarded-Proto: http\r\n") == NULL);

	/* Partial read returns 0 */
	assert(httpsd_parse_req("GET / HTTP/1.1\r\nHost: a\r\n", 25, &r) == 0);

	/* Dual / conflicting Content-Length rejected */
	const char *dup_cl = "POST /x HTTP/1.1\r\nContent-Length: 5\r\nContent-Length: 5\r\n\r\n";
	assert(httpsd_parse_req(dup_cl, strlen(dup_cl), &r) == -1);

	/* CL + TE smuggling rejected */
	const char *cl_te = "POST /x HTTP/1.1\r\nContent-Length: 5\r\nTransfer-Encoding: chunked\r\n\r\n";
	assert(httpsd_parse_req(cl_te, strlen(cl_te), &r) == -1);

	/* Oversized Content-Length rejected with -2 (413) */
	const char *big_cl = "POST /x HTTP/1.1\r\nContent-Length: 99999999\r\n\r\n";
	assert(httpsd_parse_req(big_cl, strlen(big_cl), &r) == -2);

	/* Bad method / bare LF / obs-fold rejected */
	assert(httpsd_parse_req("BAD / HTTP/1.1\r\nHost: a\n\r\n", 26, &r) == -1);
	assert(httpsd_parse_req("GET / HTTP/1.1\r\n fold: 1\r\n\r\n", 28, &r) == -1);
	assert(httpsd_parse_req("GET / HTTP/2.0\r\nHost: a\r\n\r\n", 27, &r) == -1);

	/* HTTP/1.0 Keep-Alive logic */
	const char *h10_ka = "GET /a HTTP/1.0\r\nConnection: keep-alive\r\n\r\n";
	assert(httpsd_parse_req(h10_ka, strlen(h10_ka), &r) > 0 && r.http_minor == 0 && r.keepalive == 1);
	const char *h10_no = "GET /a HTTP/1.0\r\nHost: a\r\n\r\n";
	assert(httpsd_parse_req(h10_no, strlen(h10_no), &r) > 0 && r.http_minor == 0 && r.keepalive == 0);
}

static void test_resp_rewriting(void)
{
	struct httpsd_resp rp;
	char out[512];
	int bm = -1, rl, hl;

	/* Backend Content-Length: upgraded to HTTP/1.1 keep-alive */
	const char *r_cl = "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: 4\r\nConnection: close\r\n\r\n";
	hl = httpsd_parse_resp(r_cl, strlen(r_cl), &rp);
	assert(hl == (int)strlen(r_cl) && rp.status == 200 && rp.has_cl && rp.content_length == 4);
	rl = httpsd_rewrite_resp(r_cl, (size_t)hl, 0, 1, &rp, out, sizeof out, &bm);
	assert(rl > 0 && bm == HTTPSD_BODY_CL);
	out[rl] = 0;
	assert(strncmp(out, "HTTP/1.1 200 OK\r\n", 17) == 0);
	assert(strstr(out, "Connection: keep-alive\r\n") != NULL);
	assert(strstr(out, "Connection: close") == NULL);

	/* Backend CGI without Content-Length on Keep-Alive client -> chunked */
	const char *r_cgi = "HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n";
	hl = httpsd_parse_resp(r_cgi, strlen(r_cgi), &rp);
	assert(hl == (int)strlen(r_cgi) && !rp.has_cl);
	rl = httpsd_rewrite_resp(r_cgi, (size_t)hl, 0, 1, &rp, out, sizeof out, &bm);
	assert(rl > 0 && bm == HTTPSD_BODY_CHUNKED_OUT);
	out[rl] = 0;
	assert(strstr(out, "Transfer-Encoding: chunked\r\n") != NULL);
	assert(strstr(out, "Connection: keep-alive\r\n") != NULL);

	/* HEAD request -> BODY_NONE */
	rl = httpsd_rewrite_resp(r_cl, strlen(r_cl), 1, 1, &rp, out, sizeof out, &bm);
	assert(rl > 0 && bm == HTTPSD_BODY_NONE);

	/* No keepalive -> Connection: close */
	rl = httpsd_rewrite_resp(r_cgi, strlen(r_cgi), 0, 0, &rp, out, sizeof out, &bm);
	assert(rl > 0 && bm == HTTPSD_BODY_CLOSE);
	out[rl] = 0;
	assert(strstr(out, "Connection: close\r\n") != NULL);
}

static void test_acl_and_lockout_and_san(void)
{
	struct httpsd_nets nets;
	struct httpsd_lockout lo;
	uint8_t der[256];
	int i, n;
	uint32_t lan = (192U << 24) | (168U << 16) | (1U << 8) | 10U;
	uint32_t wan = (8U << 24) | 8U;
	uint32_t lo_ip = (127U << 24) | 1U;

	httpsd_nets_parse(&nets, "192.168.1.0/24 10.0.0.0/8");
	assert(httpsd_nets_allow(&nets, lan) == 1);
	assert(httpsd_nets_allow(&nets, lo_ip) == 1);
	assert(httpsd_nets_allow(&nets, wan) == 0);
	httpsd_nets_parse(&nets, "");
	assert(httpsd_nets_allow(&nets, wan) == 1);

	httpsd_lockout_init(&lo);
	for (i = 0; i < HTTPSD_LOCK_FAILS - 1; i++) {
		httpsd_lockout_fail(&lo, lan, 1000);
		assert(httpsd_lockout_blocked(&lo, lan, 1001) == 0);
	}
	httpsd_lockout_fail(&lo, lan, 1002);
	assert(httpsd_lockout_blocked(&lo, lan, 1002) == 1);
	assert(httpsd_lockout_blocked(&lo, lan, 1002 + HTTPSD_LOCK_SEC) == 0);
	/* Loopback exempt from lockout */
	for (i = 0; i < HTTPSD_LOCK_FAILS + 2; i++) httpsd_lockout_fail(&lo, lo_ip, 2000);
	assert(httpsd_lockout_blocked(&lo, lo_ip, 2000) == 0);

	n = httpsd_build_san_der("cam1", "192.168.1.24", der, sizeof der);
	assert(n > 10 && der[0] == 0x30);
	/* Check IPv4 [7] 0x87 0x04 192 168 1 24 at tail */
	assert(der[n - 6] == 0x87 && der[n - 5] == 0x04 &&
	       der[n - 4] == 192 && der[n - 3] == 168 && der[n - 2] == 1 && der[n - 1] == 24);
}

int main(void)
{
	test_req_parsing_and_smuggling();
	test_resp_rewriting();
	test_acl_and_lockout_and_san();
	printf("httpsd_test: all checks passed\n");
	return 0;
}
