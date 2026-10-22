/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
/*
 * User API of the Anyka AK3918EV300 video encoder window (/dev/uio0).
 *
 * The ioctl numbers of WAIT_IRQ (101) and SYSREG_WRITE (100) are those of
 * the vendor "akuio" driver, so a vendor-compatible libakuio keeps working;
 * the pool calls are new.
 */
#ifndef _UAPI_LINUX_AK39_VENC_H
#define _UAPI_LINUX_AK39_VENC_H

#include <linux/ioctl.h>
#include <linux/types.h>

/* mmap() offsets (bytes) */
#define AK39_VENC_MMAP_REGS	0x00000000UL	/* the register window */
#define AK39_VENC_MMAP_POOL	0x10000000UL	/* the DMA pool */

struct akuio_sysreg_write_t {
	__u32 paddr;	/* physical address of a SYSCTRL register */
	__u32 val;
	__u32 mask;
};

struct ak39_venc_pool_info {
	__u32 paddr;	/* physical address of the pool */
	__u32 size;	/* bytes */
	__u32 regs_paddr;	/* physical address of the register window */
	__u32 regs_size;
};

#define AKUIO_SYSREG_WRITE	_IOW('U', 100, struct akuio_sysreg_write_t)
#define AKUIO_WAIT_IRQ		_IOR('U', 101, int)
#define AKUIO_VIDEO_RESET	_IOR('U', 105, int)
#define AK39_VENC_POOL_INFO	_IOR('U', 110, struct ak39_venc_pool_info)

#endif
