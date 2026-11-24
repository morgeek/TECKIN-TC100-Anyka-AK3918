/* poll.h: more polled reads answered by httpfront itself (same switch as status.h and dash.h: HTTPFRONT_NATIVE=1 ->
 * TC100_NATIVE_STATUS=1). Included by httpfront.c after dash.h; it uses the helpers of status.h.
 *
 *   GET /cgi-bin/state.cgi?cmd=daynight&format=json    (Settings -> Day/night, every 5 s)
 *   GET /cgi-bin/action.cgi?cmd=hw_state&format=json   (the Hardware page, every 2 s)
 *   GET /cgi-bin/health.cgi                            (Diagnostics: a fresh /tmp/health_snapshot.cache only)
 *   GET /cgi-bin/state.cgi?cmd=isp_tune&format=json    (Settings -> Image, isp_tune_json of scripts/isp-tune.sh)
 *
 * state.cgi?cmd=fullconfig (once per Settings open, kept 5 s by the CGI) is left to the CGI: its awk loader, the 5 s
 * perf_profile cache and the long values (URLs, OSD text) were not worth a port (audit 2026-11-24, section 5).
 *
 * Ports of the `daynight` arm of www/cgi-bin/state.cgi (with its load_conf_file and cfg_int) and of the `hw_state` arm of
 * scripts/action.d/hardware.sh behind www/cgi-bin/action.cgi, field by field, with the quirks of the shell (`read -r`
 * takes a last line without newline, `while read` does not, load_conf_file does, the last assignment of a key wins, a
 * [section] prefixes the keys). The rule is the one of status.h: an answer only when it is the exact answer of the CGI;
 * anything else returns 0 and the request goes to httpd and the CGI as before:
 *   - a query whose cmd or format is not plain text (%XX, +), or no format=json (the Accept header is left to the CGI);
 *   - a number the shell would read as octal, or a product that would wrap its 64 bits; a value ending in '='; a line or a value
 *     longer than the buffers;
 *   - hw_state: a missing or unclean /tmp/csrf_token (csrf_guard creates it), a pid file holding anything but one
 *     number, a control character in the level.
 * daynight: state.cgi keeps its answer 1 s in /tmp/state-response-daynight-json.cache; here the same files are read at
 * each request and nothing is written. hw_state: a read-only query, not noted in /tmp/log/audit.log by action.cgi
 * (W5, owner 2026-11-24), so nothing is written here either. */
#ifndef HF_POLL_H
#define HF_POLL_H

#pragma GCC push_options
#pragma GCC target("thumb")

#define SYS_lseek 19
#define SYS_kill 37


static int pl_is(const char *s, int n, const char *w) { return slen(w) == n && !cred_cmp(s, w, n); }

/* the request line against func.cgi's parsing of QUERY_STRING (words split on &, name before the first =, names of
 * [A-Za-z0-9_] only, the last value of a name wins): 3 = state.cgi cmd=daynight, 4 = action.cgi cmd=hw_state,
 * 6 = state.cgi cmd=isp_tune, all with format=json; 5 = health.cgi (any query); 0 = not ours */
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
 * line counts even without a newline. Only the keys of dn_key are kept. A value longer than the buffer that is not a
 * number becomes "?": daynight only compares its values with words and digits, and "?" is neither. */
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
	return !st_bail;
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

/* ---- isp_tune (route 6): isp_tune_json of scripts/isp-tune.sh ---- */
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

static int it_numch(char c) { return (c >= '0' && c <= '9') || c == '-'; }

/* isp_tune_get for the first nk keys at once: the value of the first line that starts with KEY= (IFS= read -r: the
 * line as it is, blanks and CR included, the last line without newline too), "" when there is none. A value longer
 * than the buffer made of digits and '-' only is printed as it is by the shell: not reproduced; any other long value
 * becomes "?", which _isp_num, the masks and the colours all reject as the shell rejects the long value. */
static void it_read_first(const char *file, int nk, char (*v)[DW])
{
	struct lr r;
	char *l;
	int t, i, seen[IT_N];

	for (i = 0; i < nk; i++) { v[i][0] = 0; seen[i] = 0; }
	if (!lr_open(&r, file)) return;
	while ((l = lr_get(&r, &t))) {
		if (r.cut) { st_bail = __LINE__; break; }
		for (i = 0; i < nk; i++) {
			int kl = slen(it_key[i]), e, j;
			const char *val;

			if (seen[i] || !pfx(l, it_key[i]) || l[kl] != '=') continue;
			seen[i] = 1;
			val = l + kl + 1;
			e = slen(val);
			if (e < DW) { scpy(v[i], val); continue; }
			for (j = 0; j < e && it_numch(val[j]); j++) ;
			if (j == e) st_bail = __LINE__;
			else scpy(v[i], "?");
		}
	}
	lr_close(&r);
}

