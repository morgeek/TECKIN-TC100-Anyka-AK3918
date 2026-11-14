/* poll.h: two more polled reads answered by httpfront itself (same switch as status.h and dash.h: HTTPFRONT_NATIVE=1 ->
 * TC100_NATIVE_STATUS=1). Included by httpfront.c after dash.h; it uses the helpers of status.h.
 *
 *   GET /cgi-bin/state.cgi?cmd=daynight&format=json    (Settings -> Day/night, every 5 s)
 *   GET /cgi-bin/action.cgi?cmd=hw_state&format=json   (the Hardware page, every 2 s)
 *
 * Ports of the `daynight` arm of www/cgi-bin/state.cgi (with its load_conf_file and cfg_int) and of the `hw_state` arm of
 * scripts/action.d/hardware.sh behind www/cgi-bin/action.cgi, field by field, with the quirks of the shell (`read -r`
 * takes a last line without newline, `while read` does not, load_conf_file does, the last assignment of a key wins, a
 * [section] prefixes the keys). The rule is the one of status.h: an answer only when it is the exact answer of the CGI;
 * anything else returns 0 and the request goes to httpd and the CGI as before:
 *   - a query whose cmd or format is not plain text (%XX, +), or no format=json (the Accept header is left to the CGI);
 *   - a number the shell would read as octal, or a product that would wrap its 64 bits; a value ending in '='; a line or a value
 *     longer than the buffers;
 *   - hw_state: a missing or unclean /tmp/csrf_token (csrf_guard creates it), an audit log to create or to rotate
 *     (/tmp/log/audit.log over 64 KB), a pid file holding anything but one number, a control character in the level.
 * daynight: state.cgi keeps its answer 1 s in /tmp/state-response-daynight-json.cache; here the same files are read at
 * each request and nothing is written. hw_state: action.cgi notes every command in /tmp/log/audit.log, this one
 * included; the same line is appended here (same clock: btime + uptime, same address as httpd's REMOTE_ADDR). */
#ifndef HF_POLL_H
#define HF_POLL_H

#pragma GCC push_options
#pragma GCC target("thumb")

#define SYS_lseek 19
#define SYS_kill 37

static u32 pl_ip;	/* the client (host order): REMOTE_ADDR of the audit line */

static int pl_is(const char *s, int n, const char *w) { return slen(w) == n && !cred_cmp(s, w, n); }

/* the request line against func.cgi's parsing of QUERY_STRING (words split on &, name before the first =, names of
 * [A-Za-z0-9_] only, the last value of a name wins): 3 = state.cgi cmd=daynight, 4 = action.cgi cmd=hw_state, both
 * with format=json; 0 = not ours */
static int pl_route(const char *b)
{
	const char *q, *e, *cmd = "", *fmt = "";
	int cl = 0, fl = 0, r;

	if (pfx(b, "GET /cgi-bin/state.cgi?")) { r = 3; q = b + 23; }
	else if (pfx(b, "GET /cgi-bin/action.cgi?")) { r = 4; q = b + 24; }
	else return 0;
	for (;;) {
		const char *eq = 0, *v;
		int plain = 1, nl, vl;

		for (e = q; *e && *e != '&' && *e != ' '; e++) {
			if ((unsigned char)*e < ' ' || *e == 127) return 0;
			if (!eq && *e == '=') eq = e;
		}
		nl = (int)((eq ? eq : e) - q);
		v = eq ? eq + 1 : q;		/* no '=': "${_VAR#*=}" is the whole word */
		vl = (int)(e - v);
		for (int i = 0; i < vl; i++) if (v[i] == '%' || v[i] == '+') plain = 0;
		if (pl_is(q, nl, "cmd")) { if (!plain) return 0; cmd = v; cl = vl; }
		else if (pl_is(q, nl, "format")) { if (!plain) return 0; fmt = v; fl = vl; }
		if (*e != '&') break;
		q = e + 1;
	}
	if (*e != ' ' || !pl_is(fmt, fl, "json")) return 0;	/* cut by the end of the peeked bytes: not ours */
	return pl_is(cmd, cl, r == 3 ? "daynight" : "hw_state") ? r : 0;
}

