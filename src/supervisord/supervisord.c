/* tc100-supervisord: the resident shell loops of the camera in one small process (option SUPERVISOR_IMPL=c in
 * config/boot.conf; the default is the shell scripts, which stay as the fallback).
 *
 * Jobs (each one is switched on by a flag file, so the service scripts keep their own start/stop):
 *   night   scripts/auto-night-daemon.sh: automatic day/night from /tmp/cam_luma, /tmp/cam_ae, /tmp/cam_awb with the
 *           same sources (luma, ae, isp, vendor), hold times, hysteresis, minimum time between two switches, IR LED
 *           protection and calibration log. Switching is still done by scripts/nightmode.sh (called, not rewritten).
 *   button  scripts/button-watch.sh (GPIO poll of Linux 6.6): the reset button on GPIO 10 (sysfs gpio522, active low)
 *           read once a second; acts on release: 3-7 s rescue Wi-Fi access point, 8-19 s reboot, 20 s + reboot (from
 *           the flash firmware first back to the built-in code). Complex work stays in the scripts it calls
 *           (wifi-rescue.sh, reboot-tracker.sh, flash-code.sh).
 *   sound   controlscripts/sound-detection (its run_daemon loop): the microphone level of tc100_rtsp (/var/run/sound_level)
 *           becomes "sound" events through the same scripts (mqtt-bridge.sh publish, notify.sh, snapshot-event), the VOX
 *           (babyphone) and alarm-tone states, the REC_WHEN=motion trigger; config/sound_detection.conf.
 * Both read the same files as the shell versions (config/daynight.conf, rtspserver.conf daynight=): no new keys.
 * Every shell loop replaced is one busybox ash process less in RAM (the loops woke up every 1 to 8 s and forked).
 *
 * Environment (same names as the scripts; the shell ones double as test hooks): DN_CONSOLE DN_CONF DN_RTSPCONF CAM_AE
 * CAM_LUMA CAM_AWB DN_IRCUT DN_NIGHTMODE DN_LOG DN_LOG_EVERY, BUTTON_GPIO_DIR BUTTON_L66_FLAG BUTTON_DEV
 * BUTTON_REBOOT_SECONDS BUTTON_RESTORE_SECONDS BUTTON_RESCUE_SECONDS BUTTON_FLASH_CODE BUTTON_REBOOT_CMD BUTTON_RESCUE
 * BUTTON_TRACKER TC100_STORAGE_FILE; SV_NIGHT_FLAG SV_BUTTON_FLAG SV_SOUND_FLAG SV_PIDFILE for the flag and pid files; the sound job: SD_CONF SD_LOG SD_STATE
 * SOUND_LEVEL_FILE SD_SCRIPTS SD_MQTTCONF SD_BOOTCONF SD_VOX SD_ALARM SD_MOTION SD_UPTIME EVENT_COOLDOWN_SECONDS LOG_MAX_BYTES
 * LOG_BACKUPS.
 * Test mode: tc100-supervisord -r SCRIPT replays commands (now, write, writen, writeml, rm, cat, echo, night, button, sdreset, sound) with a
 * clock of its own: tests/test_supervisord.py compares it with the shell scripts.
 *
 * Built like src/mqttd (glibc cross compiler, run under the uClibc loader of the camera, see the Makefile): only old
 * plain libc calls, no stat, no scanf or strto* parsing, no libm. Host build: cc -O1 -Wall -Wextra -o x supervisord.c
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <utime.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

typedef long long ll;

static int g_replay, g_div = 1;	/* g_div: test hook, SV_TICK_DIV divides every wait (the clock of the hold times is not scaled) */
static volatile sig_atomic_t g_stop;
static ll NOW;

static const char *envs(const char *name, const char *def)
{
	const char *v = getenv(name);

	return v && *v ? v : def;
}

