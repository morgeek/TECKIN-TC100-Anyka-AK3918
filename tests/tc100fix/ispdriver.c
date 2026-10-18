/* Drives the ISP tuning thread: start it, change the config, simulate a reload. */
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
int ak_vi_set_fps(void *, int);
void fake_isp_reload(void);
void fake_mask_reset(void);
static void conf(const char *path, const char *text) { FILE *f = fopen(path, "w"); fputs(text, f); fclose(f); }
static void dump(const char *path) { char l[128]; FILE *f = fopen(path, "r"); if (!f) { puts("status: none"); return; } while (fgets(l, sizeof l, f)) printf("status: %s", l); fclose(f); }
int main(void)
{
    const char *c = getenv("TC100FIX_ISP_TUNE"), *s = getenv("TC100FIX_ISP_STATUS");
    int h = 1;
    setvbuf(stdout, NULL, _IONBF, 0);
    conf(c, "BRIGHTNESS=20\nCONTRAST=-10\nSHARPNESS=99\nEXPOSURE_MAX_PCT=50\n");
    ak_vi_set_fps(&h, 25);
    sleep(8);  puts("--- after start"); dump(s);
    conf(c, "BRIGHTNESS=20\nCONTRAST=0\nPOWER_HZ=50\nEXPOSURE_MAX_PCT=50\n");
    sleep(4);  puts("--- after change");
    fake_isp_reload();
    sleep(4);  puts("--- after reload");
    conf(c, "BRIGHTNESS=0\n");
    sleep(4);  puts("--- after reset"); dump(s);
    /* Privacy masks: 2 areas, grey; lost on a reload; then removed. */
    conf(c, "MASK1=0,0,50,50\nMASK3=90,80,100,100\nMASK2=60,10,50,40\nMASK_COLOR=gray\n");
    sleep(4);  puts("--- after masks"); dump(s);
    fake_mask_reset();
    sleep(4);  puts("--- after mask reload");
    conf(c, "BRIGHTNESS=0\n");
    sleep(4);  puts("--- after masks off");
    return 0;
}
