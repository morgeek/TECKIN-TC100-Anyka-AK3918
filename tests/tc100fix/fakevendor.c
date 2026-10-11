/* Stand-in for the vendor libraries: records every call it receives. */
#include <stdio.h>
#define LOG(...) (printf(__VA_ARGS__), putchar('\n'))
int ak_vi_set_switch_fps_enable(void *h, int e) { LOG("vendor switch_fps_enable %d", e); return h ? 0 : -1; }
int ak_vi_set_fps(void *h, int fps) { (void)h; LOG("vendor set_fps %d", fps); return 0; }
int ak_ai_set_aec(void *h, int e) { (void)h; LOG("vendor set_aec %d", e); return 0; }
int ak_ai_set_nr_agc(void *h, int e) { (void)h; LOG("vendor set_nr_agc %d", e); return 0; }
int ak_ai_start_capture(void *h) { (void)h; LOG("vendor start_capture"); return 0; }
int ak_ai_stop_capture(void *h) { (void)h; LOG("vendor stop_capture"); return 0; }
int ak_print_set_level(int l, int a) { (void)a; LOG("vendor print_level %d", l); return 0; }
