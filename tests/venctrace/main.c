#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
int AKV_Encoder_Init(void *t); void fake_encode(void);
void tc100fix_venctrace_frame(const unsigned char *buf, unsigned int len, int jpeg);
static uint32_t regs[16];
static uint32_t rd(uint32_t a) { return regs[(a >> 2) & 15] + 1; }
static void wr(uint32_t a, uint32_t v) { regs[(a >> 2) & 15] = v; }
static uint32_t *al(uint32_t s, uint32_t x) {
    uint32_t *d = calloc(4, 4); unsigned char *m = mmap(NULL, s, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_32BIT, -1, 0);
    (void)x; memset(m, 0xab, s); d[0] = (uint32_t)(uintptr_t)m; d[1] = 0x81000000u + s; return d;
}
static int fr(uint32_t *d) { free(d); return 0; }
static void irq(uint32_t a) { (void)a; }
int main(void) {
    void *t[22]; unsigned char f[] = {0,0,0,1,0x40,1};
    memset(t, 0, sizeof(t));
    t[3] = (void *)rd; t[4] = (void *)wr; t[5] = (void *)al; t[6] = (void *)fr; t[19] = (void *)irq;
    AKV_Encoder_Init(t); fake_encode(); tc100fix_venctrace_frame(f, sizeof(f), 0);
    return 0;
}
