/* status.h: the status line (GET /cgi-bin/statusline.cgi) answered by httpfront itself (item 55, boot.conf
 * HTTPFRONT_NATIVE=1 -> TC100_NATIVE_STATUS=1). Included by httpfront.c (freestanding: raw system calls, no division
 * helper of libgcc: udiv() below).
 *
 * It is a port of statusline_json() of www/cgi-bin/statelib.cgi and of scripts/wifi-signal.sh, field by field, with the
 * same files, the same caches (/tmp/state_usage.cache, state_cpu_usage.state, state_perfprofile.cache, state_pwd.cache:
 * shared with the CGI, same format) and the same quirks of the shell (a last line without newline is ignored by
 * `while read`, `read -r` trims blanks, ...). tests/test_httpfront_native.py compares it with the CGI key by key.
 * The rule: it answers only when it gives the exact answer of the CGI. Whatever it cannot reproduce makes it return 0
 * and the request goes to busybox httpd as before (st_bail): a value holding a backslash (busybox `echo` would turn it
 * into an escape), a number the shell would reject, a line longer than the buffer, a missing or empty
 * /tmp/csrf_token (the CGI creates it), an unreadable /proc file.
 * Test hook: TC100_STATUS_ROOT is put before every path (/proc, /tmp, /mnt, /var/run). */
#ifndef HF_STATUS_H
#define HF_STATUS_H

#pragma GCC push_options
#pragma GCC target("thumb")
typedef unsigned long long u64;
typedef long long s64;

#define SYS_statfs64 266
#define O_RDONLY 0

static int st_bail;
static const char *st_root = "";
static char st_pb[200];
#define SO0 192			/* room before the body for the response header */
static char so[4096 + SO0];
static int sl;

static const char *P(const char *p)
{
	int l = 0;

	cat(st_pb, &l, sizeof st_pb - 1, st_root);
	cat(st_pb, &l, sizeof st_pb - 1, p);
	st_pb[l] = 0;
	return st_pb;
}

static u64 urem;	/* remainder of the last udiv() */

/* udiv and mulu are ARM code, not Thumb, and their loops carry an empty asm barrier: gcc 15 (the CI runner's
 * Ubuntu 26.04) recognised the shift-and-add loop of mulu as a 64-bit multiply and, in Thumb, called __aeabi_lmul of
 * libgcc, which this freestanding program does not link (the release build of c392315 failed); in ARM mode a 64-bit
 * multiply is inline (umull), and the barrier keeps the loops as written whatever the compiler */
__attribute__((noinline, target("arm"))) static u64 udiv(u64 n, u64 d)	/* shift and subtract (no libgcc) */
{
	u64 q = 0, r = 0;

	if (!d) { urem = 0; return 0; }
	for (int i = 0; i < 64; i++) {
		r = r << 1 | n >> 63;
		n <<= 1;
		q <<= 1;
		if (r >= d) { r -= d; q |= 1; }
		__asm__ volatile ("" : "+r"(q));
	}
	urem = r;
	return q;
}

__attribute__((noinline, target("arm"))) static u64 mulu(u64 a, u32 b)	/* a * b without libgcc's 64-bit multiply */
{
	u64 r = 0;

	while (b) { if (b & 1) r += a; a <<= 1; b >>= 1; __asm__ volatile ("" : "+r"(r)); }
	return r;
}

/* ---- numbers and words */
static int isdig(const char *s, int l)
{
	if (l <= 0) return 0;
	for (int i = 0; i < l; i++) if (s[i] < '0' || s[i] > '9') return 0;
	return 1;
}

/* a number the shell would compute and print as it is (no overflow, no leading zero), else the request falls through */
static u64 pnum(const char *s)
{
	u64 n = 0;
	int l = slen(s);

	if (!isdig(s, l) || l > 18 || (l > 1 && s[0] == '0')) { st_bail = __LINE__; return 0; }
	for (int i = 0; i < l; i++) n = mulu(n, 10) + (u64)(s[i] - '0');
	return n;
}

static int blank(char c) { return c == ' ' || c == '\t'; }

/* read -r a b ...: the next word of a NUL-terminated line, "" when there is none */
static char *tok(char **p)
{
	char *s = *p, *e;

	while (blank(*s)) s++;
	e = s;
	while (*e && !blank(*e)) e++;
	if (*e) *e++ = 0;
	*p = e;
	return s;
}

