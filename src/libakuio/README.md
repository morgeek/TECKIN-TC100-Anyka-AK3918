# libakuio (free)

Replacement for the vendor `libakuio.so` (V3.1.01) on Linux 6.6. The vendor
media libraries (`libmpi_venc`, `libplat_vi`, `libplat_venc_cb`, `libmpi_osd`)
import 7 of its functions to get physically contiguous memory, the encoder
registers and its interrupt. The vendor library needs `/dev/ion`, a
patched UIO core and a pool at a hard-coded physical address (0x80000000);
none of that exists in mainline.

This one talks to the `ak39_venc` kernel driver (`/dev/uio0`, see
`drivers/misc/ak39_venc.c` in the 6.6 patches): a register window, an
interrupt wait, a clock/reset line and one DMA pool taken from a reserved
region of the device tree. The pool is sub-allocated here in 32-byte units.

- `make` builds `libakuio.so` for the camera (arm-linux-gnueabi toolchain).
- `make selftest` checks the allocator on the host.
- Install it as `/usr/lib/libakuio.so` (or `LD_PRELOAD`), no other change.
- `AKUIO_DEV=/path` overrides the device.

Status: allocator tested on the host; not yet run on the camera.