/* ---- daynight ---- */
enum { DN_SRC, DN_LN, DN_LD, DN_AN, DN_AD, DN_NH, DN_DH, DN_VN, DN_VD, DN_IR, DN_NS, DN_LF, DN_LV, DN_IRM, DN_N7, DN_N };
static const char *const dn_key[DN_N] = { "DAYNIGHT_SOURCE", "LUMA_NIGHT", "LUMA_DAY", "AE_NIGHT_ABOVE", "AE_DAY_BELOW",
	"NIGHT_HOLD", "DAY_HOLD", "VENDOR_NIGHT_LUM", "VENDOR_DAY_LUM", "IR_LED_MAX_ON", "NIGHT_STYLE", "LOWLIGHT_FPS",
	"LOWLIGHT_FPS_VALUE", "IR_LED_MODE", "NIGHT_720P" };
static const char *const dn_def[DN_N] = { "", "40", "100", "15000", "3000", "10", "60", "3584", "1536", "50400", "1", "1",
	"10", "", "0" };

static int pl_name(const char *s)	/* [A-Za-z0-9_]+ */
{
	if (!*s) return 0;
	for (; *s; s++)
		if (!((*s >= 'a' && *s <= 'z') || (*s >= 'A' && *s <= 'Z') || (*s >= '0' && *s <= '9') || *s == '_')) return 0;
	return 1;
}

/* load_conf_file: every KEY=value line sets C_KEY (C_SECTION_KEY after a [SECTION] line), the last one wins, the last
 * line counts even without a newline. Only the keys of dn_key are kept. */
static void dn_conf(const char *file, char v[DN_N][DW])
{
	struct lr r;
	char *l, *k, *val, sec[24];
	int t, i, n, skip = 0;

	sec[0] = 0;
	if (!lr_open(&r, file)) return;
	while ((l = lr_get(&r, &t))) {
		if (r.cut) { st_bail = __LINE__; break; }
		k = kvsplit(l, &val);
		n = slen(k);
		if (n >= 2 && k[0] == '[' && k[n - 1] == ']') {
			k[n - 1] = 0;
			k++;
			/* a section no key of ours can start with (not a name, or too long) hides its keys */
			skip = !pl_name(k) || n - 2 >= (int)sizeof sec;
			if (!skip) scpy(sec, k);
			continue;
		}
		if (!pl_name(k) || skip) continue;
		n = slen(sec);
		for (i = 0; i < DN_N; i++) {
			const char *w = dn_key[i];
			int e;

			if (n) {
				if (!pfx(w, sec) || w[n] != '_') continue;
				w += n + 1;
			}
			if (slen_eq(w, k)) continue;
			e = slen(val);
			if (e && val[e - 1] == '=') st_bail = __LINE__;	/* IFS='=' read: shells differ */
			else if (e < DW) scpy(v[i], val);
			else if (isdig(val, e)) st_bail = __LINE__;	/* a number longer than the buffer */
			else scpy(v[i], "?");				/* neither a number nor a known word */
		}
	}
	lr_close(&r);
}

static int dn_oct(const char *s) { return s[0] == '0' && s[1]; }	/* a leading zero: octal in $(( )) */

/* a * b as the shell computes it (signed 64 bits); a product that would wrap is not reproduced */
static u64 dn_mul(u64 a, u32 b)
{
	if (b && a > udiv(0x7fffffffffffffffULL, b)) { st_bail = __LINE__; return 0; }
	return mulu(a, b);
}