/* the last variable of read -r: the rest of the line without trailing blanks */
static char *rest(char **p)
{
	char *s = *p, *e;

	while (blank(*s)) s++;
	e = s + slen(s);
	while (e > s && blank(e[-1])) e--;
	*e = 0;
	*p = e;
	return s;
}

/* ---- line reader: `while read -r` over a file. A line longer than the buffer is cut (cut=1) */
struct lr { long fd; int n, p, eof, cut; char b[1536]; };

static int lr_open(struct lr *r, const char *path)
{
	long fd = sc(SYS_open, (long)P(path), O_RDONLY, 0, 0, 0);

	if (fd < 0) return 0;
	r->fd = fd; r->n = r->p = r->eof = r->cut = 0;
	return 1;
}

static void lr_close(struct lr *r) { sc(SYS_close, r->fd, 0, 0, 0, 0); }

/* the next line (NUL terminated); *term = it ended with a newline; 0 at the end */
static char *lr_get(struct lr *r, int *term)
{
	int i, j;
	long k;

	r->cut = 0;
	for (;;) {
		for (i = r->p; i < r->n; i++)
			if (r->b[i] == '\n') { char *l = r->b + r->p; r->b[i] = 0; r->p = i + 1; *term = 1; return l; }
		if (r->eof) {
			char *l = r->b + r->p;

			if (r->p >= r->n) return 0;
			r->b[r->n] = 0; r->p = r->n; *term = 0;
			return l;
		}
		if (r->p) { for (j = 0; j < r->n - r->p; j++) r->b[j] = r->b[r->p + j]; r->n -= r->p; r->p = 0; }
		if (r->n >= (int)sizeof r->b - 1) {	/* too long: keep the start, drop the rest of the line */
			char *l = r->b;

			r->cut = 1;
			for (;;) {
				char c;

				k = sc(SYS_read, r->fd, (long)&c, 1, 0, 0);
				if (k <= 0) { r->eof = 1; break; }
				if (c == '\n') break;
			}
			r->b[r->n] = 0; r->n = r->p = 0; *term = 1;
			return l;
		}
		k = sc(SYS_read, r->fd, (long)r->b + r->n, (long)sizeof r->b - 1 - r->n, 0, 0);
		if (k <= 0) r->eof = 1; else r->n += (int)k;
	}
}

static int st_exists(const char *path)
{
	long fd = sc(SYS_open, (long)P(path), O_RDONLY, 0, 0, 0);

	if (fd < 0) return 0;
	sc(SYS_close, fd, 0, 0, 0, 0);
	return 1;
}

/* `read -r var < file`: 0 = no such file, 1 = out holds the first line (blanks trimmed), 2 = empty file (out "").
 * *term (optional): the line ended with a newline (a `read ... || return` fails without it). */
static int st_first(const char *path, char *out, int max, int *term)
{
	struct lr r;
	char *l, *p;
	int t = 1;

	out[0] = 0;
	if (term) *term = 1;
	if (!lr_open(&r, path)) return 0;
	l = lr_get(&r, &t);
	if (l && r.cut) st_bail = __LINE__;
	lr_close(&r);
	if (!l) return 2;
	p = l;
	l = rest(&p);
	if (slen(l) >= max) { st_bail = __LINE__; return 1; }
	for (int i = 0; (out[i] = l[i]); i++) ;
	if (term) *term = t;
	return 1;
}

/* conf_get: first KEY=value line (empty and # lines skipped, a last line without newline ignored), else def */
static void st_conf(const char *file, const char *key, char *out, int max, const char *def)
{
	struct lr r;
	char *l;
	int t, kl = slen(key), i;

	for (i = 0; def[i] && i < max - 1; i++) out[i] = def[i];
	out[i] = 0;
	if (!lr_open(&r, file)) return;
	while ((l = lr_get(&r, &t)) && t) {
		if (!l[0] || l[0] == '#') continue;
		if (pfx(l, key) && l[kl] == '=') {
			l += kl + 1;
			if (r.cut || slen(l) >= max) st_bail = __LINE__;
			else for (i = 0; (out[i] = l[i]); i++) ;
			break;
		}
	}
	lr_close(&r);
}

static int truthy(const char *v)	/* case 1|true|on|yes|enabled */
{
	return !slen_eq(v, "1") || !slen_eq(v, "true") || !slen_eq(v, "on") || !slen_eq(v, "yes") || !slen_eq(v, "enabled");
}

