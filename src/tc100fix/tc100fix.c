/*
 * libtc100fix.so — runtime fixes for the closed vendor v4l2rtspserver.
 *
 * Preloaded for v4l2rtspserver only (controlscripts/rtsp-h26x). Each fix is
 * off unless its environment variable is set, so the library is inert when
 * loaded with no configuration.
 *
 * TC100FIX_FPS_LOCK=1
 *   The vendor libplat_vi.so (V1.0.04, AK3918EV300) arms an automatic
 *   frame-rate switch from ak_vi_set_channel_attr() -> isp_fps_main(): the
 *   sensor drops to ~10 fps when the AE gain rises and back to 25 fps later.
 *   v4l2rtspserver calls ak_vi_set_fps() once, right after
 *   ak_vi_set_channel_attr(); we disable the switch there, then forward.
 *
 * TC100FIX_MIC_OFF=1   (set by rtsp-h26x only when RTSP_AUDIO=0)
 *   AnykaCameraManager::setAudioParams() hard-codes ak_ai_set_aec(h, 1) and
 *   ak_ai_set_nr_agc(h, 1), and start() calls ak_ai_start_capture() even when
 *   no audio stream is served. Measured on the TC100: aec_task ~4.5 % CPU and
 *   ai_capture ~2 % with RTSP_AUDIO=0. We force AEC/NR off and report a
 *   successful capture start without starting the ADC.
 *
 * TC100FIX_AEC_OFF=1   (set by rtsp-h26x when sound detection is enabled)
 *   Same AEC/NR/AGC override as TC100FIX_MIC_OFF, but the microphone keeps
 *   capturing: the echo canceller and noise gate are only useful for two-way
 *   audio, and they flatten the signal a level meter or Frigate listens to.
 *
 * TC100FIX_DC_BLOCK=1  (set with TC100FIX_AEC_OFF)
 *   Without the vendor noise processing the ADC output carries a DC offset
 *   (~ -1450 of 32768 on the TC100). It would reach the RTSP audio (recordings,
 *   Frigate's audio detector, whose volume gate sees it as permanent sound).
 *   A one-pole DC blocker is applied in place to each frame before the
 *   encoder gets it.
 *
 * TC100FIX_ISP_TUNE=<path>
 *   Live image tuning (brightness, contrast, ..., exposure cap) from a config
 *   file, applied by a background thread without restarting the stream. See
 *   isp_tune.c.
 *
 * TC100FIX_HIDE_CREDENTIALS=1
 *   rtsp-h26x passes "-U user:password" on the command line, readable by
 *   anything that lists processes (ps, /proc/<pid>/cmdline, the web UI's
 *   process views). v4l2rtspserver copies it into a std::string while parsing
 *   options, so once the camera starts (ak_vi_set_fps) we overwrite the
 *   argument in place with '*'. The argv area is located just before the
 *   first environment string and checked byte for byte against
 *   /proc/self/cmdline; on any mismatch nothing is touched.
 *
 * TC100FIX_SOUND_LEVEL=<path>
 *   Sound level meter for scripts/sound-detection.sh. The vendor audio
 *   encoder (libmpi_aenc) pulls raw 16-bit PCM from the microphone with
 *   ak_ai_get_frame(); we pass each frame through and keep its RMS and peak,
 *   both measured around the window's mean: with the vendor noise processing
 *   off the ADC output carries a DC offset (~ -1450 on the TC100, i.e.
 *   -27 dBFS on its own), which must not count as sound.
 *   Once a second (>= 0.5 s of audio) we write to <path> (tmpfs, atomic):
 *     "<epoch> <rms_dbfs> <peak_dbfs> <events> <last_event_epoch> <last_event_dbfs>"
 *   A window whose RMS reaches the threshold (dBFS, read every 10 s from
 *   <path>.threshold, written by sound-detection.sh; default -30) counts as an
 *   event, so the daemon can poll slowly without missing short sounds.
 *   No second reader on the ADC, no extra thread.
 *   The meter only sees audio while the encoder runs, i.e. while audio is
 *   served (rtsp-h26x serves it whenever sound detection is enabled).
 *
 * TC100FIX_PRINT_LEVEL=<0..9>
 *   The AnykaCameraManager constructor forces ak_print_set_level(3), which
 *   rewrites /var/log/ak_print_level for every vendor library. We substitute
 *   the configured level.
 *
 * Build: src/tc100fix/build.sh (Anyka arm-anykav200 uClibc toolchain).
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <math.h>
#include <time.h>

#define TAG "[tc100fix] "

extern char **environ;
static char *env_start;   /* first environment string, captured before main() */

__attribute__((constructor)) static void tc100fix_init(void)
{
    if (environ && environ[0])
        env_start = environ[0];
}

void tc100fix_isp_start(void *handle);   /* isp_tune.c */
void tc100fix_od_start(void *handle);    /* od.c */

static int env_on(const char *name)
{
    const char *v = getenv(name);
    return v && (!strcmp(v, "1") || !strcmp(v, "true") || !strcmp(v, "yes") || !strcmp(v, "on"));
}