static ll mono_ms(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return (ll)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

static int all_digits(const char *s)
{
	if (!*s) return 0;
	for (; *s; s++) if (*s < '0' || *s > '9') return 0;
	return 1;
}

static ll dec(const char *s)	/* decimal digits, saturating (the shell used 64-bit arithmetic) */
{
	ll v = 0;

	for (; *s >= '0' && *s <= '9'; s++) {
		if (v > 100000000000000000LL) return v;
		v = v * 10 + (*s - '0');
	}
	return v;
}

static int env_num(const char *name, int def)	/* ${NAME:-def}, plain digits only */
{
	const char *v = getenv(name);

	return v && all_digits(v) && strlen(v) <= 9 ? (int)dec(v) : def;
}

/* ---- files ---- */

static int slurp(const char *path, char *buf, int cap)	/* length, -1 when it cannot be read; NUL-terminated */
{
	int f = open(path, O_RDONLY), n = 0, r;

	if (f < 0) return -1;
	while (n < cap - 1 && (r = read(f, buf + n, cap - 1 - n)) > 0) n += r;
	close(f);
	buf[n] = 0;
	return n;
}

/* `read -r VAR < file` with the default IFS: the first line without its leading and trailing blanks. Returns -1 when
 * the file cannot be read, 0 when the line ended with a newline, 1 when the file ended first (read returns 1 then,
 * but still sets the variable). */
static int first_line(const char *path, char *out, int cap)
{
	char b[1024], *e, *s = b;
	int n = slurp(path, b, sizeof b), nl;

	if (n < 0) return -1;
	e = memchr(b, '\n', n);
	nl = e != NULL;
	if (!e) e = b + n;
	*e = 0;
	while (*s == ' ' || *s == '\t') s++;
	e = s + strlen(s);
	while (e > s && (e[-1] == ' ' || e[-1] == '\t')) e--;
	*e = 0;
	snprintf(out, cap, "%s", s);
	return nl ? 0 : 1;
}

static void console(const char *fmt, ...)	/* echo ... > $CONSOLE */
{
	char b[512];
	va_list ap;
	int n, f;

	va_start(ap, fmt);
	n = vsnprintf(b, sizeof b - 1, fmt, ap);
	va_end(ap);
	if (n < 0) return;
	if (n > (int)sizeof b - 2) n = sizeof b - 2;
	b[n++] = '\n';
	f = open(envs("DN_CONSOLE", "/dev/console"), O_WRONLY | O_CREAT | O_TRUNC | O_NOCTTY, 0644);
	if (f >= 0) { if (write(f, b, n) < 0) {} close(f); }
}

/* ---- running the scripts ---- */

/* fork + exec with stdio on /dev/null: the pid, -1 on failure */
static pid_t spawn(const char *const *argv)
{
	pid_t pid = fork();

	if (pid < 0) return -1;
	if (pid == 0) {
		int nul = open("/dev/null", O_RDWR);

		if (nul >= 0) { dup2(nul, 0); dup2(nul, 1); dup2(nul, 2); if (nul > 2) close(nul); }
		signal(SIGTERM, SIG_DFL);
		signal(SIGINT, SIG_DFL);
		execv(argv[0], (char *const *)argv);
		if (errno == ENOEXEC) {	/* a script without #!: the shell would have run it with sh */
			const char *a[8];
			int i;

			a[0] = "/bin/sh";
			for (i = 0; argv[i] && i < 6; i++) a[i + 1] = argv[i];
			a[i + 1] = NULL;
			execv(a[0], (char *const *)a);
		}
		_exit(127);
	}
	return pid;
}

/* spawn + wait: the exit status (0 at once when not waiting), -1 on failure */
static int run(const char *const *argv, int wait_it)
{
	int st = 0, r;
	pid_t pid = spawn(argv);

	if (pid < 0) return -1;
	if (!wait_it) return 0;
	while ((r = waitpid(pid, &st, 0)) < 0 && errno == EINTR) ;
	return r < 0 ? -1 : (WIFEXITED(st) ? WEXITSTATUS(st) : -1);
}

/* the same, but a command that does not end within `secs` seconds is killed: a hung MQTT publish must not stop the
 * other jobs of the daemon (the shell loop it replaces would have waited for ever; only a failure case differs) */
static int run_to(const char *const *argv, int secs)
{
	int st = 0, r, n = 0;
	pid_t pid = spawn(argv);

	if (pid < 0) return -1;
	for (;;) {
		r = waitpid(pid, &st, WNOHANG);
		if (r == pid) return WIFEXITED(st) ? WEXITSTATUS(st) : -1;
		if (r < 0 && errno != EINTR) return -1;
		if (n >= secs * 20) break;
		poll(NULL, 0, 50);
		n++;
	}
	kill(pid, SIGKILL);
	while ((r = waitpid(pid, &st, 0)) < 0 && errno == EINTR) ;
	return -1;
}

static void reap(void)
{
	while (waitpid(-1, NULL, WNOHANG) > 0) ;
}

/* ================= auto night ================= */

enum { SRC_LUMA, SRC_AE, SRC_ISP, SRC_VENDOR };
static const char *const src_name[] = { "luma", "ae", "isp", "vendor" };

static ll THRESHOLD_NIGHT = 40, THRESHOLD_DAY = 100, AE_NIGHT_ABOVE = 15000, AE_DAY_BELOW = 3000;
static ll VENDOR_NIGHT_LUM = 3584, VENDOR_DAY_LUM = 1536, AWB_DAY_CNT = 50000, AWB_NIGHT_CNT = 1200;
static ll VENDOR_LOCK = 900, IR_LED_MAX_ON = 50400, IR_LED_REST = 600, NIGHT_HOLD = 10, DAY_HOLD = 60, MIN_SWITCH = 180;
static int DAYNIGHT_SOURCE = SRC_LUMA;
static int IR_LED_MODE;	/* 0 auto, 1 off, 2 force */
static char DN_MODE[16] = "2";

static ll LOW_LIGHT_COUNT, BRIGHT_LIGHT_COUNT, DN_VCNT, DN_LAST_SW = -100000, DN_SW_LUM, DN_LOCK_UNTIL, DN_LOCK_LUM;
static ll DN_NIGHT_SINCE, DN_REST_UNTIL, DN_DARK_SINCE, DN_BRIGHT_SINCE, DN_LAST_SWITCH, DN_TOO_SOON;
static int have_last_switch, have_too_soon, DN_AWB_SAME, DN_AWB_DAY, DN_AWB_VIS, CUR_CUT_ON = 1;
static char DN_AWB_LAST[200];
static ll DN_LOG_AT, DN_LOG_N;
static int SLP = 8;

static void night_reset(void)
{
	LOW_LIGHT_COUNT = BRIGHT_LIGHT_COUNT = DN_VCNT = DN_SW_LUM = DN_LOCK_UNTIL = DN_LOCK_LUM = 0;
	DN_LAST_SW = -100000;
	DN_NIGHT_SINCE = DN_REST_UNTIL = DN_DARK_SINCE = DN_BRIGHT_SINCE = DN_LOG_AT = DN_LOG_N = 0;
	have_last_switch = have_too_soon = DN_AWB_SAME = 0;
	DN_AWB_LAST[0] = 0;
	SLP = 8;
}

/* Settings of rtspserver.conf (daynight) and daynight.conf. Only lines ended by a newline are seen, as with the
 * shell's `while read` (a last line without one is dropped). */
static void conf_daynight(void)
{
	static char b[16384];
	int n = slurp(envs("DN_RTSPCONF", "/mnt/config/rtspserver.conf"), b, sizeof b);
	char *p, *e;

	snprintf(DN_MODE, sizeof DN_MODE, "2");
	if (n >= 0) {
		for (p = b; (e = strchr(p, '\n')); p = e + 1) {	/* IFS='= ': key, then value */
			char *k = p, *kv, *v, *ve;

			*e = 0;
			while (*k == ' ') k++;
			kv = k;
			while (*kv && *kv != ' ' && *kv != '=') kv++;
			v = kv;
			while (*v == ' ') v++;
			if (*v == '=') { v++; while (*v == ' ') v++; }
			ve = v;
			while (*ve && *ve != ' ' && *ve != '=') ve++;
			*ve = 0;
			*kv = 0;
			if (!strcmp(k, "daynight")) { snprintf(DN_MODE, sizeof DN_MODE, "%.15s", v); break; }
			if (!strcmp(k, "[0]")) break;
		}
	}
	n = slurp(envs("DN_CONF", "/mnt/config/daynight.conf"), b, sizeof b);
	if (n < 0) return;
	for (p = b; (e = strchr(p, '\n')); p = e + 1) {	/* IFS='=' */
		char *v, *k = p;
		size_t l;

		*e = 0;
		v = strchr(k, '=');
		if (v) *v++ = 0; else v = k + strlen(k);
		l = strlen(v);
		if (!strcmp(k, "LUMA_NIGHT") || !strcmp(k, "LUMA_DAY")) {
			if (!all_digits(v) || l > 3 || dec(v) > 255) continue;
			if (k[5] == 'N') THRESHOLD_NIGHT = dec(v); else THRESHOLD_DAY = dec(v);
		} else if (!strcmp(k, "DAYNIGHT_SOURCE")) {
			int i;

			for (i = 0; i < 4; i++) if (!strcmp(v, src_name[i])) DAYNIGHT_SOURCE = i;
		} else if (!strcmp(k, "IR_LED_MODE")) {
			if (!strcmp(v, "auto")) IR_LED_MODE = 0;
			else if (!strcmp(v, "off")) IR_LED_MODE = 1;
			else if (!strcmp(v, "force")) IR_LED_MODE = 2;
		} else if (!strcmp(k, "VENDOR_NIGHT_LUM") || !strcmp(k, "VENDOR_DAY_LUM") || !strcmp(k, "AWB_DAY_CNT") ||
			   !strcmp(k, "AWB_NIGHT_CNT") || !strcmp(k, "VENDOR_LOCK") || !strcmp(k, "IR_LED_MAX_ON") ||
			   !strcmp(k, "IR_LED_REST") || !strcmp(k, "AE_NIGHT_ABOVE") || !strcmp(k, "AE_DAY_BELOW")) {
			ll x;

			if (!all_digits(v) || l > 9) continue;
			x = dec(v);
			if (!strcmp(k, "VENDOR_NIGHT_LUM")) VENDOR_NIGHT_LUM = x;
			else if (!strcmp(k, "VENDOR_DAY_LUM")) VENDOR_DAY_LUM = x;
			else if (!strcmp(k, "AWB_DAY_CNT")) AWB_DAY_CNT = x;
			else if (!strcmp(k, "AWB_NIGHT_CNT")) AWB_NIGHT_CNT = x;
			else if (!strcmp(k, "VENDOR_LOCK")) VENDOR_LOCK = x;
			else if (!strcmp(k, "IR_LED_MAX_ON")) IR_LED_MAX_ON = x;
			else if (!strcmp(k, "IR_LED_REST")) IR_LED_REST = x;
			else if (!strcmp(k, "AE_NIGHT_ABOVE")) AE_NIGHT_ABOVE = x;
			else AE_DAY_BELOW = x;
		} else if (!strcmp(k, "NIGHT_HOLD") || !strcmp(k, "DAY_HOLD")) {
			if (!all_digits(v) || l > 4 || dec(v) < 1 || dec(v) > 3600) continue;
			if (k[0] == 'N') NIGHT_HOLD = dec(v); else DAY_HOLD = dec(v);
		} else if (!strcmp(k, "MIN_SWITCH")) {
			if (!all_digits(v) || l > 4 || dec(v) > 3600) continue;
			MIN_SWITCH = dec(v);
		}
	}
	if (AE_DAY_BELOW >= AE_NIGHT_ABOVE) AE_DAY_BELOW = AE_NIGHT_ABOVE / 2;	/* the gap: day needs a lower index */
}

static void read_now(void)
{
	if (!g_replay) NOW = mono_ms() / 1000;
}

static void read_cut(void)	/* 1 = ON = day; the state file of ir_cut */
{
	char b[64];

	CUR_CUT_ON = 1;
	if (first_line(envs("DN_IRCUT", "/var/run/ircut"), b, sizeof b) >= 0 && !strcmp(b, "0")) CUR_CUT_ON = 0;
}

/* split a line into blank-separated words; the last of `max` words takes the rest of the line (read -r a b c) */
static int words(char *line, char **w, int max)
{
	int n = 0;

	while (n < max) {
		while (*line == ' ' || *line == '\t') line++;
		if (!*line) break;
		w[n++] = line;
		if (n == max) {
			char *e = line + strlen(line);

			while (e > line && (e[-1] == ' ' || e[-1] == '\t')) e--;
			*e = 0;
			break;
		}
		while (*line && *line != ' ' && *line != '\t') line++;
		if (*line) *line++ = 0;
	}
	return n;
}

struct ae { char line[1024]; char *w[7]; };

/* The first line of /tmp/cam_ae as words: lumi exp_time a_gain d_gain isp_d_gain dark_flag [rest of the line].
 * 0 when the file is unreadable or its first line has no newline (read fails at EOF). */
static int read_ae(struct ae *a)
{
	char b[1024];
	int n, i;

	if (first_line(envs("CAM_AE", "/tmp/cam_ae"), b, sizeof b) != 0) return 0;
	snprintf(a->line, sizeof a->line, "%s", b);
	n = words(a->line, a->w, 7);
	for (i = n; i < 7; i++) a->w[i] = (char *)"";
	return 1;
}

/* exposure index of six plain decimal numbers (no leading zero, at most 9 digits) */
static int dn_index(char *const *f, ll *idx)
{
	int i;

	for (i = 0; i < 6; i++) {
		const char *s = f[i];

		if (!all_digits(s) || (s[0] == '0' && s[1]) || strlen(s) > 9) return 0;
	}
	*idx = dec(f[1]) * dec(f[2]) / 256;
	*idx = *idx * dec(f[3]) / 256;
	*idx = *idx * dec(f[4]) / 256;
	return 1;
}

/* the stock firmware's light metric from the cam_ae fields f[0..5] and the maximum exposure m */
static int dn_vendor_lum(char *const *f, const char *m, ll *lum)
{
	ll idx, vm = 1125, vl, vg;

	if (!dn_index(f, &idx)) return 0;
	if (all_digits(m) && m[0] != '0') vm = dec(m);
	vl = dec(f[0]);
	if (vl <= 0) vl = 40;
	vg = dec(f[2]) * dec(f[3]) / 256;
	vg = vg * dec(f[4]) / 256;
	*lum = dec(f[1]) * vg / vm * 40 / vl;
	return 1;
}

static void dn_switch(int night, const char *why)
{
	const char *argv[3];

	if (have_last_switch && NOW - DN_LAST_SWITCH < MIN_SWITCH) {
		/* too soon after the last switch: wait; the counters keep running, so it happens once the time is up */
		if (!have_too_soon || DN_TOO_SOON != DN_LAST_SWITCH)
			console("[auto-night] %s wanted (%s) %lld s after the last switch: waiting %lld s",
				night ? "night" : "day", why, NOW - DN_LAST_SWITCH, MIN_SWITCH);
		DN_TOO_SOON = DN_LAST_SWITCH;
		have_too_soon = 1;
		return;
	}
	DN_LAST_SWITCH = NOW;
	have_last_switch = 1;
	if (night) console("[auto-night] Low light detected (%s): Switching to NIGHT mode", why);
	else console("[auto-night] Bright light detected (%s): Switching to DAY mode", why);
	argv[0] = envs("DN_NIGHTMODE", "/mnt/scripts/nightmode.sh");
	argv[1] = night ? "on" : "off";
	argv[2] = NULL;
	run(argv, 1);
	DN_DARK_SINCE = DN_BRIGHT_SINCE = 0;
	LOW_LIGHT_COUNT = BRIGHT_LIGHT_COUNT = 0;
}

/* hold logic of the ae and isp sources: dark = wants night, bright = wants day; -1 nothing, 1 night, 0 day */
static int dn_hold(int dark, int bright)
{
	int act = -1;

	if (CUR_CUT_ON) {
		DN_BRIGHT_SINCE = 0;
		if (dark) {
			if (DN_DARK_SINCE == 0) DN_DARK_SINCE = NOW;
			if (NOW - DN_DARK_SINCE >= NIGHT_HOLD) act = 1;
		} else DN_DARK_SINCE = 0;
	} else {
		DN_DARK_SINCE = 0;
		if (bright) {
			if (DN_BRIGHT_SINCE == 0) DN_BRIGHT_SINCE = NOW;
			if (NOW - DN_BRIGHT_SINCE >= DAY_HOLD) act = 0;
		} else DN_BRIGHT_SINCE = 0;
	}
	return act;
}

static int dn_step_ae(void)	/* 0 = used, -1 = /tmp/cam_ae cannot be used (the caller falls back to luma) */
{
	struct ae a;
	ll idx;
	int dark, bright, act;
	char why[200];

	if (!read_ae(&a) || !dn_index(a.w, &idx)) return -1;
	read_now();
	read_cut();
	if (DAYNIGHT_SOURCE == SRC_ISP) {
		dark = strcmp(a.w[5], "0") != 0;
		bright = 1 - dark;
		snprintf(why, sizeof why, "isp dark flag=%s", a.w[5]);
	} else {
		dark = idx > AE_NIGHT_ABOVE;
		bright = idx < AE_DAY_BELOW;
		snprintf(why, sizeof why, "exposure index=%lld exp=%s gains=%s/%s/%s", idx, a.w[1], a.w[2], a.w[3], a.w[4]);
	}
	act = dn_hold(dark, bright);
	if (act >= 0) dn_switch(act, why);
	return 0;
}

/* white balance counts of /tmp/cam_awb -> DN_AWB_DAY (a count above AWB_DAY_CNT) and DN_AWB_VIS (one of the first five
 * above AWB_NIGHT_CNT); without a usable file the metric decides alone */
static void dn_awb(void)
{
	char b[1024], *w[11], wl[200];
	int i;
	ll v[10];

	DN_AWB_DAY = 0; DN_AWB_VIS = 1;
	if (first_line(envs("CAM_AWB", "/tmp/cam_awb"), b, sizeof b) != 0) return;
	if (words(b, w, 11) < 11) return;
	for (i = 0; i < 10; i++) {
		if (!all_digits(w[i]) || strlen(w[i]) > 9) return;
		v[i] = dec(w[i]);
	}
	/* counts that stay exactly the same for 3 samples are stale (R11-02): the metric then decides alone */
	wl[0] = 0;
	for (i = 0; i < 10; i++) {
		size_t l = strlen(wl);

		snprintf(wl + l, sizeof wl - l, "%s%s", i ? " " : "", w[i]);
	}
	if (!strcmp(wl, DN_AWB_LAST)) DN_AWB_SAME++;
	else { DN_AWB_SAME = 0; snprintf(DN_AWB_LAST, sizeof DN_AWB_LAST, "%s", wl); }
	if (DN_AWB_SAME >= 2) return;
	DN_AWB_VIS = 0;
	for (i = 0; i < 5; i++) if (v[i] > AWB_NIGHT_CNT) DN_AWB_VIS = 1;
	for (i = 0; i < 10; i++) if (v[i] > AWB_DAY_CNT) DN_AWB_DAY = 1;
}

static int dn_step_vendor(void)
{
	struct ae a;
	ll lum;
	int want = -1;
	char why[160];

	if (!read_ae(&a) || !dn_vendor_lum(a.w, a.w[6], &lum)) return -1;
	read_now();
	read_cut();
	dn_awb();
	if (CUR_CUT_ON) { if (lum > VENDOR_NIGHT_LUM && DN_AWB_DAY == 0) want = 1; }
	else if (lum < VENDOR_DAY_LUM && DN_AWB_VIS == 1) want = 0;
	if (want >= 0) DN_VCNT++; else DN_VCNT = 0;
	if (DN_VCNT < 3) return 0;
	DN_VCNT = 0;
	if (DN_LOCK_UNTIL > NOW) {
		ll vd = lum - DN_LOCK_LUM;

		if (vd < 0) vd = -vd;
		if (!(vd * 10 > DN_LOCK_LUM * 3)) return 0;	/* locked: the scene did not change by 30 % */
		DN_LOCK_UNTIL = 0;
	}
	if (NOW - DN_LAST_SW < 15) {
		DN_LOCK_UNTIL = NOW + VENDOR_LOCK;
		DN_LOCK_LUM = DN_SW_LUM;
		console("[auto-night] switching back within 15 s: locked for %lld s (lum=%lld)", VENDOR_LOCK, lum);
		return 0;
	}
	DN_LAST_SW = NOW;
	DN_SW_LUM = lum;
	snprintf(why, sizeof why, "vendor lum=%lld awb day=%d visible=%d", lum, DN_AWB_DAY, DN_AWB_VIS);
	dn_switch(want, why);
	return 0;
}

/* IR LED protection (stock ir_switch_handler): after IR_LED_MAX_ON s of night, day mode for IR_LED_REST s.
 * 1 while it holds the decisions (it switched, or the rest is not over). */
static int dn_ir_guard(void)
{
	if (IR_LED_MODE == 1 || IR_LED_MAX_ON <= 0) return 0;
	read_now();
	read_cut();
	if (!CUR_CUT_ON) {
		if (DN_NIGHT_SINCE == 0) DN_NIGHT_SINCE = NOW;
		if (NOW - DN_NIGHT_SINCE >= IR_LED_MAX_ON) {
			const char *argv[3];

			console("[auto-night] IR LEDs on for %lld s: day mode for %lld s (IR LED protection)",
				NOW - DN_NIGHT_SINCE, IR_LED_REST);
			argv[0] = envs("DN_NIGHTMODE", "/mnt/scripts/nightmode.sh");
			argv[1] = "off";
			argv[2] = NULL;
			run(argv, 1);
			DN_REST_UNTIL = NOW + IR_LED_REST;
			DN_NIGHT_SINCE = 0;
			return 1;
		}
	} else DN_NIGHT_SINCE = 0;
	return DN_REST_UNTIL > NOW;
}

static void dn_step_luma(void)	/* the original decision on the picture luminance: two samples in a row */
{
	const char *lf = envs("CAM_LUMA", "/tmp/cam_luma");
	char b[64], w[32];
	ll luma = 50;

	read_now();
	if (access(lf, F_OK) == 0) {
		if (first_line(lf, b, sizeof b) >= 0 && all_digits(b)) luma = dec(b);
	} else {	/* no luma file: the mean of the first 512 bytes of the cached picture, as hexdump | awk did */
		unsigned char p[512];
		int f = open("/tmp/currentpic.cache.jpg", O_RDONLY), n = 0, i, k;
		ll s = 0;

		if (f >= 0) {
			while (n < 512 && (k = read(f, p + n, 512 - n)) > 0) n += k;
			close(f);
			for (i = 0; i < n; i++) s += (signed char)p[i];
			luma = n > 0 ? s / n : 50;
			if (luma < 0) luma = 50;	/* a negative mean is not made of digits for the shell */
		}
	}
	read_cut();
	snprintf(w, sizeof w, "luma=%lld", luma);
	if (CUR_CUT_ON) {
		if (luma < THRESHOLD_NIGHT) {
			if (++LOW_LIGHT_COUNT >= 2) dn_switch(1, w);
		} else LOW_LIGHT_COUNT = 0;
	} else {
		if (luma > THRESHOLD_DAY) {
			if (++BRIGHT_LIGHT_COUNT >= 2) dn_switch(0, w);
		} else BRIGHT_LIGHT_COUNT = 0;
	}
}

/* one calibration line every DN_LOG_EVERY seconds, kept to the last 2 x 400 lines */
static void dn_log(void)
{
	const char *path = envs("DN_LOG", "/tmp/logs/daynight.log");
	char lluma[1024] = "-", lae[1024] = "-", lawb[1024] = "-", tmp[1024], *w[8], hm[8] = "";
	char idx[24] = "-", lum[24] = "-", line[3300], *a[7];
	ll idxv, lumv, every = env_num("DN_LOG_EVERY", 300);
	int n, f, i;
	time_t t;
	struct tm tmv;

	read_now();
	if (NOW - DN_LOG_AT < every) return;
	DN_LOG_AT = NOW;
	read_cut();
	if (first_line(envs("CAM_LUMA", "/tmp/cam_luma"), tmp, sizeof tmp) >= 0 && tmp[0]) snprintf(lluma, sizeof lluma, "%s", tmp);
	if (first_line(envs("CAM_AE", "/tmp/cam_ae"), tmp, sizeof tmp) >= 0 && tmp[0]) snprintf(lae, sizeof lae, "%s", tmp);
	if (first_line(envs("CAM_AWB", "/tmp/cam_awb"), tmp, sizeof tmp) >= 0 && tmp[0]) snprintf(lawb, sizeof lawb, "%s", tmp);
	snprintf(tmp, sizeof tmp, "%s", lae);
	n = words(tmp, w, 8);
	for (i = 0; i < 7; i++) a[i] = i < n ? w[i] : (char *)"";
	if (dn_index(a, &idxv)) snprintf(idx, sizeof idx, "%lld", idxv);
	if (dn_vendor_lum(a, a[6], &lumv)) snprintf(lum, sizeof lum, "%lld", lumv);
	t = time(NULL);
	if (localtime_r(&t, &tmv)) snprintf(hm, sizeof hm, "%02d:%02d", tmv.tm_hour % 100, tmv.tm_min % 100);
	if (DN_LOG_N >= 400) {
		char old[300];

		snprintf(old, sizeof old, "%s.1", path);
		rename(path, old);
		DN_LOG_N = 0;
	}
	n = snprintf(line, sizeof line, "%s mode=%s src=%s luma=%s ae=%s idx=%s lum=%s awb=%s\n", hm,
		     CUR_CUT_ON ? "day" : "night", src_name[DAYNIGHT_SOURCE], lluma, lae, idx, lum, lawb);
	if (n > (int)sizeof line - 1) n = sizeof line - 1;
	f = open(path, O_WRONLY | O_CREAT | O_APPEND, 0644);
	if (f >= 0) { if (write(f, line, n) < 0) {} close(f); }
	DN_LOG_N++;
}

/* one turn of the main loop of the shell daemon, without the wait; SLP is the wait before the next turn */
static void night_iteration(void)
{
	conf_daynight();
	dn_log();
	if (strcmp(DN_MODE, "2")) return;	/* manual day/night (3) pauses the daemon */
	if (dn_ir_guard()) return;
	if (DAYNIGHT_SOURCE == SRC_VENDOR) {
		SLP = 2;
		if (dn_step_vendor() == 0) return;
	} else if (DAYNIGHT_SOURCE != SRC_LUMA) {
		SLP = 2;	/* /tmp/cam_ae changes every 2 s; the hold times are measured in seconds */
		if (dn_step_ae() == 0) return;
	}
	SLP = 8;
	dn_step_luma();
}

/* ================= reset button ================= */

static int g_down, g_armed, g_btn_ok;
static int B_REBOOT = 8, B_RESTORE = 20, B_RESCUE = 3;

static void button_init(void)
{
	char b[64], p[300];
	const char *dir = envs("BUTTON_GPIO_DIR", "/sys/class/gpio/gpio522");
	int f;

	B_REBOOT = env_num("BUTTON_REBOOT_SECONDS", 8);
	B_RESTORE = env_num("BUTTON_RESTORE_SECONDS", 20);
	B_RESCUE = env_num("BUTTON_RESCUE_SECONDS", 3);
	g_down = g_armed = g_btn_ok = 0;
	/* the poll is the Linux 6.6 path: the /tmp/linux66 flag and no input device (gpio_keys is off) */
	if (access(envs("BUTTON_L66_FLAG", "/tmp/linux66"), F_OK) != 0 || access(envs("BUTTON_DEV", "/dev/input/event0"), F_OK) == 0) {
		dprintf(2, "button: not the Linux 6.6 poll mode\n");
		return;
	}
	if (access(dir, F_OK) != 0) {
		f = open("/sys/class/gpio/export", O_WRONLY);
		if (f >= 0) {
			snprintf(b, sizeof b, "%s\n", envs("BUTTON_GPIO", "522"));
			if (write(f, b, strlen(b)) < 0) {}
			close(f);
		}
		snprintf(p, sizeof p, "%s/direction", dir);
		f = open(p, O_WRONLY);
		if (f >= 0) { if (write(f, "in\n", 3) < 0) {} close(f); }
	}
	snprintf(p, sizeof p, "%s/value", dir);
	if (access(p, R_OK) != 0) { dprintf(2, "no button GPIO (%s)\n", dir); return; }
	g_btn_ok = 1;
}

static void bw_log(const char *msg)	/* logger -t tc100-event -p user.err "button: ..." */
{
	char m[160];
	const char *argv[8];

	snprintf(m, sizeof m, "button: %s", msg);
	if (g_replay) dprintf(1, "log %s\n", m);
	argv[0] = access("/usr/bin/logger", X_OK) == 0 ? "/usr/bin/logger" : "/bin/logger";
	argv[1] = "-t"; argv[2] = "tc100-event"; argv[3] = "-p"; argv[4] = "user.err"; argv[5] = m; argv[6] = NULL;
	run(argv, 1);
}

static void bw_reboot(int held)
{
	char m[96];
	const char *a[6];

	snprintf(m, sizeof m, "reset button held %ds", held);
	a[0] = "/bin/sh"; a[1] = envs("BUTTON_TRACKER", "/mnt/scripts/reboot-tracker.sh"); a[2] = "intent"; a[3] = m; a[4] = NULL;
	run(a, 1);
	sync();
	a[0] = envs("BUTTON_REBOOT_CMD", "/sbin/reboot"); a[1] = NULL;
	run(a, 1);
}

static void bw_action(int held)	/* what the button does once released */
{
	char m[96], st[64];
	const char *a[6];
	const char *fc = envs("BUTTON_FLASH_CODE", "/usr/tc100/scripts/flash-code.sh");

	if (held >= B_RESTORE) {
		size_t l;

		st[0] = 0;
		first_line(envs("TC100_STORAGE_FILE", "/tmp/tc100-storage"), st, sizeof st);
		l = strlen(st);
		while (l && (st[l - 1] == '\r')) st[--l] = 0;
		if (!strcmp(st, "flash") && access(fc, X_OK) == 0) {
			snprintf(m, sizeof m, "held %ds: back to the built-in code, reboot", held);
			bw_log(m);
			a[0] = "/bin/sh"; a[1] = fc; a[2] = "clear"; a[3] = NULL;
			run(a, 1);
		} else {
			snprintf(m, sizeof m, "held %ds: reboot", held);
			bw_log(m);
		}
		bw_reboot(held);
	} else if (held >= B_REBOOT) {
		snprintf(m, sizeof m, "held %ds: reboot", held);
		bw_log(m);
		bw_reboot(held);
	} else if (held >= B_RESCUE) {
		snprintf(m, sizeof m, "held %ds: rescue access point", held);
		bw_log(m);
		a[0] = "/bin/sh"; a[1] = envs("BUTTON_RESCUE", "/mnt/scripts/wifi-rescue.sh"); a[2] = "start-ap";
		a[3] = "reset button"; a[4] = NULL;
		run(a, 0);
	}
}

/* One second of the button: act on release only, and only once the pin has been seen released (a pin that reads 0
 * for ever, a stuck button, must never turn into a reboot loop). */
static void button_sample(int pressed)
{
	if (pressed) {
		if (g_armed) g_down++;
	} else {
		if (g_down > 0) bw_action(g_down);
		g_down = 0;
		g_armed = 1;
	}
}

static int button_read(void)	/* 1 = pressed (value 0) */
{
	char p[300], b[16];

	snprintf(p, sizeof p, "%s/value", envs("BUTTON_GPIO_DIR", "/sys/class/gpio/gpio522"));
	return first_line(p, b, sizeof b) >= 0 && !strcmp(b, "0");
}

/* ================= sound detection ================= */

/* controlscripts/sound-detection run_daemon(): the microphone level that tc100_rtsp writes to /var/run/sound_level
 * (one line "ts rms peak events last_ts last_db", counted every second) becomes "sound" events: MQTT event, optional
 * babyphone (VOX) and alarm-tone states, notification, snapshot for Home Assistant, recording trigger. Config from
 * config/sound_detection.conf (re-read at every turn: the shell loop re-read it when the file was newer than a stamp). */

static char SD_LAST_EVENTS[32], SD_LAST_THR[32], SD_RM_TS[32];
static ll SD_RM_CHANGE, SD_LAST_PUBLISH, SD_STREAK, SD_VOX_UNTIL, SD_ALARM_UNTIL;
static int SD_WARNED, SD_VOX_ACTIVE, SD_ALARM_ACTIVE;

static struct {
	int enable, min_loud, vox_mode, vox_hold, alarm_detect, alarm_hold, interval;
	char threshold[32];
} sd;

static void sound_reset(void)
{
	SD_LAST_EVENTS[0] = SD_LAST_THR[0] = SD_RM_TS[0] = 0;
	SD_RM_CHANGE = SD_LAST_PUBLISH = SD_STREAK = SD_VOX_UNTIL = SD_ALARM_UNTIL = 0;
	SD_WARNED = SD_VOX_ACTIVE = SD_ALARM_ACTIVE = 0;
}

/* ${NAME:-def} clamped to min..max; a value that is not plain digits becomes min (clamp_int of the shell script) */
static ll env_clamp(const char *name, ll def, ll min, ll max)
{
	const char *v = getenv(name);
	ll x = def;

	if (v && *v) x = all_digits(v) ? dec(v) : min;
	return x < min ? min : (x > max ? max : x);
}

static void mkdir_p(const char *path)
{
	char b[300], *p;

	snprintf(b, sizeof b, "%s", path);
	for (p = b + 1; *p; p++) if (*p == '/') { *p = 0; mkdir(b, 0755); *p = '/'; }
	mkdir(b, 0755);
}

static void wfile(const char *path, const char *text)	/* echo text > path */
{
	int f = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);

	if (f >= 0) { if (write(f, text, strlen(text)) < 0) {} close(f); }
}