/* IFS='=' read -r k v: the key; *v = the rest of the line. A value ending in '=' is not reproduced (shells differ) */
static char *kvsplit(char *l, char **v)
{
	char *e = l;

	while (*e && *e != '=') e++;
	if (*e) *e++ = 0;
	*v = e;
	return l;
}

static void st_put(const char *path, const char *s, int l)
{
	long fd = sc(SYS_open, (long)P(path), O_WRONLY | O_CREAT | O_TRUNC, 0644, 0, 0);

	if (fd < 0) return;
	sc(SYS_write, fd, (long)s, l, 0, 0);
	sc(SYS_close, fd, 0, 0, 0, 0);
}

/* decimal text of v into o, returns its length */
static int fmt_u(char *o, u64 v)
{
	char t[24];
	int i = 24, l = 0;

	do { u64 q = udiv(v, 10); t[--i] = (char)('0' + (int)urem); v = q; } while (v);
	while (i < 24) o[l++] = t[i++];
	return l;
}

/* "a b c
": the numbers of a cache file */
static int fmt_nums(char *o, const u64 *v, int n)
{
	int l = 0;

	for (int i = 0; i < n; i++) { l += fmt_u(o + l, v[i]); o[l++] = i < n - 1 ? ' ' : '\n'; }
	return l;
}

/* ---- the JSON text */
static void o_c(char c)
{
	if (sl >= (int)sizeof so - 1) { st_bail = __LINE__; return; }
	so[sl++] = c;
}

static void o_r(const char *s)	/* as it is; a backslash would be an escape for busybox echo: not reproduced */
{
	for (; *s; s++) { if (*s == '\\') st_bail = __LINE__; o_c(*s); }
}

static void o_e(const char *s)	/* json_escape: backslash (not reproduced, see o_r) and double quote */
{
	for (; *s; s++) { if (*s == '"') o_c('\\'); if (*s == '\\') st_bail = __LINE__; o_c(*s); }
}

static void o_n(u64 v)
{
	char t[24];
	int i = 24;

	do { u64 q = udiv(v, 10); t[--i] = (char)('0' + (int)urem); v = q; } while (v);
	while (i < 24) o_c(t[i++]);
}

/* ---- now_ts: boot time of /proc/stat + whole seconds of /proc/uptime (_read_now_ts) */
static u64 st_now;

static void st_clock(void)
{
	struct lr r;
	char *l, *p, *k, *v, u[40];
	int t;
	u64 bt = 0;

	if (!lr_open(&r, "/proc/stat")) { st_bail = __LINE__; return; }
	while ((l = lr_get(&r, &t)) && t) {
		p = l;
		k = tok(&p);
		v = tok(&p);
		if (!slen_eq(k, "btime")) { if (r.cut) st_bail = __LINE__; bt = pnum(v); break; }
	}
	lr_close(&r);
	if (st_first("/proc/uptime", u, sizeof u, 0) != 1) { st_bail = __LINE__; return; }
	for (p = u; *p && *p != '.' && !blank(*p); p++) ;
	*p = 0;
	st_now = bt + pnum(u);
}

/* ---- CPU and memory (get_current_cpu_usage_fast, get_memory_usage_fast, the 2 s cache) */
static u64 m_cpu, m_used, m_total, m_pct;

static void st_cpu(void)
{
	struct lr r;
	char b[80], *l, *p, *w;
	int t;
	u64 pv[3], cv[3], c[8];
	s64 dt, da;

	pv[0] = pv[1] = pv[2] = 0;
	if (st_first("/tmp/state_cpu_usage.state", b, sizeof b, 0) == 1) {
		p = b;
		for (int i = 0; i < 3; i++) {
			w = i < 2 ? tok(&p) : rest(&p);
			pv[i] = isdig(w, slen(w)) ? pnum(w) : 0;
		}
	}
	if (!lr_open(&r, "/proc/stat")) { st_bail = __LINE__; return; }
	l = lr_get(&r, &t);
	if (!l || r.cut) { st_bail = __LINE__; l = (char *)""; }
	lr_close(&r);
	p = l;
	tok(&p);	/* "cpu" */
	for (int i = 0; i < 8; i++) { w = tok(&p); c[i] = *w ? pnum(w) : 0; }	/* user nice system idle iowait irq softirq steal */
	cv[0] = c[0] + c[1] + c[2] + c[5] + c[6] + c[7];
	cv[1] = cv[0] + c[3] + c[4];
	cv[2] = 0;
	dt = (s64)cv[1] - (s64)pv[1];
	da = (s64)cv[0] - (s64)pv[0];
	if (pv[1] == 0 || dt < 0) m_cpu = 0;
	else if (dt < 20) { m_cpu = pv[2]; return; }	/* too close to the last sample: its value, nothing written */
	else {
		if (da < 0) da = 0;
		m_cpu = udiv(mulu((u64)da, 100), (u64)dt);
		if (m_cpu > 100) m_cpu = 100;
		cv[2] = m_cpu;
	}
	{
		char o[80];

		st_put("/tmp/state_cpu_usage.state", o, fmt_nums(o, cv, 3));
	}
}

