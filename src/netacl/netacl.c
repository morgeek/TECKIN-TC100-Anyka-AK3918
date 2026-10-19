/*
 * netacl.c — which addresses may connect to the camera's servers.
 *
 * Loaded with LD_PRELOAD into lighttpd, telnetd and the FTP server
 * (lib/libnetacl.so), and built into libtc100fix.so for the video process
 * (both RTSP servers). The kernel has no packet filter (no iptables), so the
 * check is done where connections are accepted:
 *
 *   TC100_NET_ALLOW="10.0.0.0/8 192.168.0.0/16 ..."
 *       accept()/accept4() close a connection from an IPv4 address outside
 *       these networks at once, and return -1 with errno ECONNABORTED (the
 *       error a connection reset before accept gives: servers just go on).
 *       Not set, empty or without one valid network: everything is allowed,
 *       so a mistake in the list can never lock the camera's owner out.
 *       127.0.0.0/8 is always allowed. Non-IPv4 sockets are not checked.
 *   TC100_NET_LOCAL_PORTS="8555"
 *       bind() of an IPv4 socket to one of these ports binds it to 127.0.0.1
 *       instead of every address: only the camera itself can reach it.
 *   TC100_NET_STATUS=/var/run/netacl.<name>
 *       on each refusal: "refused=N last=a.b.c.d time=unix".
 *
 * The standalone library removes LD_PRELOAD from its own environment once
 * loaded, so the processes these servers start (CGI scripts, shells) do not
 * load it again.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <netinet/in.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include "netacl.h"

#define NETACL_MAX 32
#define PORTS_MAX 8

static int n_nets = -1;                       /* -1: not read yet; 0: allow all */
static uint32_t net_addr[NETACL_MAX], net_mask[NETACL_MAX];
static int n_ports = -1;
static unsigned short local_ports[PORTS_MAX];
static unsigned long refused;

static int parse_net(const char *s, uint32_t *addr, uint32_t *mask)
{
    char b[32], *slash;
    int bits = 32;
    struct in_addr ia;
    if (strlen(s) >= sizeof(b)) return -1;
    strcpy(b, s);
    if ((slash = strchr(b, '/'))) {
        char *end;
        long v;
        *slash = 0;
        v = strtol(slash + 1, &end, 10);
        if (!slash[1] || *end || v < 0 || v > 32) return -1;
        bits = (int)v;
    }
    if (inet_pton(AF_INET, b, &ia) != 1) return -1;
    *mask = bits ? htonl(0xffffffffu << (32 - bits)) : 0;
    *addr = ia.s_addr & *mask;
    return 0;
}

static void load(void)
{
    const char *e;
    char buf[1024], *tok, *save = NULL;
    int n = 0;
    if (n_nets >= 0) return;
    e = getenv("TC100_NET_ALLOW");
    if (e && strlen(e) < sizeof(buf)) {
        strcpy(buf, e);
        for (tok = strtok_r(buf, " ,\t", &save); tok && n < NETACL_MAX; tok = strtok_r(NULL, " ,\t", &save))
            if (parse_net(tok, &net_addr[n], &net_mask[n]) == 0) n++;
    }
    n_nets = n;
    n = 0;
    e = getenv("TC100_NET_LOCAL_PORTS");
    if (e && strlen(e) < sizeof(buf)) {
        strcpy(buf, e);
        save = NULL;
        for (tok = strtok_r(buf, " ,\t", &save); tok && n < PORTS_MAX; tok = strtok_r(NULL, " ,\t", &save)) {
            char *end;
            long v = strtol(tok, &end, 10);
            if (!*end && v > 0 && v < 65536) local_ports[n++] = (unsigned short)v;
        }
    }
    n_ports = n;
}

int netacl_is_private(uint32_t a)
{
    uint32_t h = ntohl(a);
    return (h >> 24) == 10 || (h >> 24) == 127 || (h >> 20) == 0xac1 || (h >> 16) == 0xc0a8 ||
           (h >> 16) == 0xa9fe || (h >> 22) == (0x64400000u >> 22);
}

