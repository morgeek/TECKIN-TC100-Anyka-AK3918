/*
 * tc100-logfwd — sends the camera's local log to a remote syslog server,
 * filtered and rate-limited.
 *
 * Why not "syslogd -R": BusyBox syslogd sends every message it receives to
 * the remote host *before* its own filters (sysklogd/syslogd.c, 1.35: the
 * -l level and the -f rules only apply to the local file). The remote server
 * therefore got kernel and daemon info/debug lines too, and repeated bursts
 * (the ISP driver during a day/night switch) arrived line by line. Here
 * syslogd only writes the local file (notice and above + logins) and this
 * program follows that file:
 *
 *   - forwards a line when its level is <= -l (default 5, notice) or its
 *     facility is auth/authpriv (logins);
 *   - the same message (digits ignored, so "sjf:4619178" and "sjf:4619188"
 *     count as one) is sent at most once per -w seconds (default 60); the
 *     number of repeats is sent once the window is over:
 *       "tc100-logfwd: last message repeated 7 times in 60 s: <text>";
 *   - at most -m lines per minute in total (default 60); beyond that lines
 *     are counted and reported in one line when the minute is over.
 *
 * The file is followed with inotify (no wakeups while the log is quiet),
 * with a 2 s poll as fallback. Rotation by syslogd (messages -> messages.0)
 * is handled: the rest of the old file is read, then the new one from its
 * start.
 *
 * Usage: tc100-logfwd -r HOST[:PORT] [-f /var/log/messages] [-l 5] [-w 60]
 *                     [-m 60] [-b]      (-b: start at the beginning of the file)
 *
 * Messages go out as RFC 3164: "<PRI>Mmm dd hh:mm:ss host tag: text", with
 * the timestamp and host of the local line.
 */
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/inotify.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define LINE_MAX_LEN 1024
#define SLOTS 64

static const char *g_path = "/var/log/messages";
static char g_host[256];
static char g_port[16] = "514";
static int g_maxlvl = 5, g_window = 60, g_rate = 60;
static int g_sock = -1;
static time_t g_resolve_after;

static struct slot {
    unsigned hash;
    time_t sent;          /* last time this message went out */
    int repeats;          /* suppressed since then */
    int pri;
    char stamp[16], host[64], text[120];
} g_slots[SLOTS];

static time_t g_rate_start;
static int g_rate_count, g_rate_dropped;

static time_t now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec;
}

static void resolve(void)
{
    struct addrinfo hints, *res = NULL;
    time_t t = now_s();
    if (g_sock >= 0 || t < g_resolve_after) return;
    g_resolve_after = t + 60;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_DGRAM;
    if (getaddrinfo(g_host, g_port, &hints, &res) != 0 || !res) return;
    g_sock = socket(res->ai_family, SOCK_DGRAM, 0);
    if (g_sock >= 0 && connect(g_sock, res->ai_addr, res->ai_addrlen) != 0) {
        close(g_sock); g_sock = -1;
    }
    if (g_sock >= 0) fcntl(g_sock, F_SETFD, FD_CLOEXEC);
    freeaddrinfo(res);
}

static void send_raw(int pri, const char *stamp, const char *host, const char *fmt, ...)
{
    char buf[LINE_MAX_LEN + 128];
    int n = snprintf(buf, sizeof(buf), "<%d>%s %s ", pri, stamp, host);
    va_list ap;
    if (n < 0 || n >= (int)sizeof(buf)) return;
    va_start(ap, fmt);
    vsnprintf(buf + n, sizeof(buf) - n, fmt, ap);
    va_end(ap);
    resolve();
    if (g_sock < 0) return;
    if (send(g_sock, buf, strlen(buf), MSG_DONTWAIT | MSG_NOSIGNAL) < 0 &&
        (errno == ECONNREFUSED || errno == ENETUNREACH || errno == EHOSTUNREACH || errno == ENOTCONN)) {
        /* ICMP errors are reported on the next send: try again later, the
         * address may have changed (DHCP). */
        close(g_sock); g_sock = -1;
    }
}

static char g_last_stamp[16] = "Jan  1 00:00:00", g_last_host[64] = "camera";

/* A new minute: report what the rate limit dropped in the last one. */
static void rate_tick(time_t t)
{
    if (t - g_rate_start < 60) return;
    if (g_rate_dropped)
        send_raw(13 /* user.notice */, g_last_stamp, g_last_host,
                 "tc100-logfwd: %d lines not forwarded in the last minute (more than %d)",
                 g_rate_dropped, g_rate);
    g_rate_start = t; g_rate_count = 0; g_rate_dropped = 0;
}

/* Rate limit: 1 = send, 0 = counted and dropped. */
static int rate_ok(time_t t, const char *stamp, const char *host)
{
    rate_tick(t);
    snprintf(g_last_stamp, sizeof(g_last_stamp), "%s", stamp);
    snprintf(g_last_host, sizeof(g_last_host), "%s", host);
    if (g_rate_count >= g_rate) { g_rate_dropped++; return 0; }
    g_rate_count++;
    return 1;
}