static void st_mem(void)
{
	struct lr r;
	char *l, *p, *k, *v;
	int t;
	u64 total = 0, avail = 0, mfree = 0, buf = 0, cached = 0, srec = 0, shmem = 0;

	if (!lr_open(&r, "/proc/meminfo")) { st_bail = __LINE__; return; }
	while ((l = lr_get(&r, &t))) {
		if (r.cut) st_bail = __LINE__;
		p = l;
		k = tok(&p);
		v = tok(&p);
		if (!slen_eq(k, "MemTotal:")) total = pnum(v);
		else if (!slen_eq(k, "MemAvailable:")) avail = pnum(v);
		else if (!slen_eq(k, "MemFree:")) mfree = pnum(v);
		else if (!slen_eq(k, "Buffers:")) buf = pnum(v);
		else if (!slen_eq(k, "Cached:")) cached = pnum(v);
		else if (!slen_eq(k, "SReclaimable:")) srec = pnum(v);
		else if (!slen_eq(k, "Shmem:")) shmem = pnum(v);
		if (total > 0 && avail > 0) break;
	}
	lr_close(&r);
	if (avail == 0) {
		s64 a = (s64)(mfree + buf + cached + srec) - (s64)shmem;

		avail = a < 0 ? 0 : (u64)a;
	}
	if (avail > total) avail = total;
	m_total = total;
	m_used = total - avail;
	m_pct = 0;
	if (total > 0) { m_pct = udiv(mulu(m_used, 100), total); if (m_pct > 100) m_pct = 100; }
}

static void st_usage(void)
{
	char b[160], *p, *w[5];
	int t;
	u64 v[5];

	for (int i = 0; i < 5; i++) v[i] = 0;
	if (st_first("/tmp/state_usage.cache", b, sizeof b, &t) == 1 && t) {
		p = b;
		for (int i = 0; i < 4; i++) w[i] = tok(&p);
		w[4] = rest(&p);
		for (int i = 0; i < 5; i++) {
			if (!isdig(w[i], slen(w[i]))) goto compute;
			if (slen(w[i]) > 18) { st_bail = __LINE__; return; }
			v[i] = pnum(w[i]);
		}
		if (st_bail) return;
		if (v[0] <= st_now && st_now - v[0] <= 2 && st_now > 0) {
			m_cpu = v[1]; m_used = v[2]; m_total = v[3]; m_pct = v[4];
			return;
		}
	}
compute:
	st_cpu();
	st_mem();
	if (st_now > 0) {
		char o[160];

		v[0] = st_now; v[1] = m_cpu; v[2] = m_used; v[3] = m_total; v[4] = m_pct;
		st_put("/tmp/state_usage.cache", o, fmt_nums(o, v, 5));
	}
}

/* ---- performance profile (5 s cache) */
static const char *m_prof;

static void st_profile(void)
{
	char b[64], *p, *ts, *pr, lo[16], tr[16];
	int t;

	if (st_first("/tmp/state_perfprofile.cache", b, sizeof b, &t) == 1 && t) {
		p = b; ts = tok(&p); pr = rest(&p);
		if (isdig(ts, slen(ts)) && (!slen_eq(pr, "balanced") || !slen_eq(pr, "low-cpu") || !slen_eq(pr, "rtsp-only"))
		    && slen(ts) <= 18 && st_now > 0) {
			u64 c = pnum(ts);

			if (c <= st_now && st_now - c <= 5) {
				m_prof = !slen_eq(pr, "balanced") ? "balanced" : !slen_eq(pr, "low-cpu") ? "low-cpu" : "rtsp-only";
				return;
			}
		}
	}
	st_conf("/mnt/config/boot.conf", "LOW_CPU_PROFILE", lo, sizeof lo, "0");
	st_conf("/mnt/config/service_trim.conf", "SERVICE_TRIM", tr, sizeof tr, "0");
	m_prof = !slen_eq(tr, "1") ? "rtsp-only" : !slen_eq(lo, "1") ? "low-cpu" : "balanced";
	if (st_now > 0) {
		char o[64];
		int l = fmt_u(o, st_now);

		o[l++] = ' ';
		for (const char *q = m_prof; *q; q++) o[l++] = *q;
		o[l++] = '\n';
		st_put("/tmp/state_perfprofile.cache", o, l);
	}
}

