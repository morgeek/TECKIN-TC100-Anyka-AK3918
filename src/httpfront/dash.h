/* dash.h: GET /cgi-bin/dash.cgi (the dashboard poll, every 5 s) answered by httpfront itself (item 55, same switch as
 * status.h: HTTPFRONT_NATIVE=1 -> TC100_NATIVE_STATUS=1). Included by httpfront.c after status.h, whose helpers it uses.
 *
 * Port of www/cgi-bin/dash.cgi, field by field: raw counters of /proc/stat, /proc/meminfo, /proc/net/dev,
 * /proc/uptime, /proc/loadavg, /proc/net/tcp (RTSP viewers), /proc/net/wireless + /tmp/wifi-signal.avg
 * (scripts/wifi-signal.sh, wifi_signal_read without "any"), PORT of rtspserver.conf, state of /tmp/sd-health. The numbers
 * are printed as the strings the shell prints, so the rule is the one of status.h: anything the shell would print
 * differently (a non-numeric counter, a value ending in '=', a line longer than the buffer, an unreadable /proc/uptime)
 * returns 0 and the request goes to httpd and the CGI as before. No cache file: nothing is written. */
#ifndef HF_DASH_H
#define HF_DASH_H

#pragma GCC push_options
#pragma GCC target("thumb")

#define DW 24	/* room of a counter word */

static int dh_digs(const char *s) { return isdig(s, slen(s)); }

/* -[0-9] | -[0-9][0-9] | -10[0-9] | -110 (the dBm patterns of wifi-signal.sh) */
static int dh_dbm(const char *s)
{
	int n = slen(s);

	if (s[0] != '-') return 0;
	if (n == 2 || n == 3) return isdig(s + 1, n - 1);
	return n == 4 && (!slen_eq(s, "-110") || (pfx(s, "-10") && isdig(s + 3, 1)));
}

/* a counter word copied as it is: digits only, short; else the CGI's answer is not reproduced */
static void dh_cp(char *d, const char *w)
{
	if (!dh_digs(w) || slen(w) >= DW) st_bail = __LINE__; else scpy(d, w);
}

/* wifi_signal_read (no "any"): wlan0 only. 1 = found; q, d = quality and dBm words ("" when unknown) */
static int dh_wifi(char *q, char *d)
{
	struct lr r;
	char *l, *p, *ifn, *lk, *lv, *c, a[40], up[40];
	int t, n, found = 0;

	q[0] = d[0] = 0;
	if (!lr_open(&r, "/proc/net/wireless")) return 0;
	while ((l = lr_get(&r, &t)) && t) {
		p = l;
		ifn = tok(&p); tok(&p); lk = tok(&p); lv = tok(&p);
		n = slen(ifn);
		if (n < 1 || ifn[n - 1] != ':') continue;
		ifn[n - 1] = 0;
		if (slen_eq(ifn, "wlan0")) continue;
		for (c = lk; *c && *c != '.'; c++) ;
		*c = 0;
		for (c = lv; *c && *c != '.'; c++) ;
		*c = 0;
		if (r.cut || slen(lk) >= DW || slen(lv) >= DW) st_bail = __LINE__;
		else {
			if (dh_digs(lk)) scpy(q, lk);
			if (dh_dbm(lv)) scpy(d, lv);
		}
		found = 1;
		break;
	}
	lr_close(&r);
	if (!found) return 0;
	if (st_first("/tmp/wifi-signal.avg", a, sizeof a, 0)) {	/* the access point's average, when less than 3 min old */
		char *ts, *av;
		u64 u = 0;

		p = a; ts = tok(&p); av = rest(&p);
		if (dh_digs(ts) && dh_dbm(av)) {
			if (slen(ts) > 9 || (ts[0] == '0' && ts[1])) { st_bail = __LINE__; return 1; }	/* octal in $(( )) */
			if (st_first("/proc/uptime", up, sizeof up, 0) == 1) {
				p = up;
				c = tok(&p);
				for (n = 0; c[n] && c[n] != '.'; n++) ;
				c[n] = 0;
				if (!dh_digs(c) || n > 9 || (c[0] == '0' && c[1])) { st_bail = __LINE__; return 1; }
				u = pnum(c);
			}
			{
				s64 df = (s64)u - (s64)pnum(ts);

				if (df >= 0 && df <= 180) scpy(d, av);
			}
		}
	}
	return 1;
}

