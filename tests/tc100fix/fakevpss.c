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
/* Privacy masks: SDK struct vpss_mask_area_info (2 x 4 x 10 bytes). */
struct mask_area { unsigned short x1, x2, y1, y2; unsigned char enable, pad; };
static struct mask_area masks[8];
int ak_vpss_mask_set_area(void *h, const void *p) { int i; (void)h; memcpy(masks, p, sizeof(masks));
    for (i = 0; i < 8; i++) if (masks[i].enable) printf("vpss mask %s%d %u,%u-%u,%u\n", i < 4 ? "main" : "sub", i % 4, masks[i].x1, masks[i].y1, masks[i].x2, masks[i].y2);
    printf("vpss mask_set\n"); return 0; }
int ak_vpss_mask_get_area(void *h, void *p) { (void)h; memcpy(p, masks, sizeof(masks)); return 0; }
int ak_vpss_mask_set_color(void *h, const unsigned char *c) { (void)h; printf("vpss mask_color type=%u y=%u\n", c[0], c[2]); return 0; }
/* test hook: the ISP dropped the masks (day/night reload) */
void fake_mask_reset(void) { memset(masks, 0, sizeof(masks)); printf("vpss masks lost\n"); }