/* ---- SD card: df -k /mnt/sd of busybox, from statfs (same rounding as busybox df.c) */
static u64 m_sdu, m_sdt, m_sdp;
static int m_flash;

static int st_mounted(const char *mp, int any_fs)	/* a /proc/mounts line at mp (vfat or exfat unless any_fs) */
{
	struct lr r;
	char *l, *p, *dev, *m, *fs;
	int t, f = 0;

	if (!lr_open(&r, "/proc/mounts")) return 0;
	while ((l = lr_get(&r, &t)) && t) {
		p = l;
		dev = tok(&p); m = tok(&p); fs = tok(&p);
		(void)dev;
		if (slen_eq(m, mp)) continue;
		if (any_fs || !slen_eq(fs, "vfat") || !slen_eq(fs, "exfat")) { f = 1; break; }
	}
	lr_close(&r);
	return f;
}

static void st_sd(void)
{
	char b[40];
	unsigned int w[24];
	u64 blocks, bfree, bavail, used, bs, den;

	m_sdu = m_sdt = m_sdp = 0;
	m_flash = 0;
	if (st_first("/tmp/tc100-storage", b, sizeof b, 0)) {
		if (!slen_eq(b, "flash")) { m_flash = 1; return; }
	} else if (st_exists("/tmp/flashmode")) {
		m_flash = 1;
		if (!st_mounted("/mnt/sd", 0)) return;
	}
	if (!st_mounted("/mnt/sd", 1) && !st_mounted("/mnt", 1)) return;	/* df would name another mount point */
	if (sc(SYS_statfs64, (long)P("/mnt/sd"), 88, (long)w, 0, 0)) return;
	bs = w[1];
	blocks = (u64)w[2] | (u64)w[3] << 32;
	bfree = (u64)w[4] | (u64)w[5] << 32;
	bavail = (u64)w[6] | (u64)w[7] << 32;
	if (!blocks) return;
	used = blocks - bfree;
	den = used + bavail;
	m_sdt = (mulu(blocks, (u32)bs) + 512) >> 10;
	m_sdu = (mulu(used, (u32)bs) + 512) >> 10;
	if (den) m_sdp = udiv(mulu(used, 100) + udiv(den, 2), den);
}

/* ---- Wi-Fi link quality (wifi_signal_read any + get_wifi_quality) */
static char m_wq[24], m_wif[40];

static void st_wifi(void)
{
	struct lr r;
	char *l, *p, *ifn, *lk, *c, cur[40], q[24];
	int t, n;

	m_wq[0] = 0; m_wif[0] = 0;
	cur[0] = 0; q[0] = 0;
	if (!lr_open(&r, "/proc/net/wireless")) return;
	while ((l = lr_get(&r, &t)) && t) {
		int w0;

		p = l;
		ifn = tok(&p); tok(&p); lk = tok(&p);
		n = slen(ifn);
		if (n < 1 || ifn[n - 1] != ':') continue;
		ifn[n - 1] = 0;
		for (c = lk; *c && *c != '.'; c++) ;
		*c = 0;
		if (!isdig(lk, slen(lk))) lk = (char *)"";
		w0 = !slen_eq(ifn, "wlan0");
		if (!w0 && !(cur[0] == 0 && lk[0] && slen(lk) <= 18 && pnum(lk) > 0)) continue;
		if (slen(ifn) >= (int)sizeof cur || slen(lk) >= (int)sizeof q) { st_bail = __LINE__; break; }
		for (n = 0; (cur[n] = ifn[n]); n++) ;
		for (n = 0; (q[n] = lk[n]); n++) ;
		if (w0) break;
	}
	lr_close(&r);
	if (!cur[0] || !q[0] || !slen_eq(q, "0")) return;	/* null */
	if (slen(q) > 18) { st_bail = __LINE__; return; }
	if (pnum(q) > 100) { q[0] = '1'; q[1] = '0'; q[2] = '0'; q[3] = 0; }
	for (n = 0; (m_wq[n] = q[n]); n++) ;
	for (n = 0; (m_wif[n] = cur[n]); n++) ;
}

