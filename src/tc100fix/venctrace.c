/*
 * venctrace.c — record what the vendor video encoder does to the hardware,
 * part of libtc100fix.so. A study tool for a free H.265 encoder
 * (claude/h265-free-encoder-plan in the project notes); off unless
 * TC100FIX_VENC_TRACE is set. It changes nothing in the encoding.
 *
 * libakv_encode.so (Allegro DVT control software, "AKV Encoder Lib") touches
 * no hardware itself: libmpi_venc.so passes AKV_Encoder_Init() a table of 22
 * callbacks (registers of the core at 0x20020000 through /dev/uio0, DMA
 * memory, interrupt wait, mutexes). AKV_Encoder_Init is caught here, the
 * table is copied with the hardware entries wrapped, and every call is
 * written to a buffer in RAM.
 *
 *   TC100FIX_VENC_TRACE=/tmp/venc     files: /tmp/venc.trc (records),
 *                                     /tmp/venc.es (encoded frames)
 *   TC100FIX_VENC_TRACE_KB=2048       record buffer; when full, both files
 *                                     are written once and recording stops
 *   TC100FIX_VENC_TRACE_FRAMES=90     frames kept in venc.es (1 MB at most)
 * Recording stops at the first of: record buffer full, that many frames, or
 * 1 MB of frames. <base>.status says where it is: "recs=N frames=M state=S"
 * (S: 1 recording, 2 written), rewritten every 4096 records.
 *
 * venc.trc: a 16-byte header "TC100VTR" + version + record size, then
 * records of 16 bytes, little endian:
 *   u32 time (us since the first record), u16 type, u16 aux, u32 a, u32 b
 *   type 1 read   a = register address, b = value read
 *        2 write  a = register address, b = value written
 *        3 alloc  a = size, b = physical address (0: failed)
 *        4 free   a = physical address
 *        5 irq    wait for interrupt: aux 0 = start, 1 = end, a = argument
 *        6 reset  akuio_reset_video, a = argument
 *        7 frame  a = frame number in venc.es, b = its length; aux 1 = JPEG
 *        8 init   a = number of callbacks wrapped
 *        9 blob   a = physical address, b = length: the next ceil(b/16)
 *                 records are that DMA memory as it was. aux 0 = when its
 *                 address was written to the command-list register (0x8080),
 *                 aux 1 = after the interrupt that followed (the core writes
 *                 its status back into it)
 * venc.es: the frames one after the other (Annex B, JPEG frames too), so
 * the records can be matched with the stream the core produced.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define VT_NCB 22                      /* callbacks in the table (0x58 bytes) */
enum { VT_READ = 1, VT_WRITE, VT_ALLOC, VT_FREE, VT_IRQ, VT_RESET, VT_FRAME, VT_INIT, VT_BLOB };
#define VT_CMDLIST_REG 0x8080u            /* low 16 bits: command list address */
#define VT_BLOB_MAX 0x400u
#define VT_MAPS 64
static struct { uint32_t paddr, size; const unsigned char *vaddr; } maps[VT_MAPS];
static uint32_t last_cmd;

struct vt_rec { uint32_t t; uint16_t type, aux; uint32_t a, b; };

static void *real_cb[VT_NCB];
static struct vt_rec *recs;
static size_t n_recs, max_recs;
static int vt_state;                   /* 0 off, 1 recording, 2 written */
static uint64_t t0;
static pthread_mutex_t vt_lock = PTHREAD_MUTEX_INITIALIZER;
static unsigned char *es;
static size_t es_len, es_max;
static unsigned es_frames, es_max_frames;

static uint64_t vt_us(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000ULL + (uint64_t)ts.tv_nsec / 1000;
}

