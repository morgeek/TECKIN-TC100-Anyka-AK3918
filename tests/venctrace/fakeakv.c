#include <string.h>
#include <stdint.h>
static void *cb[22];
int AKV_Encoder_Init(void *t) { memcpy(cb, t, sizeof(cb)); return 1; }
void fake_encode(void) {
    uint32_t v; uint32_t *d;
    ((void (*)(uint32_t, uint32_t))cb[4])(0x20020010, 0x1234);
    v = ((uint32_t (*)(uint32_t))cb[3])(0x20020014);
    d = ((uint32_t *(*)(uint32_t, uint32_t))cb[5])(4096, 0);
    ((void (*)(uint32_t))cb[19])(7);
    ((int (*)(uint32_t *))cb[6])(d);
    (void)v;
}