static void sd_rotate(const char *path)
{
	ll max = env_clamp("LOG_MAX_BYTES", 32768, 0, 1000000000LL);
	int backups = (int)env_clamp("LOG_BACKUPS", 1, 0, 3), f, idx;
	off_t size;
	char a[320], b[320];

	f = open(path, O_RDONLY);
	if (f < 0) return;
	size = lseek(f, 0, SEEK_END);
	close(f);
	if (size < max) return;
	if (backups > 0) {
		for (idx = backups; idx > 1; idx--) {
			snprintf(a, sizeof a, "%s.%d", path, idx - 1);
			snprintf(b, sizeof b, "%s.%d", path, idx);
			if (access(a, F_OK) == 0) rename(a, b);
		}
		snprintf(b, sizeof b, "%s.1", path);
		if (rename(path, b) != 0) wfile(path, "");
	} else wfile(path, "");
}

static void sd_log(const char *msg)	/* log_msg: "[YYYY-MM-DD HH:MM:SS] msg" in RAM, rotated */
{
	const char *path = envs("SD_LOG", "/tmp/log/sound-detection.log");
	char dir[300], line[700], *sl;
	time_t t = time(NULL);
	struct tm tmv;
	int f, n;

	snprintf(dir, sizeof dir, "%s", path);
	sl = strrchr(dir, '/');
	if (sl && sl != dir) { *sl = 0; mkdir_p(dir); }
	sd_rotate(path);
	memset(&tmv, 0, sizeof tmv);
	if (!localtime_r(&t, &tmv)) tmv.tm_year = -1900;
	n = snprintf(line, sizeof line, "[%04d-%02d-%02d %02d:%02d:%02d] %s\n", (tmv.tm_year + 1900) % 10000, (tmv.tm_mon + 1) % 100,
		     tmv.tm_mday % 100, tmv.tm_hour % 100, tmv.tm_min % 100, tmv.tm_sec % 100, msg);
	if (n > (int)sizeof line - 1) n = sizeof line - 1;
	f = open(path, O_WRONLY | O_CREAT | O_APPEND, 0644);
	if (f >= 0) { if (write(f, line, n) < 0) {} close(f); }
}