static int dn_json(const char *root)
{
	struct lr r;
	char v[DN_N][DW], luma[DW], ae[200], cut[40], *p, *l, *w[6], *m, *val;
	const char *src, *irm;
	int i, t, got = 0, night = 0, autom = 1;
	u64 idx = 0, lum = 0;

	st_root = root ? root : "";
	st_bail = 0;
	sl = SO0;
	for (i = 0; i < DN_N; i++) v[i][0] = 0;
	dn_conf("/mnt/config/daynight.conf", v);
	for (i = 0; i < DN_N; i++)	/* cfg_int: digits only, else the default */
		if (i != DN_SRC && i != DN_IRM && !isdig(v[i], slen(v[i]))) scpy(v[i], dn_def[i]);
	src = !slen_eq(v[DN_SRC], "ae") || !slen_eq(v[DN_SRC], "isp") || !slen_eq(v[DN_SRC], "vendor") ? v[DN_SRC] : "luma";
	irm = !slen_eq(v[DN_IRM], "off") || !slen_eq(v[DN_IRM], "force") ? v[DN_IRM] : "auto";
	if (slen_eq(v[DN_LV], "15") && slen_eq(v[DN_LV], "20")) scpy(v[DN_LV], "10");
	st_first("/tmp/cam_luma", luma, sizeof luma, 0);
	if (!isdig(luma, slen(luma))) scpy(luma, "null");
	/* /tmp/cam_ae: lumi exp_time a_gain d_gain isp_d_gain dark_flag [exp_max] */
	for (i = 0; i < 6; i++) w[i] = (char *)"";
	if (st_first("/tmp/cam_ae", ae, sizeof ae, 0) == 1) {
		p = ae;
		for (i = 0; i < 6; i++) w[i] = tok(&p);
		m = rest(&p);
		got = 1;
		for (i = 0; i < 6; i++) if (!isdig(w[i], slen(w[i]))) got = 0;
		for (i = 1; i < 5 && got; i++) if (slen(w[i]) > 9) got = 0;
		if (got) {
			u64 e, a, d, g, x, lv, mv = 1125;

			for (i = 0; i < 5; i++) if (dn_oct(w[i])) st_bail = __LINE__;
			if (slen(w[0]) > 9 || slen(w[5]) >= DW) st_bail = __LINE__;
			if (isdig(m, slen(m)) && slen_eq(m, "0")) {
				if (dn_oct(m) || slen(m) > 9) st_bail = __LINE__; else mv = pnum(m);
			}
			if (!st_bail) {
				lv = pnum(w[0]); e = pnum(w[1]); a = pnum(w[2]); d = pnum(w[3]); g = pnum(w[4]);
				/* the exposure index of auto-night-daemon.sh dn_index */
				x = dn_mul(dn_mul(e, (u32)a) >> 8, (u32)d) >> 8;
				idx = dn_mul(x, (u32)g) >> 8;
				/* the stock firmware's metric: exp_time * gain / exp_max * 40 / lumi */
				x = dn_mul(dn_mul(a, (u32)d) >> 8, (u32)g) >> 8;
				lum = udiv(dn_mul(udiv(dn_mul(x, (u32)e), mv), 40), lv > 0 ? lv : 40);
			}
		}
	}
	if (st_first("/var/run/ircut", cut, sizeof cut, 0) && !slen_eq(cut, "0")) night = 1;
	/* the first "daynight=" line of rtspserver.conf: 3 = manual night */
	if (lr_open(&r, "/mnt/config/rtspserver.conf")) {
		while ((l = lr_get(&r, &t)) && t) {
			if (slen_eq(kvsplit(l, &val), "daynight")) continue;
			i = slen(val);
			if (r.cut || (i && val[i - 1] == '=')) st_bail = __LINE__;
			if (!slen_eq(val, "3")) autom = 0;
			break;
		}
		lr_close(&r);
	}
	if (st_bail) return 0;

	o_r("{\"source\":\""); o_r(src);
	o_r("\",\"luma_night\":"); o_r(v[DN_LN]);
	o_r(",\"luma_day\":"); o_r(v[DN_LD]);
	o_r(",\"ae_night_above\":"); o_r(v[DN_AN]);
	o_r(",\"ae_day_below\":"); o_r(v[DN_AD]);
	o_r(",\"night_hold\":"); o_r(v[DN_NH]);
	o_r(",\"day_hold\":"); o_r(v[DN_DH]);
	o_r(",\"auto\":"); o_n((u64)autom);
	o_r(",\"night\":"); o_n((u64)night);
	o_r(",\"luma\":"); o_r(luma);
	o_r(",\"ae_available\":"); o_n((u64)got);
	o_r(",\"lumi\":"); o_r(got ? w[0] : "null");
	o_r(",\"exp_time\":"); o_r(got ? w[1] : "null");
	o_r(",\"a_gain\":"); o_r(got ? w[2] : "null");
	o_r(",\"d_gain\":"); o_r(got ? w[3] : "null");
	o_r(",\"isp_d_gain\":"); o_r(got ? w[4] : "null");
	o_r(",\"dark_flag\":"); o_r(got ? w[5] : "null");
	o_r(",\"index\":"); if (got) o_n(idx); else o_r("null");
	o_r(",\"vendor_lum\":"); if (got) o_n(lum); else o_r("null");
	o_r(",\"vendor_night\":"); o_r(v[DN_VN]);
	o_r(",\"vendor_day\":"); o_r(v[DN_VD]);
	o_r(",\"ir_max_on\":"); o_r(v[DN_IR]);
	o_r(",\"night_style\":"); o_r(v[DN_NS]);
	o_r(",\"lowlight_fps\":"); o_r(v[DN_LF]);
	o_r(",\"lowlight_fps_value\":"); o_r(v[DN_LV]);
	o_r(",\"ir_led_mode\":\""); o_r(irm);
	o_r("\",\"night_720p\":"); o_r(v[DN_N7]);
	o_r("}\n");
	return !st_bail;
}