static void *next_sym(const char *name)
{
    void *p = dlsym(RTLD_NEXT, name);
    if (!p)
        fprintf(stderr, TAG "%s not found in the next library\n", name);
    return p;
}

/* ---------------------------------------------------------- credentials */

static void hide_credentials(void)
{
    static int done;
    char buf[1024], *start, *p, *end;
    ssize_t n;
    int fd, hidden = 0;

    if (done || !env_on("TC100FIX_HIDE_CREDENTIALS") || !env_start)
        return;
    done = 1;
    fd = open("/proc/self/cmdline", O_RDONLY);
    if (fd < 0)
        return;
    n = read(fd, buf, sizeof(buf));
    close(fd);
    if (n <= 0 || n >= (ssize_t)sizeof(buf))
        return;
    start = env_start - n;          /* argv strings end where the env begins */
    if (memcmp(start, buf, (size_t)n)) {
        fprintf(stderr, TAG "credentials: argv not found, left as is\n");
        return;
    }
    end = start + n;
    for (p = start; p < end; p += strlen(p) + 1) {
        if (!strcmp(p, "-U") && p + 3 < end) {
            char *v = p + 3;
            memset(v, '*', strlen(v));
            hidden++;
        } else if (!strncmp(p, "-U", 2) && p[2]) {
            memset(p + 2, '*', strlen(p + 2));
            hidden++;
        }
    }
    fprintf(stderr, TAG "credentials hidden from the process list (%d)\n", hidden);
}

/* ---------------------------------------------------------------- video */

int ak_vi_set_fps(void *handle, int fps)
{
    static int (*real)(void *, int);
    static int (*set_switch)(void *, int);

    if (!real)
        real = (int (*)(void *, int))next_sym("ak_vi_set_fps");
    hide_credentials();                 /* options are parsed by now */
    if (env_on("TC100FIX_FPS_LOCK") && handle) {
        if (!set_switch)
            set_switch = (int (*)(void *, int))next_sym("ak_vi_set_switch_fps_enable");
        if (set_switch)
            fprintf(stderr, TAG "auto fps switch disabled (rc=%d)\n", set_switch(handle, 0));
    }
    if (handle)
        tc100fix_isp_start(handle);       /* no-op unless TC100FIX_ISP_TUNE set */
    if (handle)
        tc100fix_od_start(handle);        /* no-op unless TC100FIX_OD set */
    return real ? real(handle, fps) : -1;
}

/* ---------------------------------------------------------------- audio */

int ak_ai_set_aec(void *handle, int enable)
{
    static int (*real)(void *, int);
    if (!real)
        real = (int (*)(void *, int))next_sym("ak_ai_set_aec");
    if (env_on("TC100FIX_MIC_OFF") || env_on("TC100FIX_AEC_OFF"))
        enable = 0;
    return real ? real(handle, enable) : -1;
}

int ak_ai_set_nr_agc(void *handle, int enable)
{
    static int (*real)(void *, int);
    if (!real)
        real = (int (*)(void *, int))next_sym("ak_ai_set_nr_agc");
    if (env_on("TC100FIX_MIC_OFF") || env_on("TC100FIX_AEC_OFF"))
        enable = 0;
    return real ? real(handle, enable) : -1;
}

int ak_ai_start_capture(void *handle)
{
    static int (*real)(void *);
    if (env_on("TC100FIX_MIC_OFF")) {
        fprintf(stderr, TAG "audio capture skipped (no audio stream served)\n");
        return 0;
    }
    if (!real)
        real = (int (*)(void *))next_sym("ak_ai_start_capture");
    return real ? real(handle) : -1;
}

int ak_ai_stop_capture(void *handle)
{
    static int (*real)(void *);
    if (env_on("TC100FIX_MIC_OFF"))
        return 0;   /* never started */
    if (!real)
        real = (int (*)(void *))next_sym("ak_ai_stop_capture");
    return real ? real(handle) : -1;
}

/* ---------------------------------------------------------- sound level */

struct ak_frame {                  /* struct frame, ak_global.h */
    unsigned char *data;
    unsigned int len;
    unsigned long long ts;
    unsigned long seq_no;
};