static ll sd_uptime(void)	/* integer seconds of /proc/uptime (a file of its own for the tests) */
{
	char b[64];

	if (first_line(envs("SD_UPTIME", "/proc/uptime"), b, sizeof b) < 0) return 0;
	return dec(b);	/* stops at the dot */
}

/* the script of the same name in $SD_SCRIPTS; need_x: only when it is executable (the shell tests -x first) */
static int sd_script(const char *name, int need_x, int bg, const char *a1, const char *a2, const char *a3, const char *a4)
{
	char path[300];
	const char *argv[8];
	int n = 0;

	snprintf(path, sizeof path, "%s/%s", envs("SD_SCRIPTS", "/mnt/scripts"), name);
	if (need_x && access(path, X_OK) != 0) return -1;
	argv[n++] = path;
	if (a1) argv[n++] = a1;
	if (a2) argv[n++] = a2;
	if (a3) argv[n++] = a3;
	if (a4) argv[n++] = a4;
	argv[n] = NULL;
	return bg ? run(argv, 0) : run_to(argv, env_num("SD_TIMEOUT", 30));
}

static void sd_state_pub(const char *topic, const char *val)	/* mqtt-bridge.sh publish TOPIC VAL 1 */
{
	sd_script("mqtt-bridge.sh", 1, 0, "publish", topic, val, "1");
}

