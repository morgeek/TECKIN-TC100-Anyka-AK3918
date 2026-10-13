/*
 * isp_tune.c — live image tuning for the vendor v4l2rtspserver (part of
 * libtc100fix.so). Enabled when TC100FIX_ISP_TUNE=<path to isp_tune.conf>.
 *
 * A low-priority thread polls the config file (mtime, every 2 s) and applies
 * changes without restarting the stream. Values come from the camera's own
 * libplat_vi.so / libplat_vpss.so (V1.0.04 / V1.1.0), verified by
 * decompilation — note that this enum differs from the public EV300 SDK v18
 * header (which inserts WDR at 5):
 *   ak_vpss_effect_set(vi, 0..4, -50..50)   hue, brightness, saturation,
 *                                           contrast, sharpness; 0 = ISP file
 *   ak_vpss_effect_set(vi, 6, 50|60)        mains frequency (anti-flicker)
 * Effects are stored by the vendor as offsets and re-applied by it after every
 * day/night ISP reload (isp_switch_mode), so they only need setting on change.
 *
 * EXPOSURE_MAX_PCT caps AE exp_time_max at a percentage of the value from the
 * ISP file. The vendor reloads AE attributes on every day/night switch, so the
 * cap is checked and re-applied on every poll; the original is re-captured
 * whenever the live value differs from what we last wrote.
 *
 * NR3D=0 turns the temporal (3D) noise reduction off: tnr_y_enable and
 * tnr_uv_enable cleared in the manual set and in the 9 gain-linked sets,
 * everything else untouched. Removing the key (or NR3D=1) writes the original
 * attributes back. struct vpss_isp_3d_nr_attr of the SDK header is 1124 bytes
 * (u16 mode, pad, 10 x 112-byte sets); the camera's libplat_vpss copies exactly
 * 1124 bytes in ak_vpss_isp_set_3d_nr_attr, so the layout matches. Re-applied
 * after day/night ISP reloads like the exposure cap.
 *
 * State is written to /var/run/isp_tune.status (TC100FIX_ISP_STATUS overrides)
 * for the web UI and MQTT.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define TAG "[tc100fix] "
#define STATUS_DEFAULT "/var/run/isp_tune.status"
#define AE_ATTR_WORDS 51   /* vendor copies 0xCC bytes */
#define NR3D_BYTES 1124    /* vendor copies 1124 bytes */
#define NR3D_SETS 10       /* manual + 9 linkage */
#define NR3D_SET_BYTES 112
#define NR3D_TNR_Y 2       /* byte offsets inside one set */
#define NR3D_TNR_UV 4

enum { E_HUE, E_BRIGHTNESS, E_SATURATION, E_CONTRAST, E_SHARPNESS, E_COUNT };
static const char *const effect_key[E_COUNT] = {
    "HUE", "BRIGHTNESS", "SATURATION", "CONTRAST", "SHARPNESS"
};
#define EFFECT_HZ 6

struct tune {
    int effect[E_COUNT];      /* -50..50, 0 = ISP file */
    int hz;                   /* 0 = leave, 50 or 60 */
    int exp_max_pct;          /* 0 = leave, 10..100 */
    int nr3d;                 /* -1 = leave, 0 = temporal NR off, 1 = original */
};

static void *vi_handle;
static const char *conf_path;
static char status_path[192], status_tmp[200];
static int (*p_effect_set)(void *, int, int);
static int (*p_effect_get)(void *, int, int *);
static int (*p_ae_get)(void *, unsigned long *);
static int (*p_ae_set)(void *, const unsigned long *);
static int (*p_nr_get)(void *, void *);
static int (*p_nr_set)(void *, const void *);

static int clamp(int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }

static void parse_conf(const char *path, struct tune *t)
{
    char line[128];
    FILE *f;
    int i;

    memset(t, 0, sizeof(*t));
    t->nr3d = -1;
    f = fopen(path, "r");
    if (!f)
        return;
    while (fgets(line, sizeof(line), f)) {
        char *eq = strchr(line, '=');
        int v;
        if (line[0] == '#' || !eq)
            continue;
        *eq = '\0';
        v = atoi(eq + 1);
        for (i = 0; i < E_COUNT; i++)
            if (!strcmp(line, effect_key[i]))
                t->effect[i] = clamp(v, -50, 50);
        if (!strcmp(line, "POWER_HZ"))
            t->hz = (v == 50 || v == 60) ? v : 0;
        if (!strcmp(line, "EXPOSURE_MAX_PCT"))
            t->exp_max_pct = v ? clamp(v, 10, 100) : 0;
        if (!strcmp(line, "NR3D"))
            t->nr3d = v ? 1 : 0;
    }
    fclose(f);
}