static int dh_json(const char *root)
{
	struct lr r;
	char *l, *p, *k, *v, b[64], cpu[7][DW], mt[DW], ma[DW], ifn[40], rx[DW], tx[DW], wq[DW], wd[DW], up[DW], ld[DW];
	char rp[DW], sd[40];
	int t, i, cl = 0, got = 0, rpn;
	u64 port = 0;
	struct kv rk[1] = { { "PORT", rp, sizeof rp } };
	struct kv sk[1] = { { "state", sd, sizeof sd } };

	st_root = root ? root : "";
	st_bail = 0;
	sl = SO0;
	for (i = 0; i < 7; i++) { cpu[i][0] = '0'; cpu[i][1] = 0; }
	if (lr_open(&r, "/proc/stat")) {
		while ((l = lr_get(&r, &t)) && t) {
			p = l;
			k = tok(&p);
			if (slen_eq(k, "cpu")) continue;
			if (r.cut) st_bail = __LINE__;
			for (i = 0; i < 7; i++) {
				char *w = tok(&p);

				if (i >= 4 && !*w) w = (char *)"0";	/* ${_w:-0} */
				dh_cp(cpu[i], w);
			}
			break;
		}
		lr_close(&r);
	}
	mt[0] = ma[0] = '0'; mt[1] = ma[1] = 0;
	if (lr_open(&r, "/proc/meminfo")) {
		while ((l = lr_get(&r, &t)) && t) {
			p = l; k = tok(&p); v = tok(&p);
			if (r.cut) st_bail = __LINE__;
			if (!slen_eq(k, "MemTotal:")) dh_cp(mt, v);
			else if (!slen_eq(k, "MemAvailable:")) { dh_cp(ma, v); break; }
		}
		lr_close(&r);
	}
	/* /proc/net/dev: a line holding "wlan0:" or "eth0:"; the last such line, the first wlan0 one ends the loop */
	ifn[0] = 0; rx[0] = tx[0] = '0'; rx[1] = tx[1] = 0;
	if (lr_open(&r, "/proc/net/dev")) {
		while ((l = lr_get(&r, &t)) && t) {
			char *c, *w[9];
			int hit = 0;

			for (c = l; *c; c++) if (pfx(c, "wlan0:") || pfx(c, "eth0:")) { hit = 1; break; }
			if (!hit) continue;
			if (r.cut) st_bail = __LINE__;
			for (c = l; *c && *c != ':'; c++) ;
			*c++ = 0;
			for (k = l + slen(l); k > l && k[-1] != ' '; k--) ;	/* "${_d_if##* }" */
			if (slen(k) >= (int)sizeof ifn || !allin(k, 3)) st_bail = __LINE__; else scpy(ifn, k);
			p = c;
			for (i = 0; i < 9; i++) w[i] = tok(&p);
			if (*w[0]) dh_cp(rx, w[0]); else scpy(rx, "0");
			if (*w[8]) dh_cp(tx, w[8]); else scpy(tx, "0");
			if (!slen_eq(ifn, "wlan0")) break;
		}
		lr_close(&r);
	}
	wq[0] = wd[0] = 0;
	if (st_exists("/mnt/scripts/wifi-signal.sh") && dh_wifi(wq, wd)) got = 1;
	up[0] = '0'; up[1] = 0;
	if ((i = st_first("/proc/uptime", b, sizeof b, 0))) {
		p = b; v = tok(&p);
		for (k = v; *k && *k != '.'; k++) ;
		*k = 0;
		if (i != 1) st_bail = __LINE__; else dh_cp(up, v);
	}
	ld[0] = '0'; ld[1] = 0;
	if (st_first("/proc/loadavg", b, sizeof b, 0)) {
		p = b; v = tok(&p);
		for (k = v; *k; k++) if ((*k < '0' || *k > '9') && *k != '.') st_bail = __LINE__;
		if (slen(v) >= DW) st_bail = __LINE__; else scpy(ld, v);
	}
	/* RTSP viewers: ESTABLISHED connections to the port of rtspserver.conf (string comparison, as the CGI) */
	scpy(rp, "554");
	st_kv("/mnt/config/rtspserver.conf", rk, 1);
	rpn = slen(rp);
	if (rpn && rp[rpn - 1] == '"') rp[--rpn] = 0;
	p = rp;
	if (*p == '"') p++;
	if (!*p || !dh_digs(p)) p = (char *)"554";
	rpn = slen(p);
	if (rpn > 9) st_bail = __LINE__;
	else if (!(rpn > 1 && p[0] == '0')) port = pnum(p);
	else port = (u64)1 << 40;	/* "0554" is never equal to the decimal text of a port */
	if (lr_open(&r, "/proc/net/tcp")) {
		while ((l = lr_get(&r, &t)) && t) {
			char *loc, *st, *c;
			u64 x = 0;

			p = l; tok(&p); loc = tok(&p); tok(&p); st = tok(&p);
			if (slen_eq(st, "01")) continue;
			if (r.cut) st_bail = __LINE__;
			for (c = loc + slen(loc); c > loc && c[-1] != ':'; c--) ;
			if (!*c) continue;
			if (slen(c) > 15) { st_bail = __LINE__; continue; }
			for (i = 0; c[i]; i++) {
				char h = c[i];

				if (h >= '0' && h <= '9') h -= '0';
				else if (h >= 'a' && h <= 'f') h -= 'a' - 10;
				else if (h >= 'A' && h <= 'F') h -= 'A' - 10;
				else break;
				x = x << 4 | (u64)h;
			}
			if (!c[i] && x == port) cl++;	/* not hex: skipped */
		}
		lr_close(&r);
	}
	sd[0] = 0;
	st_kv("/tmp/sd-health", sk, 1);
	if (!allin(sd, 0)) sd[0] = 0;
	if (st_bail) return 0;

	o_r("{\"up\":"); o_r(up);
	o_r(",\"load\":\""); o_r(ld);
	o_r("\",\"cpu\":[");
	for (i = 0; i < 7; i++) { if (i) o_c(','); o_r(cpu[i]); }
	o_r("],\"mem\":["); o_r(mt); o_c(','); o_r(ma);
	o_r("],\"iface\":\""); o_r(ifn);
	o_r("\",\"net\":["); o_r(rx); o_c(','); o_r(tx);
	o_r("],\"wifi\":["); o_r(got && wq[0] ? wq : "null"); o_c(','); o_r(got && wd[0] ? wd : "null");
	o_r("],\"rtsp_clients\":"); o_n((u64)cl);
	o_r(",\"sd_health\":\""); o_r(sd);
	o_r("\"}\n");
	return !st_bail;
}

static const char *dash_response(const char *root, int *len)
{
	static const char h1[] = "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n"
		"Connection: close\r\nContent-Length: ";

	return dh_json(root) ? wrap_response(h1, len) : 0;
}

#pragma GCC pop_options
#endif