static void sd_vox_off(void)
{
	SD_VOX_ACTIVE = 0;
	unlink(envs("SD_VOX", "/tmp/vox_state"));
	sd_state_pub("babyphone/state", "OFF");
}

static void sd_alarm_off(void)
{
	SD_ALARM_ACTIVE = 0;
	unlink(envs("SD_ALARM", "/tmp/sound_alarm_state"));
	sd_state_pub("alarm/state", "OFF");
}

static void sd_load_config(void)
{
	static char b[4096];
	int n = slurp(envs("SD_CONF", "/mnt/config/sound_detection.conf"), b, sizeof b);
	char *p, *e, enable[16] = "0", thr[32] = "-24", itv[32] = "2", ml[32] = "1", vm[32] = "0", vh[32] = "5", ad[32] = "0", ah[32] = "15";
	ll x;

	if (n >= 0) {
		for (p = b; (e = strchr(p, '\n')); p = e + 1) {	/* only lines ended by a newline: `while read` */
			char *v, *k = p;

			*e = 0;
			v = strchr(k, '=');
			if (v) *v++ = 0; else v = k + strlen(k);
			if (!strcmp(k, "ENABLE")) snprintf(enable, sizeof enable, "%s", v);
			else if (!strcmp(k, "THRESHOLD_DB")) snprintf(thr, sizeof thr, "%s", v);
			else if (!strcmp(k, "INTERVAL")) snprintf(itv, sizeof itv, "%s", v);
			else if (!strcmp(k, "MIN_LOUD_SECONDS")) snprintf(ml, sizeof ml, "%s", v);
			else if (!strcmp(k, "VOX_MODE")) snprintf(vm, sizeof vm, "%s", v);
			else if (!strcmp(k, "VOX_HOLD_SECONDS")) snprintf(vh, sizeof vh, "%s", v);
			else if (!strcmp(k, "ALARM_DETECT")) snprintf(ad, sizeof ad, "%s", v);
			else if (!strcmp(k, "ALARM_HOLD_SECONDS")) snprintf(ah, sizeof ah, "%s", v);
		}
	}
	sd.enable = !strcmp(enable, "1");
	/* -[0-9] | -[0-9][0-9] | 0, else -24; then not below -90 */
	if (!((thr[0] == '-' && thr[1] >= '0' && thr[1] <= '9' && (!thr[2] || (thr[2] >= '0' && thr[2] <= '9' && !thr[3]))) || !strcmp(thr, "0")))
		snprintf(thr, sizeof thr, "-24");
	if (thr[0] == '-' && thr[2] && dec(thr + 1) > 90) snprintf(thr, sizeof thr, "-90");
	snprintf(sd.threshold, sizeof sd.threshold, "%s", thr);
	x = all_digits(itv) && strlen(itv) <= 9 ? dec(itv) : 2;
	sd.interval = (int)(x < 1 ? 1 : (x > 300 ? 300 : x));
	x = all_digits(ml) && strlen(ml) <= 9 ? dec(ml) : 1;
	sd.min_loud = (int)(x < 1 ? 1 : (x > 10 ? 10 : x));
	sd.vox_mode = !strcmp(vm, "1") || !strcmp(vm, "true") || !strcmp(vm, "yes") || !strcmp(vm, "on");
	x = all_digits(vh) && strlen(vh) <= 9 ? dec(vh) : 5;
	sd.vox_hold = (int)(x < 1 ? 1 : (x > 60 ? 60 : x));
	sd.alarm_detect = !strcmp(ad, "1") || !strcmp(ad, "true") || !strcmp(ad, "yes") || !strcmp(ad, "on");
	x = all_digits(ah) && strlen(ah) <= 9 ? dec(ah) : 15;
	sd.alarm_hold = (int)(x < 5 ? 5 : (x > 120 ? 120 : x));
}