/* ---- hw_state ---- */
/* _hs_bool: 0 -> false, digits -> true, anything else -> null */
static const char *hs_bool(const char *s)
{
	return !slen_eq(s, "0") ? "false" : isdig(s, slen(s)) ? "true" : "null";
}

/* _hs_led: `read -r v < a || read -r v < b`. The second file is read when the first is missing, empty or without a
 * newline; a missing second file leaves what the first read gave. */
static const char *hs_led(const char *a, const char *b, char *v, int max)
{
	char w[40];
	int t = 1, s = st_first(a, v, max, &t);

	if (!(s == 1 && t) && st_first(b, w, sizeof w, 0)) scpy(v, w);	/* w is not longer than v */
	return hs_bool(v);
}

/* `[ -f pid ] && kill -0 "$(cat pid)"`: 1 = that process is there. One number and its newlines; anything else (an
 * empty file: busybox kill takes "" as 0, its own group) is left to the shell. */
static int hs_alive(const char *path)
{
	char b[32];
	long fd = sc(SYS_open, (long)P(path), O_RDONLY, 0, 0, 0), n;
	int i, d;

	if (fd < 0) return 0;
	n = sc(SYS_read, fd, (long)b, sizeof b, 0, 0);
	sc(SYS_close, fd, 0, 0, 0, 0);
	if (n < 0 || n >= (long)sizeof b) { st_bail = __LINE__; return 0; }
	b[n] = 0;
	for (d = 0; b[d] >= '0' && b[d] <= '9'; d++) ;
	for (i = d; b[i] == '\n'; i++) ;
	if (i != n || !d || d > 9 || b[0] == '0') { st_bail = __LINE__; return 0; }
	b[d] = 0;
	return sc(SYS_kill, num(b), 0, 0, 0, 0) == 0;
}

/* the line audit_log of action.cgi appends: "<btime + uptime> cmd=hw_state ip=<address>". 0 = left to the shell (no
 * /tmp/log yet, or a log to rotate: more than 64 KB) */
static int hs_audit(void)
{
	char ln[96];
	int l = fmt_u(ln, st_now);
	long fd, sz;

	cat(ln, &l, sizeof ln, " cmd=hw_state ip=");
	for (int i = 3; i >= 0; i--) { l += fmt_u(ln + l, pl_ip >> (8 * i) & 255); ln[l++] = i ? '.' : '\n'; }
	fd = sc(SYS_open, (long)P("/tmp/log/audit.log"), O_WRONLY | O_CREAT | O_APPEND, 0644, 0, 0);
	if (fd < 0) return 0;
	sz = sc(SYS_lseek, fd, 0, 2 /* SEEK_END */, 0, 0);
	if (sz >= 0 && sz <= 65536) sz = sc(SYS_write, fd, (long)ln, l, 0, 0) == l;
	else sz = 0;
	sc(SYS_close, fd, 0, 0, 0, 0);
	return (int)sz;
}