static const char *const FAC[] = { "kern", "user", "mail", "daemon", "auth", "syslog", "lpr", "news",
    "uucp", "cron", "authpriv", "ftp", NULL, NULL, NULL, NULL,
    "local0", "local1", "local2", "local3", "local4", "local5", "local6", "local7" };
static const char *const LVL[] = { "emerg", "alert", "crit", "err", "warn", "notice", "info", "debug" };

static int parse_pri(const char *fl, int *fac, int *lvl)
{
    const char *dot = strchr(fl, '.');
    size_t i, fn;
    if (!dot) return -1;
    fn = (size_t)(dot - fl);
    *fac = -1; *lvl = -1;
    for (i = 0; i < sizeof(FAC) / sizeof(FAC[0]); i++)
        if (FAC[i] && strlen(FAC[i]) == fn && !strncmp(FAC[i], fl, fn)) { *fac = (int)i; break; }
    for (i = 0; i < 8; i++)
        if (!strcmp(LVL[i], dot + 1)) { *lvl = (int)i; break; }
    if (*lvl < 0 && !strcmp(dot + 1, "warning")) *lvl = 4;
    if (*lvl < 0 && !strcmp(dot + 1, "error")) *lvl = 3;
    return (*fac >= 0 && *lvl >= 0) ? 0 : -1;
}

static unsigned msg_hash(int pri, const char *s)
{
    unsigned h = 2166136261u ^ (unsigned)pri;
    int in_digits = 0;
    for (; *s; s++) {
        unsigned char c = (unsigned char)*s;
        if (isdigit(c)) { if (in_digits) continue; in_digits = 1; c = '#'; }
        else in_digits = 0;
        h = (h ^ c) * 16777619u;
    }
    return h;
}

static void flush_repeats(time_t t, int all)
{
    int i;
    for (i = 0; i < SLOTS; i++) {
        struct slot *s = &g_slots[i];
        if (!s->hash || !s->repeats) continue;
        if (!all && t - s->sent < g_window) continue;
        send_raw(s->pri, s->stamp, s->host, "tc100-logfwd: last message repeated %d times in %d s: %s",
                 s->repeats, (int)(t - s->sent), s->text);
        s->repeats = 0;
        s->sent = t;
    }
}

/* One line of the local file: "Mmm dd hh:mm:ss host fac.lvl text". */
static void handle_line(char *line)
{
    char stamp[16], host[64], fl[24];
    const char *text;
    char *p;
    int fac, lvl, pri, i, free_i = -1, old_i = 0;
    unsigned h;
    time_t t = now_s();
    struct slot *s;

    if (strlen(line) < 20 || line[3] != ' ' || line[6] != ' ' || line[15] != ' ') return;
    memcpy(stamp, line, 15); stamp[15] = 0;
    p = line + 16;
    if (sscanf(p, "%63s %23s", host, fl) != 2) return;
    text = p;                                   /* skip "host fac.lvl " */
    while (*text == ' ') text++;
    text += strlen(host);
    while (*text == ' ') text++;
    text += strlen(fl);
    while (*text == ' ') text++;
    if (parse_pri(fl, &fac, &lvl) != 0) return;
    if (lvl > g_maxlvl && fac != 4 && fac != 10) return;
    pri = fac * 8 + lvl;

    h = msg_hash(pri, text);
    if (!h) h = 1;
    for (i = 0; i < SLOTS; i++) {
        s = &g_slots[i];
        if (s->hash == h) {
            if (t - s->sent < g_window) { s->repeats++; return; }
            if (s->repeats) flush_repeats(t, 0);
            break;
        }
        if (!s->hash) { if (free_i < 0) free_i = i; }
        else if (g_slots[i].sent < g_slots[old_i].sent) old_i = i;
    }
    if (i == SLOTS) {
        i = free_i >= 0 ? free_i : old_i;
        s = &g_slots[i];
        if (s->hash && s->repeats)
            send_raw(s->pri, s->stamp, s->host, "tc100-logfwd: last message repeated %d times in %d s: %s",
                     s->repeats, (int)(t - s->sent), s->text);
        memset(s, 0, sizeof(*s));
        s->hash = h;
    }
    s = &g_slots[i];
    s->sent = t; s->repeats = 0; s->pri = pri;
    snprintf(s->stamp, sizeof(s->stamp), "%s", stamp);
    snprintf(s->host, sizeof(s->host), "%s", host);
    snprintf(s->text, sizeof(s->text), "%s", text);
    if (!rate_ok(t, stamp, host)) return;
    send_raw(pri, stamp, host, "%s", text);
}

/* Read complete lines from fd; keeps a partial last line for the next call. */
static char g_buf[LINE_MAX_LEN];
static size_t g_len;