/* the shell's read_meter: 1 with a fresh reading; w[0..5] = ts rms peak events last_ts last_db */
static int sd_read_meter(char **w, char *line, int cap)
{
	char b[1024], *ww[7];
	int i, n;
	ll up;

	for (i = 0; i < 7; i++) w[i] = (char *)"";
	if (first_line(envs("SOUND_LEVEL_FILE", "/var/run/sound_level"), b, sizeof b) < 0) return 0;
	snprintf(line, cap, "%s", b);
	n = words(line, ww, 7);
	for (i = 0; i < n; i++) w[i] = ww[i];
	if (!all_digits(w[0])) return 0;
	up = sd_uptime();
	if (strcmp(w[0], SD_RM_TS)) { snprintf(SD_RM_TS, sizeof SD_RM_TS, "%s", w[0]); SD_RM_CHANGE = up; }
	return up - SD_RM_CHANGE <= 10;
}

static int sd_prefix_line(const char *path, const char *prefix)	/* grep -q '^PREFIX' file */
{
	static char b[8192];
	char *p;
	size_t l = strlen(prefix);

	if (slurp(path, b, sizeof b) < 0) return 0;
	for (p = b; p; ) {
		if (!strncmp(p, prefix, l)) return 1;
		p = strchr(p, '\n');
		if (p) p++;
	}
	return 0;
}