static void vt_write_files(void)
{
    const char *base = getenv("TC100FIX_VENC_TRACE");
    char path[200], tmp[220];
    FILE *f;
    if (!base || strlen(base) > 180) return;
    snprintf(path, sizeof(path), "%s.trc", base);
    snprintf(tmp, sizeof(tmp), "%s.tmp", path);
    if ((f = fopen(tmp, "wb"))) {
        uint32_t hdr[2] = { 1, sizeof(struct vt_rec) };
        fwrite("TC100VTR", 1, 8, f);
        fwrite(hdr, sizeof(hdr), 1, f);
        fwrite(recs, sizeof(struct vt_rec), n_recs, f);
        fclose(f);
        rename(tmp, path);
    }
    snprintf(path, sizeof(path), "%s.es", base);
    snprintf(tmp, sizeof(tmp), "%s.tmp", path);
    if (es && (f = fopen(tmp, "wb"))) {
        fwrite(es, 1, es_len, f);
        fclose(f);
        rename(tmp, path);
    }
    free(recs); recs = NULL;
    free(es); es = NULL;
}

static void vt_status(void)
{
    const char *base = getenv("TC100FIX_VENC_TRACE");
    char path[200];
    FILE *f;
    if (!base || strlen(base) > 180) return;
    snprintf(path, sizeof(path), "%s.status", base);
    if ((f = fopen(path, "w"))) {
        fprintf(f, "recs=%lu frames=%u es=%lu state=%d\n", (unsigned long)n_recs, es_frames, (unsigned long)es_len, vt_state);
        fclose(f);
    }
}

static void vt_add(uint16_t type, uint16_t aux, uint32_t a, uint32_t b)
{
    if (vt_state != 1) return;
    pthread_mutex_lock(&vt_lock);
    if (vt_state == 1) {
        uint64_t now = vt_us();
        if (!t0) t0 = now;
        recs[n_recs].t = (uint32_t)(now - t0);
        recs[n_recs].type = type; recs[n_recs].aux = aux;
        recs[n_recs].a = a; recs[n_recs].b = b;
        if (++n_recs == max_recs) { vt_state = 2; vt_write_files(); vt_status(); }
        else if (!(n_recs & 4095)) vt_status();
    }
    pthread_mutex_unlock(&vt_lock);
}

/* The wrapped callbacks: index in the table, then what it does. */
/* DMA memory at paddr copied into the records (lock held). */
static void vt_blob_locked(uint32_t paddr, uint16_t aux)
{
    int i;
    for (i = 0; i < VT_MAPS; i++) {
        if (maps[i].vaddr && paddr >= maps[i].paddr && paddr < maps[i].paddr + maps[i].size) {
            uint32_t len = maps[i].paddr + maps[i].size - paddr, nrec;
            if (len > VT_BLOB_MAX) len = VT_BLOB_MAX;
            nrec = (len + 15) / 16;
            if (n_recs + 1 + nrec >= max_recs) return;
            recs[n_recs].t = (uint32_t)(vt_us() - t0); recs[n_recs].type = VT_BLOB; recs[n_recs].aux = aux;
            recs[n_recs].a = paddr; recs[n_recs].b = len;
            n_recs++;
            memset(&recs[n_recs], 0, nrec * 16);
            memcpy(&recs[n_recs], maps[i].vaddr + (paddr - maps[i].paddr), len);
            n_recs += nrec;
            return;
        }
    }
}

static void vt_blob(uint32_t paddr, uint16_t aux)
{
    if (vt_state != 1) return;
    pthread_mutex_lock(&vt_lock);
    if (vt_state == 1) vt_blob_locked(paddr, aux);
    pthread_mutex_unlock(&vt_lock);
}

