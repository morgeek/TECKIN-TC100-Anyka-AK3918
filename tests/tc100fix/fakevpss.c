/* Stand-in for libplat_vpss.so: effect offsets and AE attributes in memory. */
#include <stdio.h>
#include <string.h>
static int eff[7];
static unsigned long ae[51] = { 1000, 10 };   /* exp_time_max, exp_time_min */
int ak_vpss_effect_set(void *h, int t, int v) { (void)h; if (t < 0 || t > 6) return -1; eff[t] = v; printf("vpss effect_set %d %d\n", t, v); return 0; }
int ak_vpss_effect_get(void *h, int t, int *v) { (void)h; if (t < 0 || t > 6) return -1; *v = eff[t]; return 0; }
int ak_vpss_isp_get_ae_attr(void *h, unsigned long *a) { (void)h; memcpy(a, ae, sizeof(ae)); return 0; }
int ak_vpss_isp_set_ae_attr(void *h, const unsigned long *a) { (void)h; memcpy(ae, a, sizeof(ae)); printf("vpss ae exp_time_max=%lu\n", ae[0]); return 0; }
/* test hook: simulate a day/night ISP reload of the AE attributes */
void fake_isp_reload(void) { ae[0] = 1000; printf("vpss reload exp_time_max=1000\n"); }
