/* Drives the motion-zone hooks like the vendor server's AnykaMotionDetector::start. */
#include <stdio.h>
#include <stdlib.h>
int ak_md_set_global_sensitivity(int);
int ak_md_set_area_sensitivity(int, int, int *);
static void conf(const char *t) { FILE *f = fopen(getenv("TC100FIX_MDZ"), "w"); fputs(t, f); fclose(f); }
static void dump(void) { char l[200]; FILE *f = fopen(getenv("TC100FIX_MDZ_STATUS"), "r"); if (f) { while (fgets(l, sizeof l, f)) printf("status: %s", l); fclose(f); } }
int main(void)
{
    int map[16 * 12], i;
    setvbuf(stdout, NULL, _IONBF, 0);
    conf("");
    puts("--- no zones"); ak_md_set_global_sensitivity(60); dump();
    conf("MDZ1=\"0,0,50,25\"\nMDZ2=75,50,100,100\nMDZ3=\"60,10,50,40\"\n");
    puts("--- zones"); ak_md_set_global_sensitivity(60); dump();
    for (i = 0; i < 16 * 12; i++) map[i] = i % 16 < 8 ? 70 : 1;            /* vendor rectangle: left half */
    puts("--- vendor area"); ak_md_set_area_sensitivity(16, 12, map); dump();
    return 0;
}
