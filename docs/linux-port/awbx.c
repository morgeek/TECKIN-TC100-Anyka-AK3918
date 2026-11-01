/* awbx: read / set the ISP's extra white balance gains (AK_ISP_GET/SET_AWB_EX), for tests. usage: awbx get | awbx set R B (256 = x1, applied on the tuning file's values) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
struct ctrl { int rmax, rmin, gmax, gmin, bmax, bmin, rex, bex; };
struct awb_ex { int en; struct ctrl c[10]; };
#define SET _IOW('I', 115, int)
#define GET _IOR('I', 116, int)
int main(int argc, char **argv)
{
	struct awb_ex a; int fd = open("/dev/isp_char", O_RDWR), i;
	if (fd < 0 || ioctl(fd, GET, &a) < 0) { perror("get"); return 1; }
	if (argc >= 4 && !strcmp(argv[1], "set")) {
		int r = atoi(argv[2]), b = atoi(argv[3]);
		static struct awb_ex base; static int have;
		if (!have) { base = a; have = 1; }
		for (i = 0; i < 10; i++) { a.c[i].rex = r; a.c[i].bex = b; }
		a.en = 1;
		if (ioctl(fd, SET, &a) < 0) { perror("set"); return 1; }
		if (ioctl(fd, GET, &a) < 0) { perror("get2"); return 1; }
	}
	printf("en %d\n", a.en);
	for (i = 0; i < 10; i++) printf("%d: r[%d..%d] g[%d..%d] b[%d..%d] rex %d bex %d\n", i, a.c[i].rmin, a.c[i].rmax, a.c[i].gmin, a.c[i].gmax, a.c[i].bmin, a.c[i].bmax, a.c[i].rex, a.c[i].bex);
	return 0;
}
