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

	if (pfx(b, "GET /cgi-bin/health.cgi") && (b[23] == ' ' || b[23] == '?')) return 5;
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
	if (*e != ' ') return 0;	/* cut by the end of the peeked bytes: not ours */
	if (r == 4) return pl_is(fmt, fl, "json") && pl_is(cmd, cl, "hw_state") ? 4 : 0;
	if (pl_is(cmd, cl, "fullconfig")) return 7;
	if (!pl_is(fmt, fl, "json")) return 0;
	return pl_is(cmd, cl, "daynight") ? 3 : pl_is(cmd, cl, "isp_tune") ? 6 : 0;
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
 * line counts even without a newline. Only the keys in `keys` are kept. */
static void pl_conf(const char *file, const char *const *keys, int nk, char (*v)[DW])
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
		for (i = 0; i < nk; i++) {
			const char *w = keys[i];
			int e;

			if (n) {
				if (!pfx(w, sec) || w[n] != '_') continue;
				w += n + 1;
			}
			if (slen_eq(w, k)) continue;
			e = slen(val);
			if (e && val[e - 1] == '=') st_bail = __LINE__;	/* IFS='=' read: shells differ */
			else if (e < DW) scpy(v[i], val);
			else st_bail = __LINE__;
		}
	}
	lr_close(&r);
}

static void dn_conf(const char *file, char v[DN_N][DW]) { pl_conf(file, dn_key, DN_N, v); }

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

/* ---- health.cgi cache hit ---- */
static int hc_json(const char *root)
{
	struct lr r;
	char iv[40], *l, *p, *ts;
	int t;
	u64 ttl = 75, cts, age;

	st_root = root ? root : "";
	st_bail = 0;
	sl = SO0;
	if (st_first("/tmp/health_snapshot.interval", iv, sizeof iv, &t) == 1) {
		if (!t) return 0;
		if (isdig(iv, slen(iv))) {
			u64 v = pnum(iv);

			if (st_bail) return 0;
			if (v >= 10 && v <= 300) ttl = v + 15;
		}
	}
	st_clock();
	if (st_bail) return 0;
	if (!lr_open(&r, "/tmp/health_snapshot.cache")) return 0;
	l = lr_get(&r, &t);
	if (!l || r.cut) { lr_close(&r); return 0; }
	p = l;
	ts = tok(&p);
	cts = pnum(ts);
	if (st_bail || st_now < cts) { lr_close(&r); return 0; }
	age = st_now - cts;
	if (age >= ttl) { lr_close(&r); return 0; }
	while ((l = lr_get(&r, &t))) {
		if (r.cut) { lr_close(&r); return 0; }
		if (t || l[0]) { o_r(l); o_c('\n'); }
	}
	lr_close(&r);
	return !st_bail && sl > SO0;
}

/* ---- isp_tune (route 6) ---- */
enum {
	IT_BRI, IT_CON, IT_SAT, IT_SHA, IT_DEN, IT_HUE, IT_HZ, IT_EXP,
	IT_M1, IT_M2, IT_M3, IT_M4, IT_MC,
	IT_EXN, IT_EXO, IT_HZB, IT_MSKS, IT_MRC, IT_N
};
static const char *const it_key[IT_N] = {
	"BRIGHTNESS", "CONTRAST", "SATURATION", "SHARPNESS", "DENOISE", "HUE", "POWER_HZ", "EXPOSURE_MAX_PCT",
	"MASK1", "MASK2", "MASK3", "MASK4", "MASK_COLOR",
	"EXPOSURE_NOW", "EXPOSURE_ORIG", "POWER_HZ_BASE", "MASKS", "MASK_RC"
};

static void it_read_first(const char *file, int nk, char (*v)[DW])
{
	struct lr r;
	char *l, *k, *val;
	int t, i, seen[IT_N];

	for (i = 0; i < nk; i++) { v[i][0] = 0; seen[i] = 0; }
	if (!lr_open(&r, file)) return;
	while ((l = lr_get(&r, &t))) {
		if (r.cut) { st_bail = __LINE__; break; }
		k = kvsplit(l, &val);
		for (i = 0; i < nk; i++) {
			if (!seen[i] && !slen_eq(k, it_key[i])) {
				int e = slen(val);

				seen[i] = 1;
				if (e < DW) scpy(v[i], val);
				else st_bail = __LINE__;
				break;
			}
		}
	}
	lr_close(&r);
}