/* _isp_num: auto -> "auto"; empty, or any character but 0-9 and '-' -> null; anything else as it is ("--5", "007") */
static void it_num(const char *v)
{
	const char *p;

	if (!slen_eq(v, "auto")) { o_r("\"auto\""); return; }
	for (p = v; *p && it_numch(*p); p++) ;
	o_r(*v && !*p ? v : "null");
}

/* isp_tune_norm MASKn: "" or "x1,y1,x2,y2" (each 0..100, x2 > x1, y2 > y1), else "". `IFS=, set -- $v`: a last comma
 * ends the last field and makes no empty one. The shell compares the fields in decimal ([ -le 100 ]) and then computes
 * them in $(( )), where a leading zero is octal (08 an error): such a mask is left to the shell. */
static void it_norm_mask(const char *v, char *out)
{
	const char *p, *f[4];
	int n = 0, i, pos = 0, l[4], oct = 0;
	u32 c[4];

	out[0] = 0;
	if (!*v) return;
	for (p = v; *p; p++) if (!((*p >= '0' && *p <= '9') || *p == ',')) return;
	for (p = v;;) {
		const char *s = p;

		while (*p && *p != ',') p++;
		if (n == 4) return;	/* a fifth field */
		f[n] = s; l[n] = (int)(p - s); n++;
		if (!*p || !*++p) break;
	}
	if (n != 4) return;
	for (i = 0; i < 4; i++) {
		if (!l[i] || l[i] > 3) return;
		c[i] = 0;
		for (int j = 0; j < l[i]; j++) c[i] = c[i] * 10 + (u32)(f[i][j] - '0');
		if (c[i] > 100) return;
		if (l[i] > 1 && f[i][0] == '0') oct = 1;
	}
	if (oct) { st_bail = __LINE__; return; }
	if (c[2] <= c[0] || c[3] <= c[1]) return;
	for (i = 0; i < 4; i++) {
		if (i) out[pos++] = ',';
		for (int j = 0; j < l[i]; j++) out[pos++] = f[i][j];
	}
	out[pos] = 0;
}

static int it_json(const char *root)
{
	struct lr r;
	char v[IT_N][DW], norm[DW], *l;
	int t, i, en = 0, sep;

	st_root = root ? root : "";
	st_bail = 0;
	sl = SO0;
	/* isp_tune_enabled: the first ISP_TUNE= line of boot.conf */
	if (lr_open(&r, "/mnt/config/boot.conf")) {
		while ((l = lr_get(&r, &t))) {
			if (r.cut) { st_bail = __LINE__; break; }
			if (pfx(l, "ISP_TUNE=")) { en = truthy(l + 9); break; }
		}
		lr_close(&r);
	}
	it_read_first("/mnt/config/isp_tune.conf", IT_MC + 1, v);
	o_r("{\"enabled\":"); o_c(en ? '1' : '0'); o_r(",\"conf\":{");
	for (i = 0; i <= IT_EXP; i++) {	/* the values as they are written, not normalized */
		if (i) o_c(',');
		o_c('"'); o_r(it_key[i]); o_r("\":");
		it_num(v[i]);
	}
	for (i = IT_M1; i <= IT_MC; i++) {
		o_r(",\""); o_r(it_key[i]); o_r("\":\"");
		if (i < IT_MC) { it_norm_mask(v[i], norm); o_r(norm); }
		else if (!v[i][0] || !slen_eq(v[i], "black") || !slen_eq(v[i], "gray") || !slen_eq(v[i], "white")) o_r(v[i]);
		o_c('"');
	}
	o_r("},\"applied\":");
	/* [ -r status ]: the keys of ISP_TUNE_KEYS, then the reports of tc100_rtsp; an empty one is left out */
	if (st_exists("/var/run/isp_tune.status")) {
		it_read_first("/var/run/isp_tune.status", IT_N, v);
		o_c('{');
		for (i = 0, sep = 0; i < IT_N; i++) {
			if ((i >= IT_M1 && i <= IT_MC) || !v[i][0]) continue;
			if (sep) o_c(',');
			sep = 1;
			o_c('"'); o_r(it_key[i]); o_r("\":");
			it_num(v[i]);
		}
		o_c('}');
	} else o_r("null");
	o_r("}\n");
	return !st_bail;
}

/* route 3..6 of pl_route: the whole response, 0 = fall through */
static const char *poll_response(int route, const char *root, u32 ip, int *len)
{
	static const char h1[] = "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nPragma: no-cache\r\n"
		"Cache-Control: max-age=0, no-store, no-cache\r\nConnection: close\r\nContent-Length: ";

	(void)ip;	/* the client address: no audit line any more (W5) */
	return (route == 3 ? dn_json(root) : route == 4 ? hs_json(root) : route == 5 ? hc_json(root) : it_json(root))
		? wrap_response(h1, len) : 0;
}

#pragma GCC pop_options
#endif
