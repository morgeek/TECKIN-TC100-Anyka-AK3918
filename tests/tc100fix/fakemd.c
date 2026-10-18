/* Stand-in for libmpi_md.so: prints what the detector would be given. */
#include <stdio.h>
int ak_md_get_dimension_max(int *w, int *h) { *w = 16; *h = 12; return 0; }
int ak_md_set_global_sensitivity(int s) { printf("md global %d\n", s); return 0; }
int ak_md_set_area_sensitivity(int w, int h, int *m)
{
    int i, off = 0, x, y;
    if (32 % w || w * h <= 0) { printf("md area refused %dx%d\n", w, h); return -1; }
    for (i = 0; i < w * h; i++) { if (m[i] < 1 || m[i] > 100) { printf("md area bad value %d\n", m[i]); return -1; } off += m[i] == 1; }
    printf("md area %dx%d off=%d\n", w, h, off);
    for (y = 0; y < h; y++) { printf("md row %2d ", y); for (x = 0; x < w; x++) putchar(m[y * w + x] == 1 ? '.' : 'X'); putchar('\n'); }
    return 0;
}
