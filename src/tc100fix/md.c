/*
 * md.c — motion zones for the vendor motion detection, part of libtc100fix.so.
 *
 * The vendor server starts the SoC motion detector (libmpi_md) with one
 * sensitivity for the whole picture (ak_md_set_global_sensitivity) or with a
 * grid of per-cell sensitivities (ak_md_set_area_sensitivity, for the
 * mdx/mdy/mdwidth/mdheight rectangle of rtspserver.conf). Both calls are
 * caught here: with zones to ignore in /mnt/config/motion_zones.conf
 * (TC100FIX_MDZ to use another file: MDZ1..MDZ4="x1,y1,x2,y2" in percent of
 * the picture), the grid is sent
 * instead, the cells whose centre lies in a zone getting sensitivity 1.
 * In libmpi_md, sensitivity 1 sets the cell threshold to 65535, i.e. the
 * cell never triggers (read from md_set_area_sensitivity: s 1 -> 0xffff,
 * 2..10 -> 13107 + (11 - s) * 5240, ..., valid range 1..100). The grid size
 * is the library's maximum (ak_md_get_dimension_max), as the vendor uses.
 *
 * The zones are read each time the vendor (re)starts the detector: at
 * startup, and when the detection settings change (setconf -k m). Changing
 * the grid while the detector runs would free a buffer its thread may be
 * reading, so it is never done from here.
 *
 * TC100FIX_MDZ_STATUS (default /var/run/md_zones): one line per start,
 *   starts=N grid=WxH sensitivity=S ignored=K result=area|global|error
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MDZ_MAX 4

static int (*real_global)(int);
static int (*real_area)(int, int, int *);
static int (*real_dim)(int *, int *);
static unsigned md_starts;

static void md_resolve(void)
{
    if (!real_global) real_global = (int (*)(int))dlsym(RTLD_NEXT, "ak_md_set_global_sensitivity");
    if (!real_area) real_area = (int (*)(int, int, int *))dlsym(RTLD_NEXT, "ak_md_set_area_sensitivity");
    if (!real_dim) real_dim = (int (*)(int *, int *))dlsym(RTLD_NEXT, "ak_md_get_dimension_max");
}

/* Zones from the file: up to MDZ_MAX rectangles in percent; returns the count. */
static int md_zones(int z[MDZ_MAX][4])
{
    const char *path = getenv("TC100FIX_MDZ");
    char line[128];
    int n = 0;
    FILE *f;
    if (!path || !path[0]) path = "/mnt/config/motion_zones.conf";
    if (!(f = fopen(path, "r"))) return 0;
    while (n < MDZ_MAX && fgets(line, sizeof(line), f)) {
        int k, a, b, c, d;
        char q;
        if (sscanf(line, "MDZ%d=\"%d,%d,%d,%d%c", &k, &a, &b, &c, &d, &q) != 6 &&
            sscanf(line, "MDZ%d=%d,%d,%d,%d", &k, &a, &b, &c, &d) != 5)
            continue;
        if (k < 1 || k > MDZ_MAX || a < 0 || b < 0 || c > 100 || d > 100 || c <= a || d <= b) continue;
        z[n][0] = a; z[n][1] = b; z[n][2] = c; z[n][3] = d; n++;
    }
    fclose(f);
    return n;
}

static void md_status(int w, int h, int sens, int ignored, const char *result)
{
    const char *path = getenv("TC100FIX_MDZ_STATUS");
    char tmp[200];
    FILE *f;
    if (!path || !path[0]) path = "/var/run/md_zones";
    snprintf(tmp, sizeof(tmp), "%s.tmp", path);
    if (!(f = fopen(tmp, "w"))) return;
    fprintf(f, "starts=%u grid=%dx%d sensitivity=%d ignored=%d result=%s\n", md_starts, w, h, sens, ignored, result);
    fclose(f);
    rename(tmp, path);
}

/* base: the vendor's per-cell map (w*h) or NULL for one sensitivity. */
static int md_apply(int w, int h, const int *base, int sens)
{
    int z[MDZ_MAX][4], nz = md_zones(z), x, y, i, ignored = 0, r;
    int *map;
    md_starts++;
    if (!nz) {
        r = base ? real_area(w, h, (int *)base) : real_global(sens);
        md_status(w, h, sens, 0, r == 0 ? (base ? "area" : "global") : "error");
        return r;
    }
    if (!base && (!real_dim || real_dim(&w, &h) != 0 || w <= 0 || h <= 0 || w * h > 4096)) {
        r = real_global(sens);
        md_status(0, 0, sens, 0, r == 0 ? "global (no grid)" : "error");
        return r;
    }
    if (!(map = malloc(sizeof(int) * (size_t)(w * h)))) return base ? real_area(w, h, (int *)base) : real_global(sens);
    for (y = 0; y < h; y++)
        for (x = 0; x < w; x++) {
            int cx = (2 * x + 1) * 50 / w, cy = (2 * y + 1) * 50 / h, in = 0;   /* cell centre, percent */
            for (i = 0; i < nz; i++)
                if (cx >= z[i][0] && cx < z[i][2] && cy >= z[i][1] && cy < z[i][3]) in = 1;
            map[y * w + x] = in ? 1 : base ? base[y * w + x] : sens;
            if (map[y * w + x] < 1) map[y * w + x] = 1;
            if (map[y * w + x] > 100) map[y * w + x] = 100;
            ignored += in;
        }
    r = real_area(w, h, map);
    if (r != 0)                         /* never leave the detector without settings */
        r = base ? real_area(w, h, (int *)base) : real_global(sens);
    md_status(w, h, sens, ignored, r == 0 ? "area" : "error");
    free(map);
    return r;
}

int ak_md_set_global_sensitivity(int sensitivity)
{
    md_resolve();
    if (!real_global) return -1;
    if (!real_area) return real_global(sensitivity);
    return md_apply(0, 0, NULL, sensitivity);
}

int ak_md_set_area_sensitivity(int horizon_num, int vertical_num, int *area_sensitivity)
{
    int i, s = 1;
    md_resolve();
    if (!real_area) return -1;
    if (!area_sensitivity || horizon_num <= 0 || vertical_num <= 0 || horizon_num * vertical_num > 4096)
        return real_area(horizon_num, vertical_num, area_sensitivity);
    for (i = 0; i < horizon_num * vertical_num; i++) if (area_sensitivity[i] > s) s = area_sensitivity[i];
    return md_apply(horizon_num, vertical_num, area_sensitivity, s);
}
