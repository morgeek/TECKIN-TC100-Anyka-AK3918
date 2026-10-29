/* isp_fps [FPS] : read or set the sensor frame rate with the ISP (Linux 6.6, /dev/isp_char,
 *   AK_ISP_GET_SENSOR_FPS / AK_ISP_SET_SENSOR_FPS). Without an argument it prints the current rate.
 * The sensor runs at 25 fps by default while tc100_rtsp keeps 10 to 15: every frame the ISP writes costs memory
 * bandwidth that the encoder and the CPU copies share. Running the sensor at the stream rate frees it.
 * Freestanding (no C library: raw ARM EABI system calls), so it runs on any user space of the camera.
 * Build: arm-linux-gnueabi-gcc -Os -nostdlib -static -fno-builtin -o isp_fps isp_fps.c */
#define AKISP_MAGIC 'I'
#define IOC(d, t, n, sz) (((unsigned)(d) << 30) | ((unsigned)(sz) << 16) | ((unsigned)(t) << 8) | (n))
#define AK_ISP_SET_SENSOR_FPS IOC(1, AKISP_MAGIC, 122, sizeof(int))	/* _IOW(.., 122, int) */
#define AK_ISP_GET_SENSOR_FPS IOC(2, AKISP_MAGIC, 123, sizeof(int))	/* _IOR(.., 123, int) */

static long sys3(long n, long a, long b, long c)
{
	register long r7 __asm__("r7") = n, r0 __asm__("r0") = a, r1 __asm__("r1") = b, r2 __asm__("r2") = c;

	__asm__ volatile ("svc 0" : "+r"(r0) : "r"(r7), "r"(r1), "r"(r2) : "memory");
	return r0;
}
#define SYS_write 4
#define SYS_open 5
#define SYS_ioctl 54

static int slen(const char *s) { int n = 0; while (s[n]) n++; return n; }
static void out(int fd, const char *s) { sys3(SYS_write, fd, (long)s, slen(s)); }
static int num(const char *s) { int n = 0; if (!*s) return -1; for (; *s; s++) { if (*s < '0' || *s > '9') return -1; n = n * 10 + *s - '0'; } return n; }

int run(int argc, char **argv)
{
	long fd, r;
	int fps;

	if (argc > 2 || (argc == 2 && ((fps = num(argv[1])) < 1 || fps > 30))) { out(2, "usage: isp_fps [FPS 1..30]\n"); return 2; }
	fd = sys3(SYS_open, (long)"/dev/isp_char", 2 /* O_RDWR */, 0);
	if (fd < 0) { out(2, "isp_fps: cannot open /dev/isp_char\n"); return 1; }
	if (argc == 2) {
		r = sys3(SYS_ioctl, fd, AK_ISP_SET_SENSOR_FPS, (long)&fps);
		if (r < 0) { out(2, "isp_fps: the ISP refused the rate (video not started?)\n"); return 1; }
	}
	r = sys3(SYS_ioctl, fd, AK_ISP_GET_SENSOR_FPS, (long)&fps);
	if (r < 0) { out(2, "isp_fps: cannot read the rate\n"); return 1; }
	{
		char b[8]; int l = 0;

		int t = 0;

		if (fps < 0 || fps > 99) fps = 0;
		while (fps >= 10) { fps -= 10; t++; }	/* no division: no libgcc */
		if (t) b[l++] = (char)('0' + t);
		b[l++] = (char)('0' + fps); b[l++] = '\n'; b[l] = 0;
		out(1, b);
	}
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