static void drain(int fd)
{
    for (;;) {
        ssize_t n = read(fd, g_buf + g_len, sizeof(g_buf) - 1 - g_len);
        char *start, *nl;
        if (n <= 0) return;
        g_len += (size_t)n;
        g_buf[g_len] = 0;
        start = g_buf;
        while ((nl = memchr(start, '\n', g_len - (size_t)(start - g_buf)))) {
            *nl = 0;
            handle_line(start);
            start = nl + 1;
        }
        g_len -= (size_t)(start - g_buf);
        memmove(g_buf, start, g_len);
        if (g_len == sizeof(g_buf) - 1) g_len = 0;   /* overlong line: drop it */
    }
}

static volatile sig_atomic_t g_stop;
static void on_term(int sig) { (void)sig; g_stop = 1; }

int main(int argc, char **argv)
{
    int opt, fd = -1, ino = -1, wd = -1, from_start = 0;
    struct stat st;
    ino_t cur_ino = 0;
    char *colon;

    while ((opt = getopt(argc, argv, "r:f:l:w:m:b")) != -1) {
        switch (opt) {
        case 'r':
            snprintf(g_host, sizeof(g_host), "%s", optarg);
            if ((colon = strrchr(g_host, ':'))) { *colon = 0; snprintf(g_port, sizeof(g_port), "%s", colon + 1); }
            break;
        case 'f': g_path = optarg; break;
        case 'l': g_maxlvl = atoi(optarg); break;
        case 'w': g_window = atoi(optarg); break;
        case 'm': g_rate = atoi(optarg); break;
        case 'b': from_start = 1; break;
        default:
            fprintf(stderr, "usage: %s -r HOST[:PORT] [-f file] [-l 5] [-w 60] [-m 60] [-b]\n", argv[0]);
            return 2;
        }
    }
    if (!g_host[0]) { fprintf(stderr, "%s: -r HOST[:PORT] is required\n", argv[0]); return 2; }
    if (g_window < 1) g_window = 1;
    if (g_rate < 1) g_rate = 1;
    signal(SIGTERM, on_term); signal(SIGINT, on_term); signal(SIGPIPE, SIG_IGN);
    g_rate_start = now_s();

    ino = inotify_init();
    if (ino >= 0) fcntl(ino, F_SETFD, FD_CLOEXEC);

    while (!g_stop) {
        struct timeval tv;
        fd_set rf;
        int r;

        /* (Re)open the file when it appears or was replaced (rotation). */
        if (stat(g_path, &st) == 0 && (fd < 0 || st.st_ino != cur_ino)) {
            if (fd >= 0) { drain(fd); close(fd); g_len = 0; }
            fd = open(g_path, O_RDONLY);   /* uClibc 0.9.33: no O_CLOEXEC */
            if (fd >= 0) {
                fcntl(fd, F_SETFD, FD_CLOEXEC);
                cur_ino = st.st_ino;
                if (!from_start) lseek(fd, 0, SEEK_END);
                from_start = 1;          /* a new file after rotation: read it all */
                if (ino >= 0) {
                    if (wd >= 0) inotify_rm_watch(ino, wd);
                    wd = inotify_add_watch(ino, g_path, IN_MODIFY | IN_MOVE_SELF | IN_DELETE_SELF | IN_ATTRIB);
                }
            }
        } else if (fd >= 0 && fstat(fd, &st) == 0 && st.st_size < lseek(fd, 0, SEEK_CUR)) {
            lseek(fd, 0, SEEK_SET);      /* truncated in place */
            g_len = 0;
        }
        if (fd >= 0) drain(fd);
        flush_repeats(now_s(), 0);
        rate_tick(now_s());

        /* Sleep until the file changes, or for the next repeat summary. */
        tv.tv_sec = (ino >= 0 && wd >= 0) ? g_window : 2;
        tv.tv_usec = 0;
        FD_ZERO(&rf);
        if (ino >= 0 && wd >= 0) FD_SET(ino, &rf);
        r = select(ino >= 0 && wd >= 0 ? ino + 1 : 0, &rf, NULL, NULL, &tv);
        if (r > 0 && FD_ISSET(ino, &rf)) {
            char ev[512];
            ssize_t n = read(ino, ev, sizeof(ev));
            (void)n;
            if (n > 0) {
                ssize_t off = 0;
                int moved = 0;
                while (off + (ssize_t)sizeof(struct inotify_event) <= n) {
                    struct inotify_event *e = (struct inotify_event *)(ev + off);
                    if (e->mask & (IN_MOVE_SELF | IN_DELETE_SELF | IN_IGNORED)) moved = 1;
                    off += (ssize_t)sizeof(struct inotify_event) + e->len;
                }
                /* Moved or deleted: poll every 2 s until the new file is
                 * there (picked up by the stat at the top of the loop). */
                if (moved) { if (wd >= 0) inotify_rm_watch(ino, wd); wd = -1; }
            }
        } else if (r < 0 && errno != EINTR) {
            sleep(2);
        }
    }
    flush_repeats(now_s(), 1);
    return 0;
}