static int sd_rec_motion(void)	/* read_kv_config_value boot.conf REC_WHEN offline = motion */
{
	static char b[16384];
	char *p, *e, val[64] = "";

	if (slurp(envs("SD_BOOTCONF", "/mnt/config/boot.conf"), b, sizeof b) >= 0) {
		for (p = b; *p; p = e ? e + 1 : p + strlen(p)) {
			char *q = p, *eq;

			e = strchr(p, '\n');
			if (e) *e = 0;
			while (*q == ' ' || *q == '\t') q++;
			if (*q == '#') continue;
			eq = strchr(p, '=');
			if (!eq) continue;
			*eq = 0;
			if (strcmp(p, "REC_WHEN")) continue;	/* awk -F=: $1 == key, first match */
			snprintf(val, sizeof val, "%s", eq + 1);
			break;
		}
	}
	return !strcmp(val, "motion");
}

static void sd_publish_event(const char *level, const char *threshold, const char *ts)
{
	char payload[400], tsb[24], msg[160];

	if (!*ts) { snprintf(tsb, sizeof tsb, "%lld", (ll)time(NULL)); ts = tsb; }
	snprintf(payload, sizeof payload, "{\"type\":\"sound\",\"ts\":%s,\"level_db\":%s,\"threshold_db\":%s}", ts, level, threshold);
	sd_script("mqtt-bridge.sh", 1, 0, "publish", "event", payload, "0");
	if (sd.vox_mode) {
		sd_state_pub("babyphone/state", "ON");
		wfile(envs("SD_VOX", "/tmp/vox_state"), "ON\n");
	}
	if (sd_prefix_line(envs("SD_MQTTCONF", "/mnt/config/mqtt.conf"), "MQTT_SNAPSHOT_ON_EVENT=1"))
		sd_script("mqtt-bridge.sh", 0, 1, "snapshot-event", "sound", NULL, NULL);
	snprintf(msg, sizeof msg, "Sound alert: level %s dBFS (threshold %s dBFS)", level, threshold);
	sd_script("notify.sh", 1, 1, "sound", msg, "", level);
	if (sd_rec_motion()) {
		const char *m = envs("SD_MOTION", "/tmp/motion_detected");
		int f = open(m, O_WRONLY | O_CREAT | O_NOCTTY, 0644);

		if (f >= 0) close(f);
		utime(m, NULL);
	}
}

/* one turn of run_daemon without the wait; returns the seconds to wait */
static int sound_iteration(void)
{
	char line[1024], *w[7], msg[200], lt[400];

	sd_load_config();
	if (!sd.enable) {	/* disabled: the config is looked at only every 5 minutes */
		if (SD_VOX_ACTIVE) sd_vox_off();
		if (SD_ALARM_ACTIVE) sd_alarm_off();
		return 300;
	}
	/* tell the meter when the threshold changes (it re-reads this file every 10 s) */
	snprintf(lt, sizeof lt, "%s.threshold", envs("SOUND_LEVEL_FILE", "/var/run/sound_level"));
	if (strcmp(sd.threshold, SD_LAST_THR) || access(lt, F_OK) != 0) {
		char t[40];

		snprintf(t, sizeof t, "%s\n", sd.threshold);
		wfile(lt, t);
		snprintf(SD_LAST_THR, sizeof SD_LAST_THR, "%s", sd.threshold);
	}
	if (sd_read_meter(w, line, sizeof line)) {
		char st[200];

		SD_WARNED = 0;
		snprintf(st, sizeof st, "%s %s %s\n", w[1], w[2], w[0]);
		wfile(envs("SD_STATE", "/tmp/sound-detection.state"), st);
		if (!SD_LAST_EVENTS[0]) snprintf(SD_LAST_EVENTS, sizeof SD_LAST_EVENTS, "%s", w[3]);	/* do not replay past events */
		else if (strcmp(w[3], SD_LAST_EVENTS)) {
			ll delta = dec(w[3]) - dec(SD_LAST_EVENTS), cool = env_clamp("EVENT_COOLDOWN_SECONDS", 10, 0, 300);

			if (delta <= 0) delta = 1;
			snprintf(SD_LAST_EVENTS, sizeof SD_LAST_EVENTS, "%s", w[3]);
			SD_STREAK += delta;
			if (SD_STREAK >= sd.min_loud && (cool == 0 || dec(w[4]) - SD_LAST_PUBLISH >= cool)) {
				snprintf(msg, sizeof msg, "Triggered level=%sdBFS threshold=%sdBFS loud=%llds", w[5], sd.threshold, SD_STREAK);
				sd_log(msg);
				sd_publish_event(w[5], sd.threshold, w[4]);
				SD_LAST_PUBLISH = dec(w[4]);
				if (sd.vox_mode) { SD_VOX_ACTIVE = 1; SD_VOX_UNTIL = sd_uptime() + sd.vox_hold; }
			}
			if (sd.alarm_detect && SD_STREAK >= 3) {	/* loud sound continuous for 3+ seconds */
				SD_ALARM_ACTIVE = 1;
				SD_ALARM_UNTIL = sd_uptime() + sd.alarm_hold;
				wfile(envs("SD_ALARM", "/tmp/sound_alarm_state"), "ON\n");
				sd_state_pub("alarm/state", "ON");
				snprintf(msg, sizeof msg, "Alarm sound pattern detected (loudness: %llds)", SD_STREAK);
				sd_script("notify.sh", 1, 1, "sound", msg, "", w[5]);
			}
		} else SD_STREAK = 0;
		if (sd.vox_mode && SD_VOX_ACTIVE && sd_uptime() >= SD_VOX_UNTIL) sd_vox_off();
		if (sd.alarm_detect && SD_ALARM_ACTIVE && sd_uptime() >= SD_ALARM_UNTIL) sd_alarm_off();
	} else {
		wfile(envs("SD_STATE", "/tmp/sound-detection.state"), "none\n");
		if (!SD_WARNED) {
			sd_log("No sound level from the RTSP server (is rtsp-h26x running, restarted since sound detection was enabled?)");
			SD_WARNED = 1;
		}
		SD_LAST_EVENTS[0] = 0;
		if (SD_VOX_ACTIVE) sd_vox_off();
		if (SD_ALARM_ACTIVE) sd_alarm_off();
	}
	return sd.interval;
}