/* ---- the JSON */
static void scpy(char *d, const char *s) { while ((*d++ = *s++)) ; }

/* every character of s is in the class: 0 a-z, 1 a-z _, 2 letters and digits, 3 letters, digits and ".:/_-" */
static int allin(const char *s, int kind)
{
	for (; *s; s++) {
		char c = *s;
		int az = c >= 'a' && c <= 'z', dg = c >= '0' && c <= '9', up = c >= 'A' && c <= 'Z';

		if (kind == 0 ? az : kind == 1 ? az || c == '_' : kind == 2 ? az || dg || up : az || dg || up || c == '.' ||
		    c == ':' || c == '/' || c == '_' || c == '-')
			continue;
		return 0;
	}
	return 1;
}

struct kv { const char *key; char *dst; int cap; };

/* IFS='=' read -r k v over a file: the last value of each key (the line must end with a newline). A value ending in '='
 * is not reproduced (shells differ): the request falls through */
static void st_kv(const char *file, struct kv *t, int n)
{
	struct lr r;
	char *l, *k, *v;
	int tm, i;

	if (!lr_open(&r, file)) return;
	while ((l = lr_get(&r, &tm)) && tm) {
		k = kvsplit(l, &v);
		for (i = 0; i < n; i++)
			if (!slen_eq(k, t[i].key)) {
				int e = slen(v);

				if (r.cut || e >= t[i].cap || (e && v[e - 1] == '=')) st_bail = __LINE__;
				else scpy(t[i].dst, v);
			}
	}
	lr_close(&r);
}

static void st_na(char *d) { scpy(d, "n/a"); }

