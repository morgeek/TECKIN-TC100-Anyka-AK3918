#!/usr/bin/env python3
"""Flash budget of the TC100 (8 MiB SPI NOR, XM25QH64A) for the 3.0 firmware (Linux 6.6).

The partitions are those of the device tree (patches/kernel-6.6/series/0010-spi-*.patch; tests/test_flash_budget.py
checks that both agree). boot (U-Boot and the table), mac and env are never written.
  kernel  0x039000, 2 MiB       uImage (oipc.img)
  initrd  0x23b000, 2 MiB       initramfs; U-Boot loads INITRD_SIZE bytes of it (v3/build-rootfs66.sh)
  stack   0x43b000, 0x2b3000    squashfs of the free user space (v3/build-stack.sh, STACK_MAX)
  vendor  0x6ee000, 1 MiB       squashfs of the camera's sensor tuning (isp.conf, ~12 KB; made at install)
  cfga / cfgb                   settings, two slots of 36 KiB
Usage: flash_budget.py [--kernel FILE] [--initrd FILE] [--stack FILE] [--vendor FILE] [--json]
Exit status 1 when a file does not fit (refusing is the point: a file larger than its partition would overwrite the
next one)."""
import argparse, json, os, sys

FLASH = 0x800000
REGIONS = [  # name, offset, size, writable by us
    ('boot',   0x000000, 0x039000, False),
    ('kernel', 0x039000, 0x200000, True),
    ('mac',    0x239000, 0x001000, False),
    ('env',    0x23a000, 0x001000, False),
    ('initrd', 0x23b000, 0x200000, True),
    ('stack',  0x43b000, 0x2b3000, True),
    ('vendor', 0x6ee000, 0x100000, True),
    ('cfga',   0x7ee000, 0x009000, True),
    ('cfgb',   0x7f7000, 0x009000, True),
]
FILES = ('kernel', 'initrd', 'stack', 'vendor')
UIMAGE_HDR = 64  # mkimage header added in front of the zImage
ERASE = 0x1000  # sector size: sizes are rounded up to it


def layout_ok():
    end = 0
    for name, off, size, _ in REGIONS:
        if off != end:
            return False
        end = off + size
    return end == FLASH


def check(region, path, reserve=0):
    r = next(x for x in REGIONS if x[0] == region)
    size = os.path.getsize(path)
    used = -(-(size + reserve) // ERASE) * ERASE
    return {'region': region, 'file': os.path.basename(path), 'bytes': size, 'sectors_bytes': used,
            'capacity': r[2], 'free': r[2] - used, 'ok': used <= r[2]}


def main():
    ap = argparse.ArgumentParser()
    for n in FILES:
        ap.add_argument('--' + n)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    assert layout_ok(), 'region table does not cover the flash exactly'
    res = [check(n, getattr(a, n), UIMAGE_HDR if n == 'kernel' else 0) for n in FILES if getattr(a, n)]
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        for r in res:
            print('%-7s %-24s %9d B -> %9d B in sectors / %9d B  free %9d  %s' % (
                r['region'], r['file'], r['bytes'], r['sectors_bytes'], r['capacity'], r['free'],
                'OK' if r['ok'] else 'DOES NOT FIT'))
        if not res:
            for n, off, size, w in REGIONS:
                print('%-7s 0x%06x %9d B %s' % (n, off, size, 'writable' if w else 'protected'))
    return 0 if all(r['ok'] for r in res) else 1


if __name__ == '__main__':
    sys.exit(main())
