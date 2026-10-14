/*
 * od.c — image statistics for occlusion ("lens covered") detection, part of
 * libtc100fix.so. Enabled when TC100FIX_OD=<output file, e.g. /var/run/od>.
 *
 * The vendor libplat_vpss.so has no occlusion algorithm, only the ISP
 * statistics it is built from: ak_vpss_od_get() fills 5 autofocus (sharpness)
 * values, a pixel total and a 256-bin RGB histogram (struct vpss_od_info of
 * the EV300 SDK; the camera's library writes the total at +0x14 and copies
 * 0x400 bytes of histogram at +0x18, matching that layout). A low-priority
 * thread samples them every 2 s and writes one line, replaced atomically:
 *
 *   epoch af0 af1 af2 af3 af4 total mean std dark_pct peak_pct
 *
 * mean/std are histogram bin statistics, dark_pct the share of the pixels in
 * bins < 32, peak_pct the share in the fullest 8-bin band. Measured on a
 * TC100: the last word of the histogram (bin 255) holds a ~76 M aggregate,
 * not a count, and the separate total reads 0, so bins 0-254 are used. A
 * covered lens gives a near-zero sharpness and a narrow histogram; the
 * decision (relative to the scene's usual values) is made in the shell
 * (controlscripts/tamper-detection), which can be tuned without a rebuild.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <math.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define TAG "[tc100fix] "

struct od_stats {
    unsigned int af[5];
    unsigned int total;
    unsigned int hist[256];
};

static void *od_handle;
static const char *od_path;

static void *od_thread(void *arg)
{
    int (*od_get)(void *, struct od_stats *) = NULL;
    void *vpss;
    char tmp[200];
    static struct od_stats st;
    (void)arg;

    sleep(6);                           /* let the ISP finish starting */
    vpss = dlopen("libplat_vpss.so", RTLD_LAZY);
    if (vpss)
        od_get = (int (*)(void *, struct od_stats *))dlsym(vpss, "ak_vpss_od_get");
    if (!od_get) {
        fprintf(stderr, TAG "od: ak_vpss_od_get not available\n");
        return NULL;
    }
    snprintf(tmp, sizeof(tmp), "%s.tmp", od_path);
    for (;;) {
        memset(&st, 0, sizeof(st));
        if (od_get(od_handle, &st) == 0) {
            double n = 0, sum = 0, sq = 0, dark = 0, band = 0, best = 0, mean, sd;
            int i;
            FILE *f;
            for (i = 0; i < 255; i++) {
                n += st.hist[i];
                sum += (double)st.hist[i] * i;
                if (i < 32)
                    dark += st.hist[i];
            }
            for (i = 0; i < 255; i++)
                sq += (double)st.hist[i] * i * i;
            for (i = 0; i + 8 <= 255; i++) {
                int j;
                band = 0;
                for (j = 0; j < 8; j++)
                    band += st.hist[i + j];
                if (band > best)
                    best = band;
            }
            mean = n > 0 ? sum / n : 0;
            sd = n > 0 ? sqrt(sq / n - mean * mean) : 0;
            f = fopen(tmp, "w");
            if (f) {
                fprintf(f, "%ld %u %u %u %u %u %u %.0f %.0f %.0f %.0f\n", (long)time(NULL),
                        st.af[0], st.af[1], st.af[2], st.af[3], st.af[4], st.total,
                        mean, sd, n > 0 ? 100.0 * dark / n : 0, n > 0 ? 100.0 * best / n : 0);
                fclose(f);
                rename(tmp, od_path);
            }
            if (getenv("TC100FIX_OD_RAW")) {   /* debugging: raw histogram */
                char raw[208];
                snprintf(raw, sizeof(raw), "%s.raw", od_path);
                f = fopen(raw, "w");
                if (f) {
                    for (i = 0; i < 256; i++)
                        fprintf(f, "%u%c", st.hist[i], i % 16 == 15 ? '\n' : ' ');
                    fclose(f);
                }
            }
        }
        sleep(2);
    }
    return NULL;
}

void tc100fix_od_start(void *handle)
{
    static int started;
    pthread_t th;
    pthread_attr_t at;

    od_path = getenv("TC100FIX_OD");
    if (started || !handle || !od_path || !od_path[0])
        return;
    started = 1;
    od_handle = handle;
    pthread_attr_init(&at);
    pthread_attr_setdetachstate(&at, PTHREAD_CREATE_DETACHED);
    pthread_attr_setstacksize(&at, 32 * 1024);
    if (pthread_create(&th, &at, od_thread, NULL) == 0)
        fprintf(stderr, TAG "od statistics thread started (%s)\n", od_path);
    pthread_attr_destroy(&at);
}