static uint32_t w_read(uint32_t reg)                      /* 3 */
{
    uint32_t v = (uint32_t)(uintptr_t)((uint32_t (*)(uint32_t))real_cb[3])(reg);
    vt_add(VT_READ, 0, reg, v);
    return v;
}
static void w_write(uint32_t reg, uint32_t val)           /* 4 */
{
    if ((reg & 0xffffu) == VT_CMDLIST_REG) { vt_blob(val, 0); last_cmd = val; }
    ((void (*)(uint32_t, uint32_t))real_cb[4])(reg, val);
    vt_add(VT_WRITE, 0, reg, val);
}
static void *w_alloc(uint32_t size, uint32_t arg)         /* 5: {vaddr, paddr, size, self} */
{
    uint32_t *d = ((uint32_t *(*)(uint32_t, uint32_t))real_cb[5])(size, arg);
    vt_add(VT_ALLOC, 0, size, d ? d[1] : 0);
    if (d && d[0]) {
        int i;
        pthread_mutex_lock(&vt_lock);
        for (i = 0; i < VT_MAPS; i++)
            if (!maps[i].vaddr) { maps[i].vaddr = (const unsigned char *)(uintptr_t)d[0]; maps[i].paddr = d[1]; maps[i].size = size; break; }
        pthread_mutex_unlock(&vt_lock);
    }
    return d;
}
static int w_free(uint32_t *d)                            /* 6 */
{
    vt_add(VT_FREE, 0, d ? d[1] : 0, 0);
    if (d) {
        int i;
        pthread_mutex_lock(&vt_lock);
        for (i = 0; i < VT_MAPS; i++)
            if (maps[i].vaddr && maps[i].paddr == d[1]) maps[i].vaddr = NULL;
        pthread_mutex_unlock(&vt_lock);
    }
    return ((int (*)(uint32_t *))real_cb[6])(d);
}
static void w_reset(uint32_t arg)                         /* 10 */
{
    vt_add(VT_RESET, 0, arg, 0);
    ((void (*)(uint32_t))real_cb[10])(arg);
}
static void w_irq(uint32_t arg)                           /* 19 */
{
    vt_add(VT_IRQ, 0, arg, 0);
    ((void (*)(uint32_t))real_cb[19])(arg);
    vt_add(VT_IRQ, 1, arg, 0);
    if (last_cmd) { vt_blob(last_cmd, 1); last_cmd = 0; }
}

/* Called by rec.c for every frame the encoder hands out. */
void tc100fix_venctrace_frame(const unsigned char *buf, unsigned int len, int jpeg)
{
    if (vt_state != 1 || !es) return;
    pthread_mutex_lock(&vt_lock);
    if (vt_state == 1 && es_len + len > es_max) {                /* frames full: write and stop */
        vt_state = 2; vt_write_files(); vt_status();
        pthread_mutex_unlock(&vt_lock);
        return;
    }
    if (vt_state == 1 && es_frames < es_max_frames) {
        memcpy(es + es_len, buf, len);
        es_len += len;
        pthread_mutex_unlock(&vt_lock);
        vt_add(VT_FRAME, (uint16_t)jpeg, es_frames++, len);
        if (es_frames >= es_max_frames) {                 /* enough: write and stop */
            pthread_mutex_lock(&vt_lock);
            if (vt_state == 1) { vt_state = 2; vt_write_files(); vt_status(); }
            pthread_mutex_unlock(&vt_lock);
        }
        return;
    }
    pthread_mutex_unlock(&vt_lock);
}

int AKV_Encoder_Init(void *table)
{
    static int (*real)(void *);
    const char *e = getenv("TC100FIX_VENC_TRACE");
    void *copy[VT_NCB];
    if (!real) real = (int (*)(void *))dlsym(RTLD_NEXT, "AKV_Encoder_Init");
    if (!real) return 0;
    if (!e || !e[0] || !table || vt_state) return real(table);
    {
        const char *kb = getenv("TC100FIX_VENC_TRACE_KB"), *fr = getenv("TC100FIX_VENC_TRACE_FRAMES");
        long k = kb ? atol(kb) : 2048, nf = fr ? atol(fr) : 90;
        if (k < 64 || k > 8192) k = 2048;
        if (nf < 1 || nf > 1000) nf = 90;
        max_recs = (size_t)k * 1024 / sizeof(struct vt_rec);
        es_max = 1024 * 1024; es_max_frames = (unsigned)nf;
    }
    if (!(recs = malloc(max_recs * sizeof(struct vt_rec)))) return real(table);
    es = malloc(es_max);
    memcpy(real_cb, table, sizeof(real_cb));
    memcpy(copy, table, sizeof(copy));
    copy[3] = (void *)w_read;  copy[4] = (void *)w_write;
    copy[5] = (void *)w_alloc; copy[6] = (void *)w_free;
    copy[10] = (void *)w_reset; copy[19] = (void *)w_irq;
    vt_state = 1;
    vt_add(VT_INIT, 0, 6, 0);
    vt_status();
    /* AKV_Encoder_Init copies the table, so a local copy is enough. */
    return real(copy);
}