static void resolve(void)
{
    void *vpss = dlopen("libplat_vpss.so", RTLD_LAZY);
    if (!vpss) {
        fprintf(stderr, TAG "isp: libplat_vpss.so not available\n");
        return;
    }
    p_effect_set = (int (*)(void *, int, int))dlsym(vpss, "ak_vpss_effect_set");
    p_effect_get = (int (*)(void *, int, int *))dlsym(vpss, "ak_vpss_effect_get");
    p_ae_get = (int (*)(void *, unsigned long *))dlsym(vpss, "ak_vpss_isp_get_ae_attr");
    p_ae_set = (int (*)(void *, const unsigned long *))dlsym(vpss, "ak_vpss_isp_set_ae_attr");
    p_nr_get = (int (*)(void *, void *))dlsym(vpss, "ak_vpss_isp_get_3d_nr_attr");
    p_nr_set = (int (*)(void *, const void *))dlsym(vpss, "ak_vpss_isp_set_3d_nr_attr");
}

/* 3D NR state: original attributes of the current ISP mode, and ours. */
static unsigned char nr_orig[NR3D_BYTES], nr_written[NR3D_BYTES], nr_now[NR3D_BYTES];
static int nr_have_orig, nr_off_written;

static unsigned short nr_u16(const unsigned char *b, int set, int off)
{
    unsigned short v;
    memcpy(&v, b + 4 + set * NR3D_SET_BYTES + off, sizeof(v));
    return v;
}

/* off: 1 = temporal NR off, 0 = original. Returns the get/set rc. */
static int apply_nr3d(int off, FILE *st)
{
    int k, rc = -1;

    if (!p_nr_get || !p_nr_set || p_nr_get(vi_handle, nr_now) != 0) {
        if (st) fprintf(st, "NR3D_RC=-1\n");
        return -1;
    }
    /* Anything but what we wrote is the ISP file's own setting. */
    if (!nr_have_orig || !nr_off_written || memcmp(nr_now, nr_written, NR3D_BYTES)) {
        memcpy(nr_orig, nr_now, NR3D_BYTES);
        nr_have_orig = 1;
        nr_off_written = 0;
    }
    rc = 0;
    if (off) {
        unsigned short zero = 0;
        memcpy(nr_written, nr_orig, NR3D_BYTES);
        for (k = 0; k < NR3D_SETS; k++) {
            memcpy(nr_written + 4 + k * NR3D_SET_BYTES + NR3D_TNR_Y, &zero, sizeof(zero));
            memcpy(nr_written + 4 + k * NR3D_SET_BYTES + NR3D_TNR_UV, &zero, sizeof(zero));
        }
        if (memcmp(nr_now, nr_written, NR3D_BYTES)) {
            rc = p_nr_set(vi_handle, nr_written);
            fprintf(stderr, TAG "isp: 3D NR temporal off (rc=%d)\n", rc);
        }
        nr_off_written = 1;
    } else if (nr_off_written) {
        rc = p_nr_set(vi_handle, nr_orig);
        fprintf(stderr, TAG "isp: 3D NR restored (rc=%d)\n", rc);
        nr_off_written = 0;
    }
    if (st) {
        unsigned link_y = 0, link_uv = 0;
        p_nr_get(vi_handle, nr_now);
        for (k = 1; k < NR3D_SETS; k++) {      /* bit k-1 = gain-linked set k-1 */
            if (nr_u16(nr_now, k, NR3D_TNR_Y)) link_y |= 1u << (k - 1);
            if (nr_u16(nr_now, k, NR3D_TNR_UV)) link_uv |= 1u << (k - 1);
        }
        fprintf(st, "NR3D_LINK_TNR_Y=0x%03x\nNR3D_LINK_TNR_UV=0x%03x\n", link_y, link_uv);
        fprintf(st, "NR3D_MODE=%u\nNR3D_TNR_Y=%u\nNR3D_TNR_UV=%u\nNR3D_ORIG_TNR_Y=%u\nNR3D_RC=%d\n",
                (unsigned)(nr_now[0] | nr_now[1] << 8),
                (unsigned)nr_u16(nr_now, 0, NR3D_TNR_Y), (unsigned)nr_u16(nr_now, 0, NR3D_TNR_UV),
                (unsigned)nr_u16(nr_orig, 0, NR3D_TNR_Y), rc);
    }
    return rc;
}

/* Exposure cap state: original exp_time_max of the current ISP mode. */
static unsigned long exp_orig, exp_written;