static void it_out_num(const char *v)
{
	const char *p = v;

	if (!slen_eq(v, "auto")) { o_r("\"auto\""); return; }
	if (*p == '-') p++;
	if (!*p || !isdig(p, slen(p))) { o_r("null"); return; }
	o_r(v);
}

static int it_norm_signed50(const char *v, char *out)
{
	const char *p = v;
	u64 n;
	int neg = 0, l;

	if (!*v) { scpy(out, "0"); return 1; }
	if (*p == '-') { neg = 1; p++; }
	l = slen(p);
	if (!l || l > 2 || !isdig(p, l)) return 0;
	n = pnum(p);
	if (n > 50) return 0;
	if (n == 0) { scpy(out, "0"); return 1; }
	l = 0;
	if (neg) out[l++] = '-';
	if (n >= 10) out[l++] = (char)('0' + (int)udiv(n, 10));
	out[l++] = (char)('0' + (int)urem);
	out[l] = 0;
	return 1;
}

static void it_norm_mask(const char *v, char *out)
{
	const char *p = v;
	u64 c[4];
	int i, pos = 0;

	out[0] = 0;
	if (!*v) return;
	for (i = 0; i < 4; i++) {
		const char *s = p;
		int l;

		while (*p && *p != ',') p++;
		l = (int)(p - s);
		if (!l || l > 3 || !isdig(s, l)) return;
		if (dn_oct(s)) { st_bail = __LINE__; return; }
		c[i] = pnum(s);
		if (c[i] > 100) return;
		if (i < 3) { if (*p != ',') return; p++; }
		else if (*p) return;
	}
	if (c[2] <= c[0] || c[3] <= c[1]) return;
	for (i = 0; i < 4; i++) {
		u64 x = c[i];
		char t[4];
		int k = 0;

		if (i) out[pos++] = ',';
		do { u64 q = udiv(x, 10); t[k++] = (char)('0' + (int)urem); x = q; } while (x);
		while (k > 0) out[pos++] = t[--k];
	}
	out[pos] = 0;
}

static int it_json(const char *root)
{
	struct lr r;
	char v[IT_N][DW], norm[32], *l, *k, *val;
	int t, i, en = 0, has_st = 0;

	st_root = root ? root : "";
	st_bail = 0;
	sl = SO0;
	if (lr_open(&r, "/mnt/config/boot.conf")) {
		while ((l = lr_get(&r, &t))) {
			if (r.cut) { st_bail = __LINE__; break; }
			k = kvsplit(l, &val);
			if (!slen_eq(k, "ISP_TUNE")) {
				en = !slen_eq(val, "1") || !slen_eq(val, "true") || !slen_eq(val, "yes") ||
				     !slen_eq(val, "on") || !slen_eq(val, "enabled");
				break;
			}
		}
		lr_close(&r);
	}
	it_read_first("/mnt/config/isp_tune.conf", IT_MC + 1, v);
	o_r("{\"enabled\":"); o_c(en ? '1' : '0'); o_r(",\"conf\":{");
	for (i = 0; i < 8; i++) {
		if (i) o_c(',');
		o_c('"'); o_r(it_key[i]); o_r("\":");
		if (i < 6) {
			if (it_norm_signed50(v[i], norm)) it_out_num(norm);
			else o_r("null");
		} else if (i == IT_HZ) {
			if (!v[i][0] || !slen_eq(v[i], "50") || !slen_eq(v[i], "60") || !slen_eq(v[i], "auto"))
				it_out_num(v[i]);
			else o_r("null");
		} else {
			int l2 = slen(v[i]);
			u64 x;

			if (!v[i][0] || !slen_eq(v[i], "0")) o_r("null");
			else if (l2 <= 3 && isdig(v[i], l2) && (x = pnum(v[i])) >= 10 && x <= 100) {
				if (dn_oct(v[i])) st_bail = __LINE__;
				else o_n(x);
			} else o_r("null");
		}
	}
	for (i = IT_M1; i <= IT_MC; i++) {
		o_r(",\""); o_r(it_key[i]); o_r("\":\"");
		if (i < IT_MC) { it_norm_mask(v[i], norm); o_r(norm); }
		else if (!slen_eq(v[i], "black") || !slen_eq(v[i], "gray") || !slen_eq(v[i], "white")) o_r(v[i]);
		o_c('"');
	}
	o_r("},\"applied\":");
	if (lr_open(&r, "/var/run/isp_tune.status")) {
		lr_close(&r);
		has_st = 1;
	}
	if (has_st) {
		int sep = 0;

		it_read_first("/var/run/isp_tune.status", IT_N, v);
		o_c('{');
		for (i = 0; i < IT_N; i++) {
			if (i >= IT_M1 && i <= IT_MC) continue;
			if (!v[i][0]) continue;
			if (sep) o_c(',');
			sep = 1;
			o_c('"'); o_r(it_key[i]); o_r("\":");
			it_out_num(v[i]);
		}
		o_c('}');
	} else o_r("null");
	o_r("}\n");
	return !st_bail;
}