/* ================= main loop and test mode ================= */

static void on_term(int s) { (void)s; g_stop = 1; }

static void replay(const char *script)
{
	static char b[1 << 20];
	int n = slurp(script, b, sizeof b);
	char *p = b, *e;

	if (n < 0) { dprintf(2, "cannot read %s\n", script); exit(2); }
	g_replay = 1;
	button_init();
	while (*p) {
		char *arg;

		e = strchr(p, '\n');
		if (e) *e = 0; else e = p + strlen(p) - 1;
		arg = strchr(p, ' ');
		if (arg) *arg++ = 0; else arg = (char *)"";
		if (!strcmp(p, "now")) NOW = dec(arg);
		else if (!strcmp(p, "night")) { night_iteration(); dprintf(1, "slp=%d\n", SLP); }
		else if (!strcmp(p, "button")) button_sample(arg[0] == '0');
		else if (!strcmp(p, "sdreset")) sound_reset();
		else if (!strcmp(p, "sound")) { int w = sound_iteration(); while (waitpid(-1, NULL, 0) > 0) {} dprintf(1, "wait=%d\n", w); }
		else if (!strcmp(p, "echo")) dprintf(1, "%s\n", arg);
		else if (!strcmp(p, "rm")) unlink(arg);
		else if (!strcmp(p, "cat")) {
			char c[2048];
			int k = slurp(arg, c, sizeof c);

			if (k > 0 && write(1, c, k) < 0) { /* nothing to do */ }
		} else if (!strcmp(p, "write") || !strcmp(p, "writen") || !strcmp(p, "writeml")) {
			char *text = strchr(arg, ' '), *q;
			int f;

			if (text) *text++ = 0; else text = (char *)"";
			if (!strcmp(p, "writeml")) for (q = text; *q; q++) if (*q == 1) *q = '\n';
			f = open(arg, O_WRONLY | O_CREAT | O_TRUNC, 0644);
			if (f >= 0) {
				if (write(f, text, strlen(text)) < 0) {}
				if (strcmp(p, "writen") && write(f, "\n", 1) < 0) {}
				close(f);
			}
		}
		p = e + 1;
	}
}

static int pid_alive(const char *pidfile)
{
	char b[32];
	ll pid;

	if (first_line(pidfile, b, sizeof b) < 0 || !all_digits(b)) return 0;
	pid = dec(b);
	return pid > 0 && pid != getpid() && kill((pid_t)pid, 0) == 0;
}

int main(int argc, char **argv)
{
	const char *nflag = envs("SV_NIGHT_FLAG", "/var/run/tc100-sv.night");
	const char *bflag = envs("SV_BUTTON_FLAG", "/var/run/tc100-sv.button");
	const char *sflag = envs("SV_SOUND_FLAG", "/var/run/tc100-sv.sound");
	const char *pidfile = envs("SV_PIDFILE", "/var/run/tc100-supervisord.pid");
	struct sigaction sa;
	int night_on = 0, button_on = 0, sound_on = 0, f;
	ll night_due = 0, button_due = 0, sound_due = 0, t, wake;

	if (argc == 3 && !strcmp(argv[1], "-r")) { replay(argv[2]); return 0; }
	if (argc != 1) { dprintf(2, "usage: tc100-supervisord [-r SCRIPT]\n"); return 2; }
	g_div = env_num("SV_TICK_DIV", 1);
	if (g_div < 1) g_div = 1;
	if (pid_alive(pidfile)) return 0;	/* one daemon: the service scripts start it when they find none */
	setenv("NIGHT_KEEP_AUTO", "1", 1);	/* the daemon stays in auto mode (daynight=2) while it switches */
	memset(&sa, 0, sizeof sa);
	sa.sa_handler = on_term;
	sigaction(SIGTERM, &sa, NULL);
	sigaction(SIGINT, &sa, NULL);
	signal(SIGPIPE, SIG_IGN);
	signal(SIGHUP, SIG_IGN);
	f = open(pidfile, O_WRONLY | O_CREAT | O_TRUNC, 0644);
	if (f >= 0) {
		char b[24];

		snprintf(b, sizeof b, "%d\n", (int)getpid());
		if (write(f, b, strlen(b)) < 0) {}
		close(f);
	}
	while (!g_stop) {
		int n_en = access(nflag, F_OK) == 0, b_en = access(bflag, F_OK) == 0, s_en = access(sflag, F_OK) == 0;

		reap();
		t = mono_ms();
		if (!n_en && !b_en && !s_en) break;	/* nothing left to do: the service scripts start us again when needed */
		if (n_en && !night_on) {
			night_reset();
			console("[auto-night] Daemon started");
			night_due = t + SLP * 1000LL / g_div;
		}
		night_on = n_en;
		if (b_en && !button_on) {
			button_init();
			if (!g_btn_ok) { unlink(bflag); b_en = 0; }	/* the service script sees the flag gone: shell fallback */
			else button_due = t;
		}
		button_on = b_en;
		if (s_en && !sound_on) { sound_reset(); sound_due = t; }	/* the shell loop ran its first turn at once */
		sound_on = s_en;
		if (button_on && t >= button_due) {
			int k = 0;

			while (t >= button_due && k++ < 10) { button_sample(button_read()); button_due += 1000 / g_div; }
			if (t >= button_due) button_due = t + 1000 / g_div;
		}
		if (night_on && t >= night_due) {
			night_iteration();
			night_due = mono_ms() + SLP * 1000LL / g_div;
		}
		if (sound_on && mono_ms() >= sound_due) {
			sound_due = mono_ms() + sound_iteration() * 1000LL / g_div;
			reap();
		}
		wake = 1000 / g_div;
		t = mono_ms();
		if (night_on && night_due - t < wake) wake = night_due - t;
		if (button_on && button_due - t < wake) wake = button_due - t;
		if (sound_on && sound_due - t < wake) wake = sound_due - t;
		if (wake < 10) wake = 10;
		poll(NULL, 0, (int)wake);
	}
	unlink(pidfile);
	return 0;
}
