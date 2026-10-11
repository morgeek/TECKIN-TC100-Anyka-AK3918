/* Calls the vendor API in the order v4l2rtspserver uses it. */
#include <stdio.h>
int ak_print_set_level(int, int);
int ak_vi_set_fps(void *, int);
int ak_ai_set_aec(void *, int);
int ak_ai_set_nr_agc(void *, int);
int ak_ai_start_capture(void *);
int ak_ai_stop_capture(void *);
int main(void)
{
    int h = 1;
    setvbuf(stdout, NULL, _IONBF, 0);
    ak_print_set_level(3, 0);
    printf("rc set_fps %d\n", ak_vi_set_fps(&h, 25));
    ak_ai_set_aec(&h, 1);
    ak_ai_set_nr_agc(&h, 1);
    printf("rc start_capture %d\n", ak_ai_start_capture(&h));
    printf("rc stop_capture %d\n", ak_ai_stop_capture(&h));
    return 0;
}