/* ---- fullconfig (route 7) ---- */
enum {
	FC_ST, FC_LM, FC_SH, FC_RL, FC_SWD, FC_RSE, FC_RSH, FC_RSM, FC_RSW,
	FC_MGE, FC_MGW, FC_MGC, FC_MGI, FC_MGWH, FC_MGCH, FC_MGCD,
	FC_SYE, FC_SYH, FC_SYP, FC_TOP, FC_IPR, FC_LCP,
	FC_PORT, FC_0C, FC_0P, FC_0MR, FC_0F, FC_0B, FC_0G, FC_0BM, FC_0MN, FC_0MX,
	FC_0SM, FC_0SG, FC_0SQ, FC_0SS, FC_0MK, FC_0TK, FC_0VB, FC_0SMT, FC_0OFS, FC_0OX, FC_0OY,
	FC_1C, FC_1P, FC_1W, FC_1H, FC_1F, FC_1B, FC_1G, FC_1BM, FC_1MN, FC_1MX,
	FC_1SM, FC_1SG, FC_1SQ, FC_1SS, FC_1MK, FC_1TK,
	FC_2C, FC_3C, FC_FLIP, FC_SR, FC_VOL, FC_OE, FC_OT, FC_OA, FC_OFC, FC_OBC, FC_OEC, FC_TLI, FC_TLD,
	FC_MQE, FC_MQH, FC_MQP, FC_MQU, FC_MQT, FC_MQD, FC_MQDP,
	FC_MDS, FC_MTL, FC_MBS, FC_LN, FC_DA, FC_LD, FC_NA, FC_TP,
	FC_SDE, FC_SDT, FC_SDI, FC_RPR, FC_RFD, FC_RMB, FC_RMA,
	FC_TGE, FC_TGA, FC_TGC, FC_FGU, FC_FGC, FC_N
};
static const char *const fc_key[FC_N] = {
	"SERVICE_TRIM", "LIGHTWEIGHT_MODE", "SECURITY_HARDENING_MODE", "RTSPLOGENABLED", "SETUP_WIZARD_DONE",
	"REBOOT_SCHEDULE_ENABLE", "REBOOT_SCHEDULE_HOUR", "REBOOT_SCHEDULE_MINUTE", "REBOOT_SCHEDULE_WEEKDAY",
	"MEM_GUARD_ENABLE", "MEM_GUARD_WARN_KB", "MEM_GUARD_CRITICAL_KB", "MEM_GUARD_INTERVAL_SECONDS",
	"MEM_GUARD_WARN_HITS", "MEM_GUARD_CRITICAL_HITS", "MEM_GUARD_COOLDOWN_SECONDS",
	"SYSLOG_ENABLE", "SYSLOG_HOST", "SYSLOG_PORT", "STREAM_TOPOLOGY", "INTEGRATION_PROFILE", "LOW_CPU_PROFILE",
	"PORT", "0_codec", "0_profile", "0_mainres", "0_fps", "0_bps", "0_goplen", "0_brmode", "0_minqp", "0_maxqp",
	"0_smartmode", "0_smartgoplen", "0_smartquality", "0_smartstatic", "0_maxkbps", "0_targetkbps", "0_vbr", "0_smart",
	"0_osdfontsize", "0_osdx", "0_osdy",
	"1_codec", "1_profile", "1_width", "1_height", "1_fps", "1_bps", "1_goplen", "1_brmode", "1_minqp", "1_maxqp",
	"1_smartmode", "1_smartgoplen", "1_smartquality", "1_smartstatic", "1_maxkbps", "1_targetkbps",
	"2_codec", "3_codec", "imageflip", "samplerate", "volume", "osdenabled", "osdtext", "osdalpha",
	"osdfrontcolor", "osdbackcolor", "osdedgecolor", "tlinterval", "tlduration",
	"MQTT_ENABLE", "MQTT_HOST", "MQTT_PORT", "MQTT_USER", "MQTT_TOPIC_ROOT", "MQTT_HA_DISCOVERY_ENABLE", "MQTT_HA_DISCOVERY_PREFIX",
	"mdsens", "motion_trigger_led", "motion_best_shot",
	"LUMA_NIGHT", "daynightawb", "LUMA_DAY", "nightdayawb", "TELNET_PORT",
	"ENABLE", "THRESHOLD_DB", "INTERVAL",
	"rec_postrecord_sec", "rec_file_duration_sec", "rec_reserverd_disk_mb", "rec_motion_activated",
	"TELEGRAM_ENABLE", "apiToken", "userChatId", "FRIGATE_URL", "FRIGATE_CAMERA"
};

