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

#define TAG "[tc100fix] "

extern char **environ;
static char *env_start;   /* first environment string, captured before main() */

__attribute__((constructor)) static void tc100fix_init(void)
{
    if (environ && environ[0])
        env_start = environ[0];
}

void tc100fix_isp_start(void *handle);   /* isp_tune.c */

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
    return real ? real(handle, fps) : -1;
}

/* ---------------------------------------------------------------- audio */

int ak_ai_set_aec(void *handle, int enable)
{
    static int (*real)(void *, int);
    if (!real)
        real = (int (*)(void *, int))next_sym("ak_ai_set_aec");
    if (env_on("TC100FIX_MIC_OFF"))
        enable = 0;
    return real ? real(handle, enable) : -1;
}

int ak_ai_set_nr_agc(void *handle, int enable)
{
    static int (*real)(void *, int);
    if (!real)
        real = (int (*)(void *, int))next_sym("ak_ai_set_nr_agc");
    if (env_on("TC100FIX_MIC_OFF"))
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
