#!/usr/bin/env python3
"""Flash budget of the TC100 (8 MiB SPI NOR, XM25QH64A) for the Linux 6.6 firmware.

Layout from the stock partition table (flash 0x37000, see docs/linux-port/flash-budget.md).
U-Boot, the table, MAC and ENV are never written.  The 6.6 image uses two regions:
  kernel: the KERNEL partition              0x039000, 0x200000 bytes
  rootfs: the A, B and C partitions merged   0x23b000 .. 0x7ee000
Usage: flash_budget.py [--kernel FILE] [--rootfs FILE] [--json]
Exit status 1 when a file does not fit (refusing is the point: the stock update path
has no size check and would overwrite the next partition)."""
import argparse, json, os, sys

FLASH = 0x800000
REGIONS = [  # name, offset, size, writable by us
    ('uboot+table', 0x000000, 0x039000, False),
    ('kernel',      0x039000, 0x200000, True),
    ('mac',         0x239000, 0x001000, False),
    ('env',         0x23a000, 0x001000, False),
    ('rootfs',      0x23b000, 0x7ee000 - 0x23b000, True),
    ('tail',        0x7ee000, FLASH - 0x7ee000, False),
]
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
    ap.add_argument('--kernel'); ap.add_argument('--rootfs'); ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    assert layout_ok(), 'region table does not cover the flash exactly'
    res = [check(n, p, UIMAGE_HDR if n == 'kernel' else 0) for n, p in (('kernel', a.kernel), ('rootfs', a.rootfs)) if p]
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        for r in res:
            print('%-7s %-24s %9d B -> %9d B in sectors / %9d B  free %9d  %s' % (
                r['region'], r['file'], r['bytes'], r['sectors_bytes'], r['capacity'], r['free'],
                'OK' if r['ok'] else 'DOES NOT FIT'))
        if not res:
            for n, off, size, w in REGIONS:
                print('%-12s 0x%06x %9d B %s' % (n, off, size, 'writable' if w else 'protected'))
    return 0 if all(r['ok'] for r in res) else 1

if __name__ == '__main__':
    sys.exit(main())