static void apply_exposure(int pct, FILE *st)
{
    unsigned long ae[AE_ATTR_WORDS], target;

    if (!p_ae_get || !p_ae_set || p_ae_get(vi_handle, ae) != 0) {
        if (st) fprintf(st, "EXPOSURE_RC=-1\n");
        return;
    }
    /* A value we did not write means the ISP file was (re)loaded. */
    if (ae[0] != exp_written || !exp_orig)
        exp_orig = ae[0];
    target = pct ? exp_orig * (unsigned long)pct / 100UL : exp_orig;
    if (target < ae[1])                 /* never below exp_time_min */
        target = ae[1];
    if (target < 1)
        target = 1;
    if (ae[0] != target) {
        ae[0] = target;
        if (p_ae_set(vi_handle, ae) == 0)
            fprintf(stderr, TAG "isp: exp_time_max %lu -> %lu (%d%%)\n", exp_orig, target, pct ? pct : 100);
    }
    exp_written = target;
    if (st) fprintf(st, "EXPOSURE_ORIG=%lu\nEXPOSURE_NOW=%lu\n", exp_orig, ae[0]);
}

static void write_status(const struct tune *t, const int *rc, int exp_active)
{
    FILE *st = fopen(status_tmp, "w");
    int i, v;

    if (!st)
        return;
    for (i = 0; i < E_COUNT; i++) {
        v = 0;
        if (p_effect_get)
            p_effect_get(vi_handle, i, &v);
        fprintf(st, "%s=%d\n%s_RC=%d\n", effect_key[i], v, effect_key[i], rc[i]);
    }
    v = 0;
    if (p_effect_get)
        p_effect_get(vi_handle, EFFECT_HZ, &v);
    fprintf(st, "POWER_HZ=%d\nEXPOSURE_MAX_PCT=%d\nNR3D=%d\n", v, t->exp_max_pct, t->nr3d);
    apply_nr3d(t->nr3d == 0, st);
    if (exp_active) {
        apply_exposure(t->exp_max_pct, st);
    } else if (p_ae_get) {
        unsigned long ae[AE_ATTR_WORDS];
        if (p_ae_get(vi_handle, ae) == 0)
            fprintf(st, "EXPOSURE_NOW=%lu\n", ae[0]);
    }
    fclose(st);
    rename(status_tmp, status_path);
}

static void *isp_thread(void *arg)
{
    struct tune want, have;
    time_t seen = (time_t)-1;
    int rc[E_COUNT];
    int i, first = 1;
    (void)arg;

    memset(&have, 0, sizeof(have));
    memset(rc, 0, sizeof(rc));
    sleep(5);                       /* let the ISP finish starting */
    resolve();
    for (;;) {
        struct stat sb;
        time_t m = stat(conf_path, &sb) == 0 ? sb.st_mtime : 0;

        if (m != seen || first) {
            seen = m;
            parse_conf(conf_path, &want);
            for (i = 0; i < E_COUNT; i++) {
                if (p_effect_set && (want.effect[i] != have.effect[i] || first)) {
                    rc[i] = p_effect_set(vi_handle, i, want.effect[i]);
                    if (want.effect[i] || !first)
                        fprintf(stderr, TAG "isp: %s=%d (rc=%d)\n", effect_key[i], want.effect[i], rc[i]);
                }
            }
            if (p_effect_set && want.hz && want.hz != have.hz)
                fprintf(stderr, TAG "isp: POWER_HZ=%d (rc=%d)\n", want.hz, p_effect_set(vi_handle, EFFECT_HZ, want.hz));
            /* Leaving the cap: restore the original once. */
            if (have.exp_max_pct && !want.exp_max_pct)
                apply_exposure(0, NULL);
            /* write_status applies NR3D (off, or restore if we changed it). */
            have = want;
            write_status(&have, rc, have.exp_max_pct != 0);
            first = 0;
        } else {
            if (have.exp_max_pct)
                apply_exposure(have.exp_max_pct, NULL);   /* survive day/night reloads */
            if (have.nr3d == 0)
                apply_nr3d(1, NULL);
        }
        sleep(2);
    }
    return NULL;
}

void tc100fix_isp_start(void *handle)
{
    static int started;
    pthread_t th;
    pthread_attr_t at;

    conf_path = getenv("TC100FIX_ISP_TUNE");
    if (started || !handle || !conf_path || !conf_path[0])
        return;
    started = 1;
    vi_handle = handle;
    snprintf(status_path, sizeof(status_path), "%s",
             getenv("TC100FIX_ISP_STATUS") ? getenv("TC100FIX_ISP_STATUS") : STATUS_DEFAULT);
    snprintf(status_tmp, sizeof(status_tmp), "%s.tmp", status_path);
    pthread_attr_init(&at);
    pthread_attr_setdetachstate(&at, PTHREAD_CREATE_DETACHED);
    pthread_attr_setstacksize(&at, 32 * 1024);
    if (pthread_create(&th, &at, isp_thread, NULL) == 0)
        fprintf(stderr, TAG "isp tuning thread started (%s)\n", conf_path);
    pthread_attr_destroy(&at);
}
