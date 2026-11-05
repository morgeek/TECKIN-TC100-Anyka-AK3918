/* tc100-mqttd: the MQTT side of the camera in one small process (replaces the four shell processes of
 * scripts/mqtt-bridge.sh run, which forged packets into nc).
 *
 * What it does (MQTT 3.1.1 over plain TCP, QoS 0, one connection, one poll loop):
 *   - CONNECT as "<client id>-sub" with a retained Will "<root>/availability" = offline, publishes "online" and
 *     subscribes the command topic; reconnects with the backoff / circuit breaker of config/mqtt.conf;
 *   - every payload it receives on the command topic is handed to `mqtt-bridge.sh command <payload> mqtt`
 *     (the one place that knows the commands: same handlers as the web UI), as an argument, never through a shell
 *     string, with a time limit;
 *   - the discovery payloads, the health JSON, the integration manifest and the results of the commands are still
 *     produced by mqtt-bridge.sh (one implementation, byte for byte the same topics and payloads). That script runs
 *     with MQTT_SINK=1 and writes what it would have sent to file descriptor 3 as records
 *         P<retain><topic> NUL <payload> NUL        (publish this)
 *         F<retain><topic> NUL <file>    NUL        (publish the content of this file, e.g. the snapshot)
 *     which this program publishes over its own connection. It runs only when there is something to do (once after
 *     connecting, every MQTT_HEALTH_INTERVAL_SECONDS, once per command), one job at a time.
 *   - `mqtt-bridge.sh publish ...` called by the other scripts (motion, sound, tamper...) writes the same records to
 *     the FIFO this program reads (a record is below PIPE_BUF: atomic), instead of opening a connection of its own;
 *   - the live status read by the web UI is /tmp/mqtt_last_pub.status: "<time> ok", "<time> fail", or
 *     "<time> fail <CONNACK code>" when the broker refuses the login.
 *
 * usage: tc100-mqttd [-s SCRIPT] [-l LOG] [-t STATUS] [-f FIFO] [-p PIDFILE]
 * The connection settings come from `SCRIPT print-config` (KEY=VALUE lines, defaults and auto-detection already
 * applied by load_config): this program never reads mqtt.conf itself and never logs the password.
 *
 * Built like src/tc100rtsp: glibc cross compiler, linked to run under the uClibc loader of the camera (Makefile).
 * Only plain, old libc calls on purpose (no stat, no time64, no C2x redirects). Host build for the tests:
 *   cc -O1 -Wall -Wextra -o tc100-mqttd mqttd.c
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define KEEPALIVE 60		/* announced in CONNECT; PINGREQ every MQTT_KEEPALIVE_PING_SECONDS (30) */
#define CONNECT_TIMEOUT_MS 10000
#define PONG_TIMEOUT_MS 20000	/* no answer to a PINGREQ: the link is dead */
#define MAX_FRAME 4096		/* incoming packet limit, as the shell decoder had */
#define MAX_OUT (2 << 20)	/* bytes waiting for a slow broker */
#define MAX_PEND (128 << 10)	/* publishes made while there is no connection (sent after the next CONNACK) */
#define MAX_REC (1 << 20)	/* one record of a job (the manifest, a snapshot) */
#define MAX_QUEUE 16
#define LOG_MAX 65536		/* the log lives in RAM: keep the last 100 lines past this size */
#define LOG_KEEP 100

static const char *g_script = "/mnt/scripts/mqtt-bridge.sh";
static const char *g_log = "/tmp/log/mqtt-bridge.log";
static const char *g_status = "/tmp/mqtt_last_pub.status";
static const char *g_fifo = "/tmp/mqtt-bridge.pub";
static const char *g_pidfile = "/var/run/tc100-mqttd.pid";

static struct {
	char host[128], port[8], user[128], pass[128], cid[140], root[160], cmd[256];
	int enable, health_s, ping_s, bo_init, bo_max, bo_mul, cb_thresh, cb_cool;
} C;

struct buf { unsigned char *p; size_t len, cap; };

enum { DISC, CONNECTING, CONNACKWAIT, UP };
enum { J_STARTUP, J_HEALTH, J_COMMAND, J_LOGEVENT };

struct job { int kind; char *a, *b; };

static int g_state = DISC, g_sock = -1, g_fifofd = -1, g_sigpipe[2] = { -1, -1 };
static struct buf g_in, g_out, g_pend, g_fin, g_cin;
static long long g_deadline, g_next_try, g_next_ping, g_next_health, g_pong_due, g_last_ok_write;
static int g_failures, g_backoff, g_started;
static volatile sig_atomic_t g_stop, g_chld;
static struct job g_q[MAX_QUEUE];
static int g_qn;
static pid_t g_child;
static int g_cpipe = -1;
static long long g_child_deadline;
static int g_pend_warned;