/* the echo of statusline_json, from the files of the camera. 0: not exactly reproducible, httpd must answer */
static int st_json(const char *root)
{
	char lum[160], awb[160], sec[16], mqe[16], tmp[300], upd[400], ver[160], hn[160], pw1[160], pw2[160];
	char csrf[160], uval[200], health[40], card[40], pid[40], pr[8], cfgs[40], cfgm[300], frig[300], mqts[48], sdb[48];
	char u_url[200], u_cam[200];
	int t, mq_ok = -1, mq_ref = 0, def = 0, upd_a = 0, i;
	char *p, *k;
	struct kv fl[2] = { { "FRIGATE_URL", u_url, sizeof u_url }, { "FRIGATE_CAMERA", u_cam, sizeof u_cam } };
	struct kv sh[1] = { { "state", health, sizeof health } };
	struct kv sc3[3] = { { "kind", card, sizeof card }, { "prompt", pr, sizeof pr }, { "id", pid, sizeof pid } };
	struct kv cp[2] = { { "state", cfgs, sizeof cfgs }, { "msg", cfgm, sizeof cfgm } };

	st_root = root ? root : "";
	st_bail = 0;
	sl = SO0;
	st_clock();
	if (st_bail) return 0;
	st_usage();
	st_profile();
	if (st_bail) return 0;

	/* lum / awb (load_lum_awb) */
	lum[0] = awb[0] = 0;
	if (!st_first("/var/run/lum", lum, sizeof lum, 0)) st_first("/tmp/cam_luma", lum, sizeof lum, 0);
	st_first("/var/run/awb", awb, sizeof awb, 0);

	/* security / MQTT flags */
	st_conf("/mnt/config/boot.conf", "SECURITY_HARDENING_MODE", sec, sizeof sec, "0");
	st_conf("/mnt/config/mqtt.conf", "MQTT_ENABLE", mqe, sizeof mqe, "0");
	mqts[0] = '0'; mqts[1] = 0;
	if (st_exists("/tmp/mqtt_last_pub.status")) {
		char *ts, *res, *code;

		st_first("/tmp/mqtt_last_pub.status", tmp, sizeof tmp, 0);
		p = tmp; ts = tok(&p); res = tok(&p); code = rest(&p);
		if (isdig(ts, slen(ts))) { if (slen(ts) >= (int)sizeof mqts) st_bail = __LINE__; else scpy(mqts, ts); }
		if (!slen_eq(res, "ok")) mq_ok = 1;
		else if (!slen_eq(res, "fail")) { mq_ok = 0; if (code[0] >= '1' && code[0] <= '5' && !code[1]) mq_ref = code[0] - '0'; }
	}

	st_sd();
	st_wifi();

	/* default password flag (120 s cache) */
	t = 0;
	if (st_exists("/tmp/state_pwd.cache")) {
		char *ts, *val;

		if (st_first("/tmp/state_pwd.cache", tmp, sizeof tmp, 0) != 1) st_bail = __LINE__;
		else {
			p = tmp; ts = tok(&p); val = rest(&p);
			if (isdig(ts, slen(ts)) && (!val[0] || isdig(val, slen(val)))) {
				u64 c = pnum(ts);

				if (st_now > 0 && c <= st_now && st_now - c <= 120) { def = !slen_eq(val, "1"); t = 1; }
			}
		}
	}
	if (!t) {
		char o[40];

		st_conf("/mnt/config/rtspserver.conf", "USERNAME", pw1, sizeof pw1, "root");
		st_conf("/mnt/config/rtspserver.conf", "USERPASSWORD", pw2, sizeof pw2, "pass");
		def = !slen_eq(pw1, "root") && !slen_eq(pw2, "pass");
		if (st_first("/mnt/config/user.pwd", tmp, sizeof tmp, 0) && !slen_eq(tmp, "pass")) def = 1;
		i = fmt_u(o, st_now);
		o[i++] = ' '; o[i++] = (char)('0' + def); o[i++] = '\n';
		st_put("/tmp/state_pwd.cache", o, i);
	}

	/* CSRF token: the CGI creates a missing one, we leave that to it */
	if (st_first("/tmp/csrf_token", csrf, sizeof csrf, 0) != 1) return 0;
	for (i = 0, k = csrf; *k; k++)
		if ((*k >= '0' && *k <= '9') || (*k >= 'a' && *k <= 'f') || (*k >= 'A' && *k <= 'F')) csrf[i++] = *k;
	csrf[i] = 0;

	/* update notifier: "update_available":1 anywhere, the text of "latest_version":"..." */
	upd[0] = 0;
	st_first("/tmp/update_status.json", upd, sizeof upd, 0);
	st_na(uval);
	for (p = upd; *p; p++) if (pfx(p, "\"update_available\":1")) { upd_a = 1; break; }
	for (p = upd; *p; p++)
		if (pfx(p, "\"latest_version\":\"")) {
			p += 18;
			for (i = 0; p[i] && p[i] != '"' && i < (int)sizeof uval - 1; i++) uval[i] = p[i];
			if (p[i] && p[i] != '"') st_bail = __LINE__;
			if (i) uval[i] = 0;
			break;
		}

	/* firmware version, host name */
	st_first("/mnt/VERSION", ver, sizeof ver, 0);
	if (!ver[0]) st_na(ver);
	st_first("/proc/sys/kernel/hostname", hn, sizeof hn, 0);
	if (!hn[0]) scpy(hn, "tc100");

	/* the small status files of the other scripts */
	u_url[0] = u_cam[0] = health[0] = card[0] = pid[0] = cfgs[0] = cfgm[0] = 0;
	pr[0] = '0'; pr[1] = 0;
	st_kv("/mnt/config/frigate_live.conf", fl, 2);
	st_kv("/tmp/sd-health", sh, 1);
	st_kv("/tmp/sd-card", sc3, 3);
	st_kv("/tmp/cfg-persist.status", cp, 2);
	frig[0] = 0;
	if (u_url[0] && allin(u_url, 3) && allin(u_cam, 3)) {	/* url + "/" + "#camera" */
		if (slen(u_url) + slen(u_cam) + 3 >= (int)sizeof frig) st_bail = __LINE__;
		else {
			scpy(frig, u_url);
			i = slen(frig);
			frig[i++] = '/';
			frig[i] = 0;
			if (u_cam[0]) { frig[i++] = '#'; scpy(frig + i, u_cam); }
		}
	}
	if (!allin(health, 0)) health[0] = 0;
	if (!allin(card, 0)) card[0] = 0;
	if (slen_eq(pr, "1") || !allin(pid, 2)) pid[0] = 0;	/* the card's id, when the page has to ask about it */
	if (!allin(cfgs, 1)) cfgs[0] = 0;

	/* microphone level: "<ts> <dBFS>" not older than 10 s */
	scpy(sdb, "null");
	if (st_first("/var/run/sound_level", tmp, sizeof tmp, 0) == 1) {
		char *ts, *rms;

		p = tmp; ts = tok(&p); rms = tok(&p);
		if (isdig(ts, slen(ts))) {
			if (slen(ts) > 18) st_bail = __LINE__;
			if ((s64)st_now - (s64)pnum(ts) <= 10 &&
			    ((rms[0] == '-' && rms[1] >= '0' && rms[1] <= '9') || !slen_eq(rms, "0"))) {
				if (slen(rms) >= (int)sizeof sdb) st_bail = __LINE__; else scpy(sdb, rms);
			}
		}
	}
	if (st_bail) return 0;

	/* the line */
	o_r("{\"sysusage\":\"CPU: "); o_n(m_cpu); o_r("% RAM: "); o_n(m_used); o_c('/'); o_n(m_total);
	o_r(" kB\",\"cpu\":"); o_n(m_cpu);
	o_r(",\"ram_used_kb\":"); o_n(m_used);
	o_r(",\"ram_total_kb\":"); o_n(m_total);
	o_r(",\"ram_percent\":"); o_n(m_pct);
	o_r(",\"sd_used_kb\":"); o_n(m_sdu);
	o_r(",\"sd_total_kb\":"); o_n(m_sdt);
	o_r(",\"sd_percent\":"); o_n(m_sdp);
	o_r(",\"perfprofile\":\""); o_r(m_prof);
	o_r("\",\"lum\":\""); o_e(lum);
	o_r("\",\"awb\":\""); o_e(awb);
	o_r("\",\"web_mode\":\"http\",\"security_hardening_mode\":"); o_n((u64)truthy(sec));
	o_r(",\"mqtt_enabled\":"); o_n((u64)truthy(mqe));
	o_r(",\"mqtt_last_pub_ts\":"); o_r(mqts);
	o_r(",\"mqtt_last_pub_ok\":"); if (mq_ok < 0) o_r("-1"); else o_n((u64)mq_ok);
	o_r(",\"mqtt_refused\":"); o_n((u64)mq_ref);
	o_r(",\"default_password_active\":"); o_n((u64)def);
	o_r(",\"csrf_token\":\""); o_r(csrf);
	o_r("\",\"update_available\":"); o_n((u64)upd_a);
	o_r(",\"update_latest_version\":\""); o_e(uval);
	o_r("\",\"current_version\":\""); o_e(ver);
	o_r("\",\"wifi_qual\":"); o_r(m_wq[0] ? m_wq : "null");
	o_r(",\"wifi_iface\":\""); o_r(m_wif);
	o_r("\",\"frigate_live\":\""); o_r(frig);
	o_r("\",\"storage\":\""); o_r(m_flash ? "flash" : "sd");
	o_r("\",\"sd_health\":\""); o_r(health);
	o_r("\",\"sd_card\":\""); o_r(card);
	o_r("\",\"sd_prompt\":\""); o_r(pid);
	o_r("\",\"platform\":\"linux66\",\"cfg_save\":\""); o_r(cfgs);
	o_r("\",\"cfg_save_msg\":\""); o_e(cfgm);
	o_r("\",\"hostname\":\""); o_e(hn);
	o_r("\",\"sound_db\":"); o_r(sdb);
	o_r("}\n");
	return !st_bail;
}

/* the whole response in so (header right before the body): returns its start, *len its length; 0 = fall through */
static const char *status_response(const char *root, int *len)
{
	static const char h1[] = "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nPragma: no-cache\r\n"
		"Cache-Control: max-age=0, no-store, no-cache\r\nConnection: close\r\nContent-Length: ";
	char hd[SO0];
	int hl = 0, body, d;
	u64 x;
	char dg[12];

	if (!st_json(root)) return 0;
	body = sl - SO0;
	cat(hd, &hl, SO0 - 16, h1);
	x = (u64)body;
	d = 12;
	do { u64 q = udiv(x, 10); dg[--d] = (char)('0' + (int)urem); x = q; } while (x);
	while (d < 12) hd[hl++] = dg[d++];
	hd[hl++] = '\r'; hd[hl++] = '\n'; hd[hl++] = '\r'; hd[hl++] = '\n';
	for (int i = 0; i < hl; i++) so[SO0 - hl + i] = hd[i];
	*len = hl + body;
	return so + SO0 - hl;
}

#pragma GCC pop_options
#endif