int netacl_allowed(uint32_t a)
{
    int i;
    load();
    if (n_nets == 0 || (ntohl(a) >> 24) == 127) return 1;
    for (i = 0; i < n_nets; i++)
        if ((a & net_mask[i]) == net_addr[i]) return 1;
    return 0;
}

static void note_refusal(uint32_t a)
{
    const char *path = getenv("TC100_NET_STATUS");
    char ip[INET_ADDRSTRLEN], tmp[256];
    FILE *f;
    refused++;
    if (!path || !path[0] || strlen(path) > 200) return;
    inet_ntop(AF_INET, &a, ip, sizeof(ip));
    snprintf(tmp, sizeof(tmp), "%s.tmp", path);
    if (!(f = fopen(tmp, "w"))) return;
    fprintf(f, "refused=%lu last=%s time=%ld\n", refused, ip, (long)time(NULL));
    fclose(f);
    rename(tmp, path);
}

/* 1: keep the connection (address copied to the caller), 0: closed. */
static int check(int fd, const struct sockaddr_storage *ss, socklen_t sl, struct sockaddr *addr, socklen_t *len)
{
    if (ss->ss_family == AF_INET) {
        uint32_t a = ((const struct sockaddr_in *)ss)->sin_addr.s_addr;
        if (!netacl_allowed(a)) {
            close(fd);
            note_refusal(a);
            return 0;
        }
    }
    if (addr && len) {
        socklen_t c = *len < sl ? *len : sl;
        memcpy(addr, ss, c);
        *len = sl;
    }
    return 1;
}

int accept(int s, struct sockaddr *addr, socklen_t *len)
{
    static int (*real)(int, struct sockaddr *, socklen_t *);
    struct sockaddr_storage ss;
    socklen_t sl = sizeof(ss);
    int fd;
    if (!real) real = (int (*)(int, struct sockaddr *, socklen_t *))dlsym(RTLD_NEXT, "accept");
    if (!real) { errno = ENOSYS; return -1; }
    memset(&ss, 0, sizeof(ss));
    fd = real(s, (struct sockaddr *)&ss, &sl);
    if (fd < 0) return fd;
    if (!check(fd, &ss, sl, addr, len)) { errno = ECONNABORTED; return -1; }
    return fd;
}

int accept4(int s, struct sockaddr *addr, socklen_t *len, int flags)
{
    static int (*real)(int, struct sockaddr *, socklen_t *, int);
    struct sockaddr_storage ss;
    socklen_t sl = sizeof(ss);
    int fd;
    if (!real) real = (int (*)(int, struct sockaddr *, socklen_t *, int))dlsym(RTLD_NEXT, "accept4");
    if (!real) { errno = ENOSYS; return -1; }
    memset(&ss, 0, sizeof(ss));
    fd = real(s, (struct sockaddr *)&ss, &sl, flags);
    if (fd < 0) return fd;
    if (!check(fd, &ss, sl, addr, len)) { errno = ECONNABORTED; return -1; }
    return fd;
}

int bind(int s, const struct sockaddr *addr, socklen_t len)
{
    static int (*real)(int, const struct sockaddr *, socklen_t);
    if (!real) real = (int (*)(int, const struct sockaddr *, socklen_t))dlsym(RTLD_NEXT, "bind");
    if (!real) { errno = ENOSYS; return -1; }
    load();
    if (n_ports > 0 && addr && addr->sa_family == AF_INET && len >= (socklen_t)sizeof(struct sockaddr_in)) {
        struct sockaddr_in a;
        int i;
        memcpy(&a, addr, sizeof(a));
        for (i = 0; i < n_ports; i++)
            if (ntohs(a.sin_port) == local_ports[i] && a.sin_addr.s_addr == htonl(INADDR_ANY)) {
                a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
                return real(s, (const struct sockaddr *)&a, sizeof(a));
            }
    }
    return real(s, addr, len);
}

#ifndef NETACL_IN_TC100FIX
__attribute__((constructor)) static void netacl_init(void)
{
    load();
    unsetenv("LD_PRELOAD");
}
#endif