static const char *fc_int(const char *s, const char *def) { return (*s && isdig(s, slen(s))) ? s : def; }
static const char *fc_str(const char *s, const char *def) { return *s ? s : def; }
static char fc_bool(const char *s, char def)
{
	if (!*s) return def;
	return (!slen_eq(s, "1") || !slen_eq(s, "true") || !slen_eq(s, "on") || !slen_eq(s, "yes") || !slen_eq(s, "enabled")) ? '1' : '0';
}

static void fc_single(const char *file, const char *def, char *out)
{
	struct lr r;
	char *l;
	int t;

	scpy(out, def);
	if (!lr_open(&r, file)) return;
	while ((l = lr_get(&r, &t))) {
		if (r.cut) { st_bail = __LINE__; break; }
		if (!l[0] || l[0] == '#') continue;
		if (slen(l) >= DW) { st_bail = __LINE__; break; }
		scpy(out, l);
		break;
	}
	lr_close(&r);
}

static void fc_gw(char *out)
{
	struct lr r;
	char *l, *p, *w1, *w2, *w3;
	int t;

	scpy(out, "n/a");
	if (!lr_open(&r, "/proc/net/route")) return;
	while ((l = lr_get(&r, &t))) {
		if (r.cut) break;
		p = l;
		w1 = tok(&p); w2 = tok(&p); w3 = tok(&p);
		(void)w1;
		if (slen_eq(w2, "00000000")) continue;
		if (slen(w3) != 8 || !slen_eq(w3, "00000000")) continue;
		{
			u32 v = 0;
			int ok = 1, i, pos = 0;

			for (i = 0; i < 8; i++) {
				char c = w3[i];
				u32 d;

				if (c >= '0' && c <= '9') d = (u32)(c - '0');
				else if (c >= 'a' && c <= 'f') d = (u32)(c - 'a' + 10);
				else if (c >= 'A' && c <= 'F') d = (u32)(c - 'A' + 10);
				else { ok = 0; break; }
				v = (v << 4) | d;
			}
			if (!ok) continue;
			for (i = 0; i < 4; i++) {
				u32 b = (v >> (i * 8)) & 0xff;
				char d[4];
				int k = 0;

				if (i) out[pos++] = '.';
				do { u64 q = udiv(b, 10); d[k++] = (char)('0' + (int)urem); b = (u32)q; } while (b);
				while (k > 0) out[pos++] = d[--k];
			}
			out[pos] = 0;
			break;
		}
	}
	lr_close(&r);
}

static char fc_led(const char *p1, const char *p2)
{
	char b[16];

	if (!st_first(p1, b, sizeof b, 0) && !st_first(p2, b, sizeof b, 0)) return '0';
	return !slen_eq(b, "1") ? '1' : '0';
}

