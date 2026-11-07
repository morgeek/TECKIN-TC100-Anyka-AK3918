/* vencreset: soft reset of the encoder core (AKUIO_VIDEO_RESET: the SYSCTRL reset bit of the encoder) then the vendor's
 * initialisation of its registers, for a core left without interrupts by a test (2026-11-07). Stop tc100_rtsp first.
 * License: GPL-2.0-or-later */
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include "../libakuio/ak39_venc.h"

int main(void)
{
	struct ak39_venc_pool_info info;
	int fd = open("/dev/uio0", O_RDWR | O_SYNC);
	volatile uint32_t *r;

	if (fd < 0 || ioctl(fd, AK39_VENC_POOL_INFO, &info) < 0) { perror("/dev/uio0"); return 1; }
	r = mmap(NULL, info.regs_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, AK39_VENC_MMAP_REGS);
	if (r == MAP_FAILED) { perror("mmap"); return 1; }
	printf("before: 8014 %08x 8018 %08x 8020 %08x 8300 %08x\n", r[0x8014 / 4], r[0x8018 / 4], r[0x8020 / 4], r[0x8300 / 4]);
	if (ioctl(fd, AKUIO_VIDEO_RESET, 0) < 0) { perror("AKUIO_VIDEO_RESET"); return 1; }
	r[0x8010 / 4] = 0xffffffff; r[0x8018 / 4] = 0xffffff;
	(void)r[0x8020 / 4]; r[0x8020 / 4] = 1; r[0x822c / 4] = 0;
	(void)r[0x8020 / 4]; r[0x8020 / 4] = 0x10000;
	r[0x8034 / 4] = 0; r[0x8054 / 4] = 0x70;
	printf("after:  8014 %08x 8018 %08x 8020 %08x 8300 %08x\n", r[0x8014 / 4], r[0x8018 / 4], r[0x8020 / 4], r[0x8300 / 4]);
	return 0;
}
