/* isp_flip FLIP MIRROR : turn the picture with the ISP (Linux 6.6, /dev/isp_char, AK_ISP_SET_FLIP_MIRROR).
 *   FLIP   1 = upside down (vertical flip), 0 = normal
 *   MIRROR 1 = left-right mirror, 0 = normal
 * The hardware does it: no CPU cost per frame. Called by bin/setconf -k f (Settings -> Picture -> orientation).
 * Freestanding (no C library: raw ARM EABI system calls), so it runs on any user space of the camera.
 * Build: arm-linux-gnueabi-gcc -Os -nostdlib -static -fno-builtin -o isp_flip isp_flip.c */
#define AKISP_MAGIC 'I'
#define IOW(t, n, sz) ((1u << 30) | ((unsigned)(sz) << 16) | ((unsigned)(t) << 8) | (n))
#define AK_ISP_SET_FLIP_MIRROR IOW(AKISP_MAGIC, 121, sizeof(int))	/* as the driver defines it: _IOW(.., 121, int) */

struct isp_flip_mirror_info { int flip_en; int mirror_en; };

static long sys3(long n, long a, long b, long c)
{
	register long r7 __asm__("r7") = n, r0 __asm__("r0") = a, r1 __asm__("r1") = b, r2 __asm__("r2") = c;

	__asm__ volatile ("svc 0" : "+r"(r0) : "r"(r7), "r"(r1), "r"(r2) : "memory");
	return r0;
}
#define SYS_exit 1
#define SYS_write 4
#define SYS_open 5
#define SYS_ioctl 54

static int slen(const char *s) { int n = 0; while (s[n]) n++; return n; }
static void say(const char *s) { sys3(SYS_write, 2, (long)s, slen(s)); }

static int bit(const char *s) { return s && s[0] == '1' && !s[1] ? 1 : s && s[0] == '0' && !s[1] ? 0 : -1; }

int run(int argc, char **argv)
{
	struct isp_flip_mirror_info i;
	long fd, r;

	if (argc != 3 || (i.flip_en = bit(argv[1])) < 0 || (i.mirror_en = bit(argv[2])) < 0) {
		say("usage: isp_flip FLIP(0|1) MIRROR(0|1)\n");
		return 2;
	}
	fd = sys3(SYS_open, (long)"/dev/isp_char", 2 /* O_RDWR */, 0);
	if (fd < 0) { say("isp_flip: cannot open /dev/isp_char\n"); return 1; }
	r = sys3(SYS_ioctl, fd, AK_ISP_SET_FLIP_MIRROR, (long)&i);
	if (r < 0) { say("isp_flip: the ISP refused the flip (video not started?)\n"); return 1; }
	return 0;
}

/* entry point: argc at [sp], argv after it */
__attribute__((naked, noreturn)) void _start(void)
{
	__asm__ volatile (
		"ldr r0, [sp]\n"
		"add r1, sp, #4\n"
		"bl run\n"
		"mov r7, #1\n"
		"svc 0\n");
}