static long long now_ms(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return (long long)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

/* ---- log (same file and "<epoch> text" lines as log_msg of the shell bridge) ---- */

static void log_rotate(const char *path)
{
	char t2[300], *tmp = malloc(LOG_MAX + 1024);
	int f = open(path, O_RDONLY);
	long n, k = 0;
	char *s, *e;
	int lines = 0;
	off_t sz;

	if (f < 0 || !tmp) { if (f >= 0) close(f); free(tmp); return; }
	sz = lseek(f, 0, SEEK_END);
	lseek(f, sz > LOG_MAX + 1023 ? sz - (LOG_MAX + 1023) : 0, SEEK_SET);
	while (k < LOG_MAX + 1023 && (n = read(f, tmp + k, LOG_MAX + 1023 - k)) > 0) k += n;
	close(f);
	e = tmp + k;
	for (s = e; s > tmp; s--)	/* start of the last LOG_KEEP lines */
		if (s[-1] == '\n' && s != e && ++lines == LOG_KEEP) break;
	snprintf(t2, sizeof t2, "%s.tmp", path);
	f = open(t2, O_WRONLY | O_CREAT | O_TRUNC, 0644);
	if (f >= 0) {
		if (write(f, s, e - s) == e - s) { close(f); rename(t2, path); } else { close(f); unlink(t2); }
	}
	free(tmp);
}

static void logf_(const char *fmt, ...)
{
	char line[400];
	va_list ap;
	int n, f;
	off_t sz;

	n = snprintf(line, sizeof line, "%ld ", (long)time(NULL));
	va_start(ap, fmt);
	n += vsnprintf(line + n, sizeof line - n - 1, fmt, ap);
	va_end(ap);
	if (n > (int)sizeof line - 2) n = sizeof line - 2;
	line[n++] = '\n';
	f = open(g_log, O_WRONLY | O_APPEND | O_CREAT, 0644);
	if (f < 0) return;
	sz = lseek(f, 0, SEEK_END);
	if (write(f, line, n) < 0) { /* RAM log: nothing to do */ }
	close(f);
	if (sz > LOG_MAX) log_rotate(g_log);
}

/* ---- the status file of the web UI ---- */

static void status(int ok, int code, int throttle)
{
	char s[64];
	int n, f;
	long long t = now_ms();

	if (throttle && t - g_last_ok_write < 1000) return;	/* one write per second is plenty */
	g_last_ok_write = t;
	if (ok) n = snprintf(s, sizeof s, "%ld ok\n", (long)time(NULL));
	else if (code > 0) n = snprintf(s, sizeof s, "%ld fail %d\n", (long)time(NULL), code);
	else n = snprintf(s, sizeof s, "%ld fail\n", (long)time(NULL));
	f = open(g_status, O_WRONLY | O_CREAT | O_TRUNC, 0644);
	if (f < 0) return;
	if (write(f, s, n) < 0) { /* nothing to do */ }
	close(f);
}

/* ---- growing buffers ---- */

static int bput(struct buf *b, const void *d, size_t n, size_t max)
{
	if (b->len + n > max) return -1;
	if (b->len + n > b->cap) {
		size_t c = b->cap ? b->cap : 512;
		unsigned char *p;

		while (c < b->len + n) c *= 2;
		p = realloc(b->p, c);
		if (!p) return -1;
		b->p = p;
		b->cap = c;
	}
	memcpy(b->p + b->len, d, n);
	b->len += n;
	return 0;
}

static void bdrop(struct buf *b, size_t n)
{
	if (n >= b->len) { b->len = 0; return; }
	memmove(b->p, b->p + n, b->len - n);
	b->len -= n;
}

static void bfree(struct buf *b)	/* give the memory back: these buffers are empty most of the time */
{
	free(b->p);
	b->p = NULL;
	b->len = b->cap = 0;
}

/* ---- MQTT 3.1.1 packets ---- */

static void put_varint(unsigned char *o, size_t *n, size_t v)
{
	do {
		unsigned char d = v % 128;

		v /= 128;
		o[(*n)++] = v ? d | 128 : d;
	} while (v);
}

static int put_str(struct buf *b, const char *s)
{
	size_t l = strlen(s);
	unsigned char h[2] = { l >> 8, l & 255 };

	return bput(b, h, 2, MAX_OUT) | bput(b, s, l, MAX_OUT);
}

static void pkt_connect(struct buf *b)
{
	char cid[160], will[200];
	struct buf p = { 0 };
	unsigned char h[16] = { 0x10 };
	size_t n = 1;
	unsigned char flags = 0x02 | 0x04 | 0x20;	/* clean session + will + retained will, QoS 0 */

	snprintf(cid, sizeof cid, "%s-sub", C.cid);
	snprintf(will, sizeof will, "%s/availability", C.root);
	put_str(&p, cid);
	put_str(&p, will);
	put_str(&p, "offline");
	if (*C.user) {
		flags |= 0x80 | 0x40;
		put_str(&p, C.user);
		put_str(&p, C.pass);
	}
	put_varint(h, &n, 10 + p.len);
	memcpy(h + n, "\x00\x04MQTT\x04", 7);
	n += 7;
	h[n++] = flags;
	h[n++] = 0;
	h[n++] = KEEPALIVE;
	bput(b, h, n, MAX_OUT);
	bput(b, p.p, p.len, MAX_OUT);
	free(p.p);
}

static void pkt_subscribe(struct buf *b, const char *topic)
{
	unsigned char h[8] = { 0x82 };
	size_t n = 1, l = strlen(topic);

	put_varint(h, &n, 2 + 2 + l + 1);
	h[n++] = 0; h[n++] = 1;		/* packet id 1 */
	bput(b, h, n, MAX_OUT);
	put_str(b, topic);
	bput(b, "\0", 1, MAX_OUT);	/* QoS 0 */
}

/* encoded PUBLISH (QoS 0); returns -1 when it does not fit */
static int pkt_publish(struct buf *b, int retain, const char *topic, const void *pl, size_t pn, size_t max)
{
	unsigned char h[8] = { 0x30 | (retain ? 1 : 0) };
	size_t n = 1, tl = strlen(topic);
	unsigned char t[2] = { tl >> 8, tl & 255 };

	if (tl > 65535) return -1;	/* the topic length field has 16 bits (audit M1: it was truncated) */
	if (b->len + 7 + tl + pn > max) return -1;
	put_varint(h, &n, 2 + tl + pn);
	bput(b, h, n, max);
	bput(b, t, 2, max);
	bput(b, topic, tl, max);
	return bput(b, pl, pn, max);
}

/* publish: straight into the send buffer when connected, else kept for the next connection */
static void send_publish(int retain, const char *topic, const void *pl, size_t pn)
{
	int r;

	if (g_state == UP) {
		r = pkt_publish(&g_out, retain, topic, pl, pn, MAX_OUT);
	} else {
		r = pkt_publish(&g_pend, retain, topic, pl, pn, MAX_PEND);
		if (r && !g_pend_warned) { g_pend_warned = 1; logf_("publish queue full while disconnected: dropping"); }
	}
	if (r) logf_("publish of %s dropped (%zu bytes, buffer full)", topic, pn);
}

/* ---- jobs: the shell script as a worker, one at a time ---- */

static void job_free(struct job *j) { free(j->a); free(j->b); }

static void queue_job(int kind, const char *a, const char *b)
{
	if (kind == J_HEALTH)	/* one is enough */
		for (int i = 0; i < g_qn; i++) if (g_q[i].kind == J_HEALTH) return;
	if (g_qn >= MAX_QUEUE) { logf_("job queue full: dropping a job"); return; }
	g_q[g_qn].kind = kind;
	g_q[g_qn].a = a ? strdup(a) : NULL;
	g_q[g_qn].b = b ? strdup(b) : NULL;
	g_qn++;
}

static pid_t spawn(char *const argv[], int *rfd, int on_stdout)
{
	int pfd[2];
	pid_t pid;

	if (pipe(pfd) < 0) return -1;
	pid = fork();
	if (pid < 0) { close(pfd[0]); close(pfd[1]); return -1; }
	if (pid == 0) {
		int dn = open("/dev/null", O_RDWR);

		setsid();	/* one process group: the whole job can be killed on a timeout */
		signal(SIGPIPE, SIG_DFL);
		signal(SIGHUP, SIG_DFL);
		dup2(dn, 0); dup2(dn, 1); dup2(dn, 2);
		if (on_stdout) dup2(pfd[1], 1);	/* print-config answers on standard output */
		if (pfd[1] != 3) { dup2(pfd[1], 3); }
		for (int i = 4; i < 64; i++) close(i);
		setenv("MQTT_SINK", "1", 1);
		setenv("MQTT_HOST_RESOLVED", C.host, 1);
		execv(argv[0], argv);
		_exit(127);
	}
	close(pfd[1]);
	fcntl(pfd[0], F_SETFD, FD_CLOEXEC);
	fcntl(pfd[0], F_SETFL, O_NONBLOCK);
	*rfd = pfd[0];
	return pid;
}

static void start_job(void)
{
	struct job j = g_q[0];
	char *argv[6];
	int tmo = 120;

	memmove(g_q, g_q + 1, (--g_qn) * sizeof g_q[0]);
	argv[0] = (char *)g_script;
	switch (j.kind) {
	case J_STARTUP: argv[1] = "startup"; argv[2] = NULL; tmo = 300; break;
	case J_HEALTH: argv[1] = "health-cycle"; argv[2] = NULL; break;
	case J_COMMAND: argv[1] = "command"; argv[2] = j.a; argv[3] = "mqtt"; argv[4] = NULL; break;
	default: argv[1] = "log-event"; argv[2] = j.a; argv[3] = j.b; argv[4] = NULL; tmo = 20; break;
	}
	g_child = spawn(argv, &g_cpipe, 0);
	if (g_child < 0) { logf_("cannot start %s", argv[1]); g_child = 0; }
	else g_child_deadline = now_ms() + tmo * 1000LL;
	job_free(&j);
}

/* records written by the job (or by `mqtt-bridge.sh publish` into the FIFO): P<r>topic NUL payload NUL, F<r>... */
static void file_publish(int retain, const char *topic, const char *path)
{
	struct buf d = { 0 };
	unsigned char tmp[4096];
	int f = open(path, O_RDONLY);
	long n;

	if (f < 0) { logf_("cannot read %s for %s", path, topic); return; }
	while ((n = read(f, tmp, sizeof tmp)) > 0)
		if (bput(&d, tmp, n, MAX_REC) < 0) { logf_("%s is too big to publish", path); n = -1; break; }
	close(f);
	if (n == 0 && d.len) send_publish(retain, topic, d.p, d.len);
	free(d.p);
}

static void parse_records(struct buf *b)
{
	for (;;) {
		unsigned char *t, *pl, *e;

		if (b->len < 3) return;
		if (b->p[0] != 'P' && b->p[0] != 'F') { logf_("bad record, dropping %zu bytes", b->len); b->len = 0; return; }
		t = memchr(b->p + 2, 0, b->len - 2);
		if (!t) break;
		pl = t + 1;
		e = memchr(pl, 0, b->len - (pl - b->p));
		if (!e) break;
		if (t - b->p - 2 > 0) {
			if (b->p[0] == 'P') send_publish(b->p[1] == '1', (char *)b->p + 2, pl, e - pl);
			else file_publish(b->p[1] == '1', (char *)b->p + 2, (char *)pl);
		}
		bdrop(b, e + 1 - b->p);
	}
	if (b->len > MAX_REC) { logf_("record too long, dropping"); b->len = 0; }
}

static void drain_child(void)
{
	unsigned char tmp[4096];
	long n;

	if (g_cpipe < 0) return;
	while ((n = read(g_cpipe, tmp, sizeof tmp)) > 0)
		if (bput(&g_cin, tmp, n, 2 * MAX_REC) < 0) { logf_("job output too big, dropping"); g_cin.len = 0; }
	parse_records(&g_cin);
	if (n == 0 || (n < 0 && errno != EAGAIN && errno != EINTR)) {	/* end of output */
		close(g_cpipe);
		g_cpipe = -1;
		g_cin.len = 0;
	}
}

static void reap(void)
{
	int st;
	pid_t p;

	g_chld = 0;
	while ((p = waitpid(-1, &st, WNOHANG)) > 0) {
		if (p != g_child) continue;
		drain_child();	/* whatever it wrote before it left */
		if (g_cpipe >= 0) { close(g_cpipe); g_cpipe = -1; }	/* a background child may keep the pipe open: not waited for */
		bfree(&g_cin);
		g_child = 0;
	}
}

/* ---- connection ---- */

static void conn_close(void)
{
	if (g_sock >= 0) close(g_sock);
	g_sock = -1;
	bfree(&g_in);
	bfree(&g_out);
}

static void schedule_retry(int was_up)
{
	long long t = now_ms();

	conn_close();
	g_state = DISC;
	if (was_up) {	/* a connection that lasted: start again quickly */
		g_failures = 0;
		g_backoff = C.bo_init;
		g_next_try = t + C.bo_init * 1000LL;
		return;
	}
	g_failures++;
	if (g_failures == 1 || g_failures % 5 == 0) {
		char m[120];

		logf_("MQTT connection failed (attempt %d, backoff %ds)", g_failures, g_backoff);
		snprintf(m, sizeof m, "MQTT connection failed (attempt %d, backoff %ds)", g_failures, g_backoff);
		queue_job(J_LOGEVENT, "error", m);
	}
	if (g_failures >= C.cb_thresh) {
		char m[160];

		logf_("MQTT circuit breaker tripped (%d consecutive failures) - pausing %ds", g_failures, C.cb_cool);
		snprintf(m, sizeof m, "MQTT circuit breaker tripped after %d failures; cooling down %ds", g_failures, C.cb_cool);
		queue_job(J_LOGEVENT, "critical", m);
		g_failures = 0;
		g_backoff = C.bo_init;
		g_next_try = t + C.cb_cool * 1000LL;
		return;
	}
	g_next_try = t + g_backoff * 1000LL;
	if (g_backoff < C.bo_max) {
		g_backoff *= C.bo_mul;
		if (g_backoff > C.bo_max) g_backoff = C.bo_max;
	}
}

/* the broker's address (audit M1: getaddrinfo, which can block for seconds on DNS, ran at every reconnection and froze
 * the loop): a numeric address needs no lookup; a name is resolved once, kept, and resolved again only after a
 * failed connection */
static struct sockaddr_in g_addr;
static int g_addr_ok;

static int broker_addr(void)
{
	struct addrinfo hints, *ai = NULL;

	if (g_addr_ok) return 0;
	memset(&g_addr, 0, sizeof g_addr);
	g_addr.sin_family = AF_INET;
	g_addr.sin_port = htons((unsigned short)atoi(C.port));
	if (inet_aton(C.host, &g_addr.sin_addr)) { g_addr_ok = 1; return 0; }
	memset(&hints, 0, sizeof hints);
	hints.ai_family = AF_INET;
	hints.ai_socktype = SOCK_STREAM;
	if (getaddrinfo(C.host, C.port, &hints, &ai) != 0 || !ai) return -1;
	memcpy(&g_addr, ai->ai_addr, sizeof g_addr);
	freeaddrinfo(ai);
	g_addr_ok = 1;
	return 0;
}

static void conn_start(void)
{
	int r, fl;

	if (broker_addr()) {
		status(0, 0, 0);
		schedule_retry(0);
		return;
	}
	g_sock = socket(AF_INET, SOCK_STREAM, 0);
	if (g_sock < 0) { status(0, 0, 0); schedule_retry(0); return; }
	fcntl(g_sock, F_SETFD, FD_CLOEXEC);
	fl = fcntl(g_sock, F_GETFL);
	fcntl(g_sock, F_SETFL, fl | O_NONBLOCK);
	r = 1;
	setsockopt(g_sock, IPPROTO_TCP, TCP_NODELAY, &r, sizeof r);
	r = connect(g_sock, (struct sockaddr *)&g_addr, sizeof g_addr);
	if (r < 0 && errno != EINPROGRESS) { g_addr_ok = 0; status(0, 0, 0); schedule_retry(0); return; }
	g_state = CONNECTING;
	g_deadline = now_ms() + CONNECT_TIMEOUT_MS;
}

static void on_connected(void)
{
	pkt_connect(&g_out);
	g_state = CONNACKWAIT;
	g_deadline = now_ms() + CONNECT_TIMEOUT_MS;
}

static void on_up(void)
{
	char t[200];
	long long n = now_ms();

	g_state = UP;
	pkt_subscribe(&g_out, C.cmd);
	snprintf(t, sizeof t, "%s/availability", C.root);
	pkt_publish(&g_out, 1, t, "online", 6, MAX_OUT);	/* paired with this session's Will */
	if (g_pend.len) { bput(&g_out, g_pend.p, g_pend.len, MAX_OUT); bfree(&g_pend); g_pend_warned = 0; }
	if (g_failures > 0) logf_("MQTT connection recovered after %d error(s)", g_failures);
	g_failures = 0;
	g_backoff = C.bo_init;
	g_next_ping = n + C.ping_s * 1000LL;
	g_pong_due = 0;
	status(1, 0, 0);
	logf_("MQTT connected host=%s:%s root=%s command topic=%s", C.host, C.port, C.root, C.cmd);
	if (!g_started) {	/* first connection of this run: manifest, discovery, start event, then health */
		g_started = 1;
		queue_job(J_STARTUP, NULL, NULL);
		queue_job(J_HEALTH, NULL, NULL);
		g_next_health = n + C.health_s * 1000LL;
	}
}

/* returns 0 to go on, -1 when the connection must be dropped */
static int on_packet(int type, int flags, const unsigned char *p, size_t rem)
{
	if (g_state == CONNACKWAIT) {
		if (type != 2 || rem != 2) return -1;
		if (p[1] == 0) { on_up(); return 0; }
		logf_("MQTT broker refused the connection (CONNACK %d)", p[1]);
		status(0, p[1] >= 1 && p[1] <= 5 ? p[1] : 0, 0);
		return -2;
	}
	switch (type) {
	case 3: {	/* PUBLISH: only QoS 0 can arrive (that is all we subscribed to) */
		size_t tl, pn;
		char pay[MAX_FRAME + 1];

		if (((flags >> 1) & 3) != 0 || rem < 2) return -1;
		tl = (p[0] << 8) | p[1];
		if (tl < 1 || 2 + tl > rem) return -1;
		pn = rem - 2 - tl;
		memcpy(pay, p + 2 + tl, pn);
		for (size_t i = 0; i < pn; i++) {
			if (pay[i] == 0) { logf_("MQTT command frame rejected (invalid or over 4 KiB)"); return -1; }
			if (pay[i] == '\r' || pay[i] == '\n') pay[i] = ' ';	/* one record per packet, also for pretty-printed JSON */
		}
		pay[pn] = 0;
		for (size_t i = 0; i < pn; i++)
			if (pay[i] != ' ' && pay[i] != '\t') { queue_job(J_COMMAND, pay, NULL); break; }
		return 0;
	}
	case 9:
		if (rem >= 3 && p[2] == 0x80) logf_("MQTT broker refused the subscription to %s", C.cmd);
		return 0;
	case 13:	/* PINGRESP */
		g_pong_due = 0;
		status(1, 0, 1);
		return 0;
	default:
		return 0;
	}
}

static int parse_in(void)
{
	while (g_in.len >= 2) {
		size_t i = 1, rem = 0, mult = 1;
		int d;

		do {
			if (i >= g_in.len) return 0;
			d = g_in.p[i++];
			rem += (d & 127) * mult;
			mult *= 128;
		} while ((d & 128) && i < 5);
		if ((d & 128) || rem > MAX_FRAME) { logf_("MQTT frame rejected (invalid or over 4 KiB)"); return -1; }
		if (g_in.len < i + rem) return 0;
		{
			int r = on_packet(g_in.p[0] >> 4, g_in.p[0] & 15, g_in.p + i, rem);

			if (r) return r;
		}
		bdrop(&g_in, i + rem);
	}
	return 0;
}

/* ---- start up ---- */

static void cfg_set(const char *k, const char *v)
{
	int n = atoi(v);

#define S(name, field) if (!strcmp(k, name)) { snprintf(C.field, sizeof C.field, "%s", v); return; }
#define I(name, field) if (!strcmp(k, name)) { C.field = n; return; }
	S("MQTT_HOST", host) S("MQTT_PORT", port) S("MQTT_USER", user) S("MQTT_PASSWORD", pass)
	S("MQTT_CLIENT_ID", cid) S("MQTT_TOPIC_ROOT", root) S("MQTT_TOPIC_COMMAND", cmd)
	I("MQTT_ENABLE", enable) I("MQTT_HEALTH_INTERVAL_SECONDS", health_s) I("MQTT_KEEPALIVE_PING_SECONDS", ping_s)
	I("MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS", bo_init) I("MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS", bo_max)
	I("MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER", bo_mul) I("MQTT_CIRCUIT_BREAKER_THRESHOLD", cb_thresh)
	I("MQTT_CIRCUIT_BREAKER_COOLDOWN_SECONDS", cb_cool)
#undef S
#undef I
}

/* `SCRIPT print-config`, up to 30 s (it may ping the usual Home Assistant names) */
static int load_config(void)
{
	char *argv[3] = { (char *)g_script, "print-config", NULL };
	struct buf o = { 0 };
	int fd, st, got = 0;
	pid_t pid;
	long long end = now_ms() + 30000;
	char *line, *nl;

	pid = spawn(argv, &fd, 1);
	if (pid < 0) return -1;
	while (!g_stop) {
		struct pollfd pf = { fd, POLLIN, 0 };
		unsigned char tmp[1024];
		long n;

		if (now_ms() > end) { kill(-pid, SIGKILL); break; }
		if (poll(&pf, 1, 500) <= 0) continue;
		n = read(fd, tmp, sizeof tmp);
		if (n > 0) { if (bput(&o, tmp, n, 16384) < 0) break; }
		else if (n == 0 || (errno != EAGAIN && errno != EINTR)) break;
	}
	close(fd);
	if (g_stop) kill(-pid, SIGKILL);
	waitpid(pid, &st, 0);
	if (!WIFEXITED(st) || WEXITSTATUS(st) != 0 || g_stop) { free(o.p); return -1; }
	bput(&o, "", 1, 16385);
	for (line = (char *)o.p; line && *line; line = nl ? nl + 1 : NULL) {
		char *eq;

		nl = strchr(line, '\n');
		if (nl) *nl = 0;
		eq = strchr(line, '=');
		if (!eq) continue;
		*eq = 0;
		cfg_set(line, eq + 1);
		got++;
	}
	free(o.p);
	return got ? 0 : -1;
}

static void sig_handler(int s)
{
	if (s == SIGCHLD) g_chld = 1; else g_stop = 1;
	if (write(g_sigpipe[1], "x", 1) < 0) { /* the pipe is full: the loop wakes up anyway */ }
}

static void shutdown_now(void)
{
	char t[200];
	long long end = now_ms() + 1500;

	if (g_child > 0) kill(-g_child, SIGKILL);
	if (g_state == UP) {	/* a clean DISCONNECT does not fire the Will: say offline ourselves */
		snprintf(t, sizeof t, "%s/availability", C.root);
		pkt_publish(&g_out, 1, t, "offline", 7, MAX_OUT);
		bput(&g_out, "\xe0\x00", 2, MAX_OUT);
		while (g_out.len && now_ms() < end) {
			struct pollfd pf = { g_sock, POLLOUT, 0 };
			long n;

			if (poll(&pf, 1, 200) <= 0) continue;
			n = send(g_sock, g_out.p, g_out.len, MSG_NOSIGNAL);
			if (n > 0) bdrop(&g_out, n); else if (n < 0 && errno != EAGAIN && errno != EINTR) break;
		}
	}
	logf_("MQTT bridge stopping");
	conn_close();
	unlink(g_fifo);
	unlink(g_pidfile);
}

static void write_pidfile(void)
{
	char s[24];
	int f = open(g_pidfile, O_WRONLY | O_CREAT | O_TRUNC, 0644);

	if (f < 0) return;
	if (write(f, s, snprintf(s, sizeof s, "%d\n", (int)getpid())) < 0) { /* nothing to do */ }
	close(f);
}

int main(int argc, char **argv)
{
	struct sigaction sa;

	/* by hand: no getopt/optarg/stderr (data imports do not survive the stand-in libc of the Makefile) */
	for (int i = 1; i < argc; i += 2) {
		const char **dst = NULL;

		if (argv[i][0] == '-' && argv[i][1] && !argv[i][2] && i + 1 < argc) {
			switch (argv[i][1]) {
			case 's': dst = &g_script; break;
			case 'l': dst = &g_log; break;
			case 't': dst = &g_status; break;
			case 'f': dst = &g_fifo; break;
			case 'p': dst = &g_pidfile; break;
			}
		}
		if (!dst) {
			static const char u[] = "usage: tc100-mqttd [-s SCRIPT] [-l LOG] [-t STATUS] [-f FIFO] [-p PIDFILE]\n";

			if (write(2, u, sizeof u - 1) < 0) { /* nothing to do */ }
			return 2;
		}
		*dst = argv[i + 1];
	}
	C.health_s = 300; C.ping_s = 30; C.bo_init = 2; C.bo_max = 20; C.bo_mul = 2; C.cb_thresh = 50; C.cb_cool = 300;
	if (pipe(g_sigpipe) < 0) return 1;
	fcntl(g_sigpipe[0], F_SETFL, O_NONBLOCK);
	fcntl(g_sigpipe[1], F_SETFL, O_NONBLOCK);
	memset(&sa, 0, sizeof sa);
	sa.sa_handler = sig_handler;
	sigaction(SIGTERM, &sa, NULL);
	sigaction(SIGINT, &sa, NULL);
	sigaction(SIGCHLD, &sa, NULL);
	signal(SIGPIPE, SIG_IGN);
	signal(SIGHUP, SIG_IGN);

	if (load_config() < 0) {
		if (g_stop) return 0;
		logf_("cannot read the MQTT settings from %s print-config", g_script);
		return 1;
	}
	if (!C.enable) { logf_("MQTT bridge disabled in config"); return 0; }
	if (!*C.host || !*C.cid || !*C.root || !*C.cmd) { logf_("MQTT settings incomplete (host, client id, topics)"); return 1; }
	if (C.health_s < 10) C.health_s = 10;
	if (C.ping_s < 5 || C.ping_s > 55) C.ping_s = 30;
	if (C.bo_init < 1) C.bo_init = 1;
	if (C.bo_max < C.bo_init) C.bo_max = C.bo_init;
	if (C.bo_mul < 1) C.bo_mul = 1;
	if (C.cb_thresh < 1) C.cb_thresh = 50;
	if (C.cb_cool < 1) C.cb_cool = 300;
	g_backoff = C.bo_init;

	unlink(g_fifo);
	if (mkfifo(g_fifo, 0600) == 0) g_fifofd = open(g_fifo, O_RDWR | O_NONBLOCK | O_CLOEXEC);
	if (g_fifofd < 0) logf_("cannot create %s: other scripts will publish over their own connections", g_fifo);
	write_pidfile();
	logf_("MQTT bridge started (tc100-mqttd) host=%s:%s root=%s", C.host, C.port, C.root);
	queue_job(J_LOGEVENT, "info", "MQTT bridge started");

	for (;;) {
		struct pollfd pf[4];
		int np = 0, isig, ifif = -1, isock = -1, ich = -1;
		long long t = now_ms(), wake = t + 1000;

		if (g_stop) break;
		if (g_chld) reap();

		/* timers */
		if (g_state == DISC && t >= g_next_try) conn_start();
		if ((g_state == CONNECTING || g_state == CONNACKWAIT) && t >= g_deadline) {
			if (g_state == CONNECTING) g_addr_ok = 0;	/* no answer from that address: a name is resolved again */
			status(0, 0, 0);
			schedule_retry(0);
		}
		if (g_state == UP) {
			if (t >= g_next_ping) {
				bput(&g_out, "\xc0\x00", 2, MAX_OUT);
				g_next_ping = t + C.ping_s * 1000LL;
				if (!g_pong_due) g_pong_due = t + PONG_TIMEOUT_MS;
			}
			if (g_pong_due && t >= g_pong_due) {
				logf_("MQTT broker does not answer: connection dropped");
				status(0, 0, 0);
				schedule_retry(1);
			}
			if (g_state == UP && t >= g_next_health) {
				queue_job(J_HEALTH, NULL, NULL);
				g_next_health = t + C.health_s * 1000LL;
			}
		}
		if (g_child && t >= g_child_deadline) {
			logf_("job timed out: killed");
			kill(-g_child, SIGKILL);
			g_child_deadline = t + 60000;	/* reap() finishes it */
		}
		/* jobs need the connection, except the log lines */
		if (!g_child && g_qn && (g_state == UP || g_q[0].kind == J_LOGEVENT)) start_job();

		if (g_state == DISC && g_next_try < wake) wake = g_next_try;
		if (g_state == UP && g_next_ping < wake) wake = g_next_ping;
		if (g_state == UP && g_next_health < wake) wake = g_next_health;
		pf[np].fd = g_sigpipe[0]; pf[np].events = POLLIN; isig = np++;
		if (g_fifofd >= 0) { pf[np].fd = g_fifofd; pf[np].events = POLLIN; ifif = np++; }
		if (g_sock >= 0) {
			pf[np].fd = g_sock;
			pf[np].events = POLLIN | ((g_state == CONNECTING || g_out.len) ? POLLOUT : 0);
			isock = np++;
		}
		if (g_cpipe >= 0) { pf[np].fd = g_cpipe; pf[np].events = POLLIN; ich = np++; }
		if (wake < t) wake = t;
		if (poll(pf, np, (int)(wake - t)) < 0 && errno != EINTR) continue;

		if (pf[isig].revents) {
			char junk[32];

			while (read(g_sigpipe[0], junk, sizeof junk) > 0) { }
		}
		if (ifif >= 0 && (pf[ifif].revents & POLLIN)) {
			unsigned char tmp[4096];
			long n = read(g_fifofd, tmp, sizeof tmp);

			if (n > 0 && bput(&g_fin, tmp, n, 2 * MAX_REC) < 0) { logf_("FIFO input too big, dropping"); g_fin.len = 0; }
			parse_records(&g_fin);
			if (!g_fin.len) bfree(&g_fin);
		}
		if (ich >= 0 && (pf[ich].revents & (POLLIN | POLLHUP))) drain_child();
		if (isock >= 0 && g_sock >= 0) {
			int re = pf[isock].revents;

			if (g_state == CONNECTING && (re & (POLLOUT | POLLERR | POLLHUP))) {
				int e = 0;
				socklen_t l = sizeof e;

				getsockopt(g_sock, SOL_SOCKET, SO_ERROR, &e, &l);
				if (e) { g_addr_ok = 0; status(0, 0, 0); schedule_retry(0); }
				else on_connected();
			}
			if (g_sock >= 0 && (re & POLLIN)) {
				unsigned char tmp[2048];
				long n = recv(g_sock, tmp, sizeof tmp, 0);
				int was_up = g_state == UP;

				if (n > 0) {
					int r;

					bput(&g_in, tmp, n, 8 * MAX_FRAME);
					r = parse_in();
					if (r == -2) { schedule_retry(0); }	/* refused: the status says why */
					else if (r < 0) {
						if (was_up) { status(0, 0, 0); logf_("MQTT connection lost"); }
						schedule_retry(was_up);
					}
				} else if (n == 0 || (errno != EAGAIN && errno != EINTR)) {
					if (was_up) { status(0, 0, 0); logf_("MQTT connection lost"); }
					else status(0, 0, 0);
					schedule_retry(was_up);
				}
			}
			if (g_sock >= 0 && g_out.len && g_state != CONNECTING) {
				long n = send(g_sock, g_out.p, g_out.len, MSG_NOSIGNAL);

				if (n > 0) { bdrop(&g_out, n); if (g_state == UP) status(1, 0, 1); }
				else if (n < 0 && errno != EAGAIN && errno != EINTR) {
					int was_up = g_state == UP;

					if (was_up) { status(0, 0, 0); logf_("MQTT connection lost"); }
					schedule_retry(was_up);
				}
				if (!g_out.len && g_out.cap > 65536) bfree(&g_out);
			}
		}
	}
	shutdown_now();
	return 0;
}