static void sound_meter(const struct ak_frame *f)
{
    static const char *path;
    static int checked;
    static double sum, sum_sq;
    static int vmin = 32767, vmax = -32768;
    static unsigned long n_samples;
    static time_t last, thr_read;
    static int threshold = -30;
    static unsigned long events;
    static long last_event;
    static int last_event_db = -96;
    const short *pcm;
    unsigned int i, n;
    time_t now;

    if (!checked) {
        path = getenv("TC100FIX_SOUND_LEVEL");
        checked = 1;
    }
    if (!path || !*path || !f || !f->data || f->len < 2)
        return;
    pcm = (const short *)f->data;
    n = f->len / 2;
    for (i = 0; i < n; i++) {
        int v = pcm[i];
        if (v < vmin) vmin = v;
        if (v > vmax) vmax = v;
        sum += v;
        sum_sq += (double)v * v;
    }
    n_samples += n;
    now = time(NULL);
    if (n_samples >= 4000 && now != last) {   /* >= 0.5 s at 8 kHz, at most 1/s */
        char tmp[256], line[96];
        double mean = sum / n_samples;
        double var = sum_sq / n_samples - mean * mean;
        double rms = var > 0 ? sqrt(var) : 0;
        double peak = vmax - mean > mean - vmin ? vmax - mean : mean - vmin;
        int rms_db = rms > 0.5 ? (int)lrint(20.0 * log10(rms / 32768.0)) : -96;
        int peak_db = peak > 0.5 ? (int)lrint(20.0 * log10(peak / 32768.0)) : -96;
        int fd, len;
        if (now - thr_read >= 10) {          /* threshold set by the daemon */
            int t, tfd;
            char tb[16];
            snprintf(tmp, sizeof(tmp), "%s.threshold", path);
            tfd = open(tmp, O_RDONLY);
            if (tfd >= 0) {
                int r = (int)read(tfd, tb, sizeof(tb) - 1);
                close(tfd);
                if (r > 0) {
                    tb[r] = 0;
                    t = atoi(tb);
                    if (t <= 0 && t >= -90)
                        threshold = t;
                }
            }
            thr_read = now;
        }
        if (rms_db >= threshold) {
            events++;
            last_event = (long)now;
            last_event_db = rms_db;
        }
        snprintf(tmp, sizeof(tmp), "%s.tmp", path);
        len = snprintf(line, sizeof(line), "%ld %d %d %lu %ld %d\n", (long)now, rms_db, peak_db,
                       events, last_event, last_event_db);
        fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (fd >= 0) {
            if (write(fd, line, (size_t)len) == len)
                rename(tmp, path);
            close(fd);
        }
        sum = 0; sum_sq = 0; n_samples = 0; vmin = 32767; vmax = -32768; last = now;
    }
}

static void dc_block(struct ak_frame *f)
{
    /* y[n] = x[n] - x[n-1] + R*y[n-1], R = 0.995 (corner ~6 Hz at 8 kHz),
     * fixed point Q15. */
    static int on = -1;
    static int x1, y1;
    short *pcm;
    unsigned int i, n;
    if (on < 0)
        on = env_on("TC100FIX_DC_BLOCK");
    if (!on || !f || !f->data || f->len < 2)
        return;
    pcm = (short *)f->data;
    n = f->len / 2;
    for (i = 0; i < n; i++) {
        int x = pcm[i];
        int y = x - x1 + ((32604 * y1) >> 15);
        x1 = x;
        y1 = y;
        pcm[i] = (short)(y > 32767 ? 32767 : y < -32768 ? -32768 : y);
    }
}

int ak_ai_get_frame(void *handle, struct ak_frame *frame, long ms)
{
    static int (*real)(void *, struct ak_frame *, long);
    int rc;
    if (!real)
        real = (int (*)(void *, struct ak_frame *, long))next_sym("ak_ai_get_frame");
    if (!real)
        return -1;
    rc = real(handle, frame, ms);
    if (rc == 0) {
        dc_block(frame);
        sound_meter(frame);
    }
    return rc;
}

/* ---------------------------------------------------------------- logging */

int ak_print_set_level(int level, int arg)
{
    static int (*real)(int, int);
    const char *v = getenv("TC100FIX_PRINT_LEVEL");
    if (!real)
        real = (int (*)(int, int))next_sym("ak_print_set_level");
    if (v && v[0] >= '0' && v[0] <= '9' && v[1] == '\0') {
        fprintf(stderr, TAG "vendor print level %d -> %c\n", level, v[0]);
        level = v[0] - '0';
    }
    return real ? real(level, arg) : -1;
}

/* ------------------------------------------------------- day/night polling */

/*
 * TC100FIX_DAYNIGHT_POLL_MS=<ms>
 *   AnykaDayNight::processAutoModeThread() polls the ISP's day/night level
 *   with a hard-coded ak_sleep_ms(100), and with daynightinfo=1 rewrites
 *   /var/run/lum and /var/run/awb on every turn: ~20 file writes a second
 *   for a dashboard badge. Only that call is stretched: it is the one whose
 *   return address is 0x37d3c in the bundled (non-PIE) v4l2rtspserver, md5
 *   e02408de163ce9d64864fb871c34fe87. Any other binary or caller is left
 *   untouched. Range 100-2000 ms.
 */
#define DAYNIGHT_SLEEP_RET ((void *)0x37d3c)

void ak_sleep_ms(int ms)
{
    static void (*real)(int);
    static int poll_ms = -1;

    if (!real)
        real = (void (*)(int))next_sym("ak_sleep_ms");
    if (poll_ms < 0) {
        const char *v = getenv("TC100FIX_DAYNIGHT_POLL_MS");
        int p = v ? atoi(v) : 0;
        poll_ms = (p >= 100 && p <= 2000) ? p : 0;
        if (poll_ms)
            fprintf(stderr, TAG "day/night poll every %d ms\n", poll_ms);
    }
    if (poll_ms && ms == 100 && __builtin_return_address(0) == DAYNIGHT_SLEEP_RET)
        ms = poll_ms;
    if (real)
        real(ms);
    else
        usleep((useconds_t)ms * 1000);
}
