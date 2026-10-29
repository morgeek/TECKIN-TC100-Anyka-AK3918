"""Hardware inventory (v3/install/inventory.sh) and board check (v3/install/hwcheck.sh) on fake /proc, /sys, /dev
trees: a stock TC100, a 3.0 one, and variants that must be refused. No camera needed.
Run: python3 -m unittest tests.test_hwinventory -v
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INV = ROOT / 'v3/install/inventory.sh'
HW = ROOT / 'v3/install/hwcheck.sh'
STOCK_MTD = '''dev:    size   erasesize  name
mtd0: 00800000 00001000 "spi0.0"
mtd1: 00200000 00001000 "KERNEL"
mtd2: 00001000 00001000 "MAC"
mtd3: 00001000 00001000 "ENV"
mtd4: 00180000 00001000 "A"
mtd5: 0007d000 00001000 "B"
mtd6: 003b6000 00001000 "C"
'''
V3_MTD = '''dev:    size   erasesize  name
mtd0: 00039000 00001000 "boot"
mtd1: 00200000 00001000 "kernel"
mtd2: 00001000 00001000 "mac"
mtd3: 00001000 00001000 "env"
mtd4: 00200000 00001000 "initrd"
mtd5: 002b3000 00001000 "stack"
mtd6: 00100000 00001000 "vendor"
mtd7: 00009000 00001000 "cfga"
mtd8: 00009000 00001000 "cfgb"
'''
ENV = b'\x12\x34\x56\x78' + b'bootcmd=run boot_normal\0ethaddr=00:11:22:33:44:55\0serverip=192.168.1.1\0bootdelay=1\0\0'


def tree(d, kernel, mtd, modules, usb=('0bda', 'f179'), jedec=None, partname=None, dmesg=None):
    d = Path(d)
    for p in ('proc/sys/kernel', 'sys/bus/usb/devices/usb1', 'sys/bus/usb/devices/1-1', 'dev', 'bin'):
        (d / p).mkdir(parents=True, exist_ok=True)
    (d / 'proc/sys/kernel/osrelease').write_text(kernel + '\n')
    (d / 'proc/mtd').write_text(mtd)
    (d / 'proc/cpuinfo').write_text('Processor\t: ARM926EJ-S rev 5 (v5l)\nHardware\t: CLOUD39EV3_AK3918EV300_MNBD\n')
    (d / 'proc/meminfo').write_text('MemTotal:          33384 kB\n')
    (d / 'proc/cmdline').write_text('console=ttySAK0,115200n8 mem=64M\n')
    (d / 'proc/modules').write_text(''.join(m + ' 1 0 - Live 0x0\n' for m in modules))
    (d / 'sys/bus/usb/devices/usb1/idVendor').write_text('1d6b\n')
    (d / 'sys/bus/usb/devices/usb1/bDeviceClass').write_text('09\n')
    (d / 'sys/bus/usb/devices/1-1/idVendor').write_text(usb[0] + '\n')
    (d / 'sys/bus/usb/devices/1-1/idProduct').write_text(usb[1] + '\n')
    if jedec or partname:
        n = d / 'sys/bus/spi/devices/spi0.0/spi-nor'
        n.mkdir(parents=True)
        if jedec:
            (n / 'jedec_id').write_text(jedec + '\n')
        if partname:
            (n / 'partname').write_text(partname + '\n')
    for i, line in enumerate(l for l in mtd.splitlines() if l.startswith('mtd')):
        size = int(line.split()[1], 16)
        name = line.split('"')[1].lower()
        data = ENV if name == 'env' else (b'U-Boot 2013.10.0-AK_V3.0.05 (Aug 10 2020)\0' if name in ('spi0.0', 'boot') else b'')
        (d / 'dev' / f'mtd{i}').write_bytes(data + b'\xff' * (min(size, 0x40000) - len(data)))
    # dmesg: a stand-in on the PATH (the 3.0 kernel logs the sensor id)
    (d / 'bin/dmesg').write_text('#!/bin/sh\n' + ''.join(f"echo '{l}'\n" for l in (dmesg or [])))
    os.chmod(d / 'bin/dmesg', 0o755)
    return d


def run_inventory(d, *args):
    env = dict(os.environ, PROC=str(d / 'proc'), SYS=str(d / 'sys'), DEV=str(d / 'dev'),
               PATH=str(d / 'bin') + ':' + os.environ['PATH'])
    r = subprocess.run(['sh', str(INV), *args], env=env, capture_output=True, text=True, timeout=60)
    return r.stdout


def kv(out):
    return dict(l.split('=', 1) for l in out.splitlines() if re.match(r'^[a-z0-9_]+=', l))


def hwcheck(inv_text, strict=False):
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as f:
        f.write(inv_text)
    env = dict(os.environ)
    if strict:
        env['HWCHECK_FLASH_ID'] = '1'
    r = subprocess.run(['sh', str(HW), f.name], env=env, capture_output=True, text=True, timeout=30)
    os.unlink(f.name)
    return r.returncode, r.stdout.strip()


class Inventory(unittest.TestCase):
    def test_stock_camera(self):
        with tempfile.TemporaryDirectory() as t:
            d = tree(t, '3.4.35', STOCK_MTD, ['8188fu', 'akcamera', 'sensor_f22+f23+f28+f35+f37_mipi'])
            out = run_inventory(d)
            k = kv(out)
            self.assertEqual(k['firmware'], 'stock')
            self.assertEqual(k['flash_size'], '8388608')
            self.assertEqual(k['wifi_usb'], '0bda:f179')
            self.assertEqual(k['wifi_driver'], '8188fu')
            self.assertEqual(k['sensor_module'], 'sensor_f22+f23+f28+f35+f37_mipi')
            self.assertEqual(k['ram_kb'], '33384')
            self.assertEqual(k['env_bootcmd'], 'run boot_normal')
            self.assertTrue(k['uboot_version'].startswith('U-Boot 2013.10.0'))
            self.assertRegex(k['uboot_md5'], r'^[0-9a-f]{32}$')
            # nothing personal: the MAC and the addresses of the U-Boot environment are hidden
            self.assertNotIn('00:11:22:33:44:55', out)
            self.assertNotIn('192.168.1.1', out)
            self.assertIn('ethaddr=<hidden>', out)
            self.assertEqual(hwcheck(out), (0, 'board=tc100-f23-rtl8188fu'))
            # the stock kernel does not name the flash chip: the flash install (strict) would refuse it
            self.assertEqual(hwcheck(out, strict=True)[0], 1)

    def test_v3_camera_quick(self):
        with tempfile.TemporaryDirectory() as t:
            d = tree(t, '6.6.58', V3_MTD, [], jedec='207017', partname='xm25qh64a',
                     dmesg=['ak39-vi 20000000.vi: sensor id 0xf23'])
            out = run_inventory(d, '--quick')
            k = kv(out)
            self.assertEqual(k['flash_size'], '8388608')
            self.assertEqual(k['sensor_id'], '0xf23')
            self.assertEqual(k['flash_jedec'], '207017')
            self.assertNotIn('uboot_md5', k)
            self.assertEqual(k['uboot_version'], 'unknown')	# --quick does not read U-Boot
            self.assertEqual(hwcheck(out, strict=True), (0, 'board=tc100-f23-rtl8188fu'))

    def test_unknown_variants_refused(self):
        base = 'sensor_id=0xf23\nwifi_usb=0bda:f179\nflash_size=8388608\nflash_jedec=207017\nflash_name=xm25qh64a\n'
        for change in ('sensor_id=0x2053', 'wifi_usb=0bda:8179', 'flash_size=16777216',
                       'flash_jedec=c84017\nflash_name=gd25q64'):
            text = base
            for line in change.split('\n'):
                key = line.split('=')[0]
                text = re.sub(rf'^{key}=.*$', line, text, flags=re.M)
            rc, msg = hwcheck(text, strict=True)
            self.assertEqual(rc, 1, change)
            self.assertTrue(msg.startswith('unknown:'), msg)
        self.assertEqual(hwcheck('wifi_usb=0bda:f179\nflash_size=8388608\n')[0], 1)	# sensor not identified

    def test_hooks_check_before_writing(self):
        hook = (ROOT / 'v3/install/stock-hook.sh').read_text()
        self.assertLess(hook.index('hwcheck.sh'), hook.index('envtool" set'))
        self.assertLess(hook.index('hwcheck.sh'), hook.index('of="$K/backup/flash-stock.bin"'))
        self.assertLess(hook.index('INVENTORY-ONLY'), hook.index('envtool" set'))
        inst = (ROOT / 'v3/install/install66.sh').read_text()
        self.assertIn('HWCHECK_FLASH_ID=1', inst.split('check() {')[1].split('\n}')[0])
        for f in (INV, HW):
            src = f.read_text()
            for w in ('flashcp', 'flash_erase ', 'flash_eraseall', 'fw_setenv', 'mtd_debug', 'envtool', 'of=/dev', 'of=$DEV', 'of=$B'):
                self.assertNotIn(w, src, (f.name, w))

    def test_board_profiles(self):
        for f in (ROOT / 'v3/board').glob('*.conf'):
            keys = dict(l.split('=', 1) for l in f.read_text().splitlines() if re.match(r'^[A-Z_]+=', l))
            for k in ('SENSOR_ID', 'STOCK_SENSOR_MODULE', 'WIFI_USB', 'FLASH_SIZE', 'ISP_CONF', 'IRCUT_DAY_GPIO',
                      'IRCUT_NIGHT_GPIO'):
                self.assertIn(k, keys, (f.name, k))


if __name__ == '__main__':
    unittest.main()