static int fc_json(const char *root)
{
	static const char *const files[11] = {
		"/mnt/config/boot.conf", "/mnt/config/rtspserver.conf", "/mnt/config/mqtt.conf",
		"/mnt/config/service_trim.conf", "/mnt/config/motion.conf", "/mnt/config/daynight.conf",
		"/mnt/config/telnetd.conf", "/mnt/config/sound_detection.conf", "/mnt/config/recording.conf",
		"/mnt/config/telegram.conf", "/mnt/config/frigate_live.conf"
	};
	char v[FC_N][DW], host[DW], tz[DW], ntp[DW], gw[24];
	const char *fps0, *c0, *c1, *w0, *h0, *pp, *sdi, *sdb;
	int i, main_720;
	struct lr r;

	st_root = root ? root : "";
	st_bail = 0;
	sl = SO0;
	for (i = 0; i < FC_N; i++) v[i][0] = 0;
	for (i = 0; i < 11; i++) {
		if ((i == 8 || i == 9) && !slen_eq(v[FC_IPR], "frigate_ha")) continue;
		pl_conf(files[i], fc_key, FC_N, v);
	}
	fc_single("/mnt/config/hostname.conf", "TC100-CAMERA", host);
	fc_single("/mnt/config/timezone.conf", "UTC+0", tz);
	fc_single("/mnt/config/ntp_srv.conf", "pool.ntp.org", ntp);
	fc_gw(gw);

	pp = fc_bool(v[FC_ST], '0') == '1' ? "rtsp-only" : fc_bool(v[FC_LCP], '0') == '1' ? "low-cpu" : "balanced";
	main_720 = 0;
	if (lr_open(&r, "/sys/module/ak39_vi/parameters/main_scale")) { lr_close(&r); main_720 = 1; }
	if (main_720 && !slen_eq(fc_int(v[FC_0MR], "1080"), "720")) { w0 = "1280"; h0 = "720"; }
	else { w0 = "1920"; h0 = "1080"; }
	fps0 = fc_int(v[FC_0F], "16");
	if (slen_eq(fps0, "10") && slen_eq(fps0, "12") && slen_eq(fps0, "15") && slen_eq(fps0, "20") && slen_eq(fps0, "25"))
		fps0 = "15";
	c0 = fc_int(v[FC_0C], "2");
	c1 = fc_int(v[FC_1C], "0");
	if (!v[FC_SDI][0]) sdi = "2";
	else if (isdig(v[FC_SDI], slen(v[FC_SDI]))) sdi = v[FC_SDI];
	else sdi = "5";
	sdb = v[FC_SDT];
	if (slen_eq(sdb, "0") && !(sdb[0] == '-' && sdb[1] >= '0' && sdb[1] <= '9' &&
	    (!sdb[2] || (sdb[2] >= '0' && sdb[2] <= '9' && !sdb[3]))))
		sdb = "-24";

	if (st_bail) return 0;
	o_r("{\"boot\":{\"perf_profile\":\""); o_r(pp);
	o_r("\",\"service_trim\":"); o_c(fc_bool(v[FC_ST], '0'));
	o_r(",\"topology\":\""); o_e(fc_str(v[FC_TOP], "dual"));
	o_r("\",\"lightweight_mode\":"); o_c(fc_bool(v[FC_LM], '0'));
	o_r(",\"security_hardening\":"); o_c(fc_bool(v[FC_SH], '0'));
	o_r("},\"video\":{\"rtsp_port\":"); o_r(fc_int(v[FC_PORT], "554"));
	o_r(",\"main_720\":"); o_r(main_720 ? "true" : "false");
	o_r(",\"main\":{\"codec\":"); o_r(c0);
	o_r(",\"profile\":"); o_r(fc_int(v[FC_0P], "3"));
	o_r(",\"width\":"); o_r(w0); o_r(",\"height\":"); o_r(h0);
	o_r(",\"fps\":"); o_r(fps0);
	o_r(",\"bitrate\":"); o_r(fc_int(v[FC_0B], "1000"));
	o_r(",\"gop\":"); o_r(fc_int(v[FC_0G], "50"));
	o_r(",\"format\":\""); o_r(fc_int(v[FC_0BM], "1"));
	o_r("\",\"minqp\":"); o_r(fc_int(v[FC_0MN], "20"));
	o_r(",\"maxqp\":"); o_r(fc_int(v[FC_0MX], "51"));
	o_r(",\"smartmode\":"); o_r(fc_int(v[FC_0SM], "1"));
	o_r(",\"smartgoplen\":"); o_r(fc_int(v[FC_0SG], "0"));
	o_r(",\"smartquality\":"); o_r(fc_int(v[FC_0SQ], "100"));
	o_r(",\"smartstatic\":"); o_r(fc_int(v[FC_0SS], "500"));
	o_r(",\"maxkbps\":"); o_r(fc_int(v[FC_0MK], "1500"));
	o_r(",\"targetkbps\":"); o_r(fc_int(v[FC_0TK], "1200"));
	o_r(",\"vbr\":"); o_r(fc_int(v[FC_0VB], "0"));
	o_r(",\"smart\":"); o_r(fc_int(v[FC_0SMT], "0"));
	o_r("},\"sub\":{\"codec\":"); o_r(c1);
	o_r(",\"profile\":"); o_r(fc_int(v[FC_1P], "0"));
	o_r(",\"width\":640,\"height\":360,\"fps\":"); o_r(fps0);
	o_r(",\"bitrate\":"); o_r(fc_int(v[FC_1B], "250"));
	o_r(",\"gop\":"); o_r(fc_int(v[FC_1G], "32"));
	o_r(",\"format\":\""); o_r(fc_int(v[FC_1BM], "1"));
	o_r("\",\"minqp\":"); o_r(fc_int(v[FC_1MN], "20"));
	o_r(",\"maxqp\":"); o_r(fc_int(v[FC_1MX], "51"));
	o_r(",\"smartmode\":"); o_r(fc_int(v[FC_1SM], "1"));
	o_r(",\"smartgoplen\":"); o_r(fc_int(v[FC_1SG], "0"));
	o_r(",\"smartquality\":"); o_r(fc_int(v[FC_1SQ], "50"));
	o_r(",\"smartstatic\":"); o_r(fc_int(v[FC_1SS], "150"));
	o_r(",\"maxkbps\":"); o_r(fc_int(v[FC_1MK], "450"));
	o_r(",\"targetkbps\":"); o_r(fc_int(v[FC_1TK], "400"));
	o_r("},\"flip\":"); o_r(fc_int(v[FC_FLIP], "0"));
	o_r(",\"rtsp_log\":"); o_c(fc_bool(v[FC_RL], '0'));
	o_r("},\"audio\":{\"samplerate\":"); o_r(fc_int(v[FC_SR], "8000"));
	o_r(",\"volume\":"); o_r(fc_int(v[FC_VOL], "8"));
	o_r(",\"codec_main\":"); o_r(fc_int(v[FC_2C], "4"));
	o_r(",\"codec_sub\":"); o_r(fc_int(v[FC_3C], "4"));
	o_r(",\"mic_sens\":"); o_r(fc_int(v[FC_VOL], "8"));
	o_r("},\"isp\":{\"daynight_lum\":"); o_r(fc_int(v[FC_LN], "40"));
	o_r(",\"daynight_awb\":"); o_r(fc_int(v[FC_DA], "100000"));
	o_r(",\"nightday_lum\":"); o_r(fc_int(v[FC_LD], "100"));
	o_r(",\"nightday_awb\":"); o_r(fc_int(v[FC_NA], "50000"));
	o_r("},\"osd\":{\"enabled\":"); o_c(fc_bool(v[FC_OE], '0'));
	o_r(",\"text\":\""); o_e(v[FC_OT]);
	o_r("\",\"alpha\":"); o_r(fc_int(v[FC_OA], "128"));
	o_r(",\"fontsize0\":"); o_r(fc_int(v[FC_0OFS], "24"));
	o_r(",\"frontcolor\":"); o_r(fc_int(v[FC_OFC], "1"));
	o_r(",\"backcolor\":"); o_r(fc_int(v[FC_OBC], "0"));
	o_r(",\"edgecolor\":"); o_r(fc_int(v[FC_OEC], "2"));
	o_r(",\"x0\":"); o_r(fc_int(v[FC_0OX], "10"));
	o_r(",\"y0\":"); o_r(fc_int(v[FC_0OY], "10"));
	o_r("},\"mqtt\":{\"enabled\":"); o_c(fc_bool(v[FC_MQE], '0'));
	o_r(",\"host\":\""); o_e(fc_str(v[FC_MQH], "127.0.0.1"));
	o_r("\",\"port\":"); o_r(fc_int(v[FC_MQP], "1883"));
	o_r(",\"user\":\""); o_e(v[FC_MQU]);
	o_r("\",\"topic_root\":\""); o_e(fc_str(v[FC_MQT], "tc100/camera"));
	o_r("\",\"discovery\":"); o_c(fc_bool(v[FC_MQD], '1'));
	o_r(",\"discovery_prefix\":\""); o_e(fc_str(v[FC_MQDP], "homeassistant"));
	o_r("\"},\"recording\":{\"postrec\":"); o_r(fc_int(v[FC_RPR], "10"));
	o_r(",\"maxduration\":"); o_r(fc_int(v[FC_RFD], "60"));
	o_r(",\"reserved_mb\":"); o_r(fc_int(v[FC_RMB], "1024"));
	o_r(",\"motion_activated\":"); o_c(fc_bool(v[FC_RMA], '0'));
	o_r("},\"system\":{\"hostname\":\""); o_e(host);
	o_r("\",\"timezone\":\""); o_e(tz);
	o_r("\",\"ntp_server\":\""); o_e(ntp);
	o_r("\",\"setup_wizard_done\":"); o_c(fc_bool(v[FC_SWD], '0'));
	o_r(",\"gateway\":\""); o_e(gw);
	o_r("\",\"reboot_schedule\":{\"enable\":"); o_c(fc_bool(v[FC_RSE], '0'));
	o_r(",\"hour\":"); o_r(fc_int(v[FC_RSH], "4"));
	o_r(",\"min\":"); o_r(fc_int(v[FC_RSM], "0"));
	o_r(",\"dow\":\""); o_e(fc_str(v[FC_RSW], "*"));
	o_r("\"},\"mem_guard\":{\"enable\":"); o_c(fc_bool(v[FC_MGE], '0'));
	o_r(",\"warn_kb\":"); o_r(fc_int(v[FC_MGW], "6144"));
	o_r(",\"crit_kb\":"); o_r(fc_int(v[FC_MGC], "3072"));
	o_r(",\"interval\":"); o_r(fc_int(v[FC_MGI], "20"));
	o_r(",\"hits_warn\":"); o_r(fc_int(v[FC_MGWH], "2"));
	o_r(",\"hits_crit\":"); o_r(fc_int(v[FC_MGCH], "1"));
	o_r(",\"cooldown\":"); o_r(fc_int(v[FC_MGCD], "120"));
	o_r("}},\"timelapse\":{\"interval\":"); o_r(fc_int(v[FC_TLI], "10"));
	o_r(",\"duration\":"); o_r(fc_int(v[FC_TLD], "0"));
	o_r("},\"services\":{\"telnet_port\":"); o_r(fc_int(v[FC_TP], "23"));
	o_r(",\"sound_det_enable\":"); o_c(fc_bool(v[FC_SDE], '0'));
	o_r(",\"sound_det_threshold\":"); o_r(sdb);
	o_r(",\"sound_det_interval\":"); o_r(sdi);
	o_r(",\"motion_sens\":"); o_r(fc_int(v[FC_MDS], "50"));
	o_r(",\"motion_led\":"); o_c(fc_bool(v[FC_MTL], '0'));
	o_r(",\"motion_best_shot\":"); o_c(fc_bool(v[FC_MBS], '0'));
	o_r("},\"telegram\":{\"enabled\":"); o_c(fc_bool(v[FC_TGE], '0'));
	o_r(",\"token\":\"\",\"token_set\":"); o_r(v[FC_TGA][0] ? "true" : "false");
	o_r(",\"chat_id\":\""); o_e(v[FC_TGC]);
	o_r("\"},\"syslog\":{\"enabled\":"); o_c(fc_bool(v[FC_SYE], '0'));
	o_r(",\"host\":\""); o_e(v[FC_SYH]);
	o_r("\",\"port\":"); o_r(fc_int(v[FC_SYP], "514"));
	o_r("},\"frigate\":{\"url\":\""); o_e(v[FC_FGU]);
	o_r("\",\"camera\":\""); o_e(v[FC_FGC]);
	o_r("\"},\"peripherals\":{\"led_front\":"); o_c(fc_led("/sys/class/leds/blue_led/brightness", "/sys/class/leds/blue/brightness"));
	o_r(",\"led_red\":"); o_c(fc_led("/sys/class/leds/red_led/brightness", "/sys/class/leds/red/brightness"));
	o_r("}}\n");
	return !st_bail;
}

/* route 3..7 of pl_route: the whole response, 0 = fall through */
static const char *poll_response(int route, const char *root, u32 ip, int *len)
{
	static const char h1[] = "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nPragma: no-cache\r\n"
		"Cache-Control: max-age=0, no-store, no-cache\r\nConnection: close\r\nContent-Length: ";

	pl_ip = ip;
	return (route == 3 ? dn_json(root) : route == 4 ? hs_json(root) : route == 5 ? hc_json(root) :
		route == 6 ? it_json(root) : fc_json(root)) ? wrap_response(h1, len) : 0;
}

#pragma GCC pop_options
#endif