static int hs_json(const char *root)
{
	char tk[80], fl[40], rl[40], ir[40], cut[40], snd[120], btn[40], *p, *ts, *lv;
	const char *front, *red, *db = "null", *button = "null";
	struct ts now = { 0, 0 };
	int i, alive;

	st_root = root ? root : "";
	st_bail = 0;
	sl = SO0;
	/* csrf_guard, GET: a clean token returns at once; no token, or an unclean one, is rewritten by the shell */
	if (st_first("/tmp/csrf_token", tk, sizeof tk, 0) != 1 || !tk[0]) return 0;
	for (i = 0; tk[i]; i++)
		if (!((tk[i] >= '0' && tk[i] <= '9') || (tk[i] >= 'a' && tk[i] <= 'f') || (tk[i] >= 'A' && tk[i] <= 'F'))) return 0;
	if (!st_exists("/mnt/scripts/action.d/hardware.sh")) return 0;	/* "Unsupported command" */
	st_clock();	/* the time of the audit line */
	front = hs_led("/sys/class/leds/blue_led/brightness", "/sys/class/leds/blue/brightness", fl, sizeof fl);
	red = hs_led("/sys/class/leds/red_led/brightness", "/sys/class/leds/red/brightness", rl, sizeof rl);
	st_first("/sys/class/leds/ir/brightness", ir, sizeof ir, 0);
	st_first("/var/run/ircut", cut, sizeof cut, 0);
	alive = hs_alive("/var/run/auto-night-detection.pid");
	/* the microphone level, "<epoch> <dB>", while it is at most 10 s old (the real clock, as `date +%s`) */
	if (st_first("/var/run/sound_level", snd, sizeof snd, 0) == 1) {
		p = snd;
		ts = tok(&p);
		lv = tok(&p);
		if (isdig(ts, slen(ts))) {
			s64 age;

			if (dn_oct(ts)) st_bail = __LINE__;
			sc(SYS_clock_gettime, 0 /* CLOCK_REALTIME */, (long)&now, 0, 0, 0);
			age = (s64)now.sec - (s64)pnum(ts);
			if (age <= 10 && (!slen_eq(lv, "0") || (lv[0] == '-' && lv[1] >= '0' && lv[1] <= '9'))) {
				for (i = 0; lv[i]; i++) if ((unsigned char)lv[i] < ' ' || lv[i] == 127) st_bail = __LINE__;
				db = lv;
			}
		}
	}
	if (st_first("/sys/class/gpio/gpio522/value", btn, sizeof btn, 0))
		button = !slen_eq(btn, "0") ? "true" : !slen_eq(btn, "1") ? "false" : "null";
	if (st_bail) return 0;

	o_r("{\"ok\":true,\"front_led\":"); o_r(front);
	o_r(",\"red_led\":"); o_r(red);
	o_r(",\"ir_led\":"); o_r(hs_bool(ir));
	o_r(",\"ir_cut\":"); o_r(!slen_eq(cut, "0") || !slen_eq(cut, "1") ? cut : "null");
	o_r(",\"auto_daynight\":"); o_r(alive ? "true" : "false");
	o_r(",\"sound_db\":");
	for (; *db; db++) o_c(*db);	/* printf %s: as it is, a backslash or a quote included */
	o_r(",\"button\":"); o_r(button);
	o_r("}\n");
	return !st_bail && hs_audit();
}

/* route 3 or 4 of pl_route: the whole response, 0 = fall through */
static const char *poll_response(int route, const char *root, u32 ip, int *len)
{
	static const char h1[] = "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nPragma: no-cache\r\n"
		"Cache-Control: max-age=0, no-store, no-cache\r\nConnection: close\r\nContent-Length: ";

	pl_ip = ip;
	return (route == 3 ? dn_json(root) : hs_json(root)) ? wrap_response(h1, len) : 0;
}

#pragma GCC pop_options
#endif
