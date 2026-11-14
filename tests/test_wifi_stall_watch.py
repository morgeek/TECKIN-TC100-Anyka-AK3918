"""[wifi-counters] scripts/wifi-stall-watch.sh parses, and the counter names it reads are the ones the test-kernel
patches 0020 / 0021 / 0023 define (module_param_cb, 0444, .set = -EPERM)."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/wifi-stall-watch.sh'
SERIES = ROOT / 'patches/kernel-6.6/series'
RTL = 'tx_urb_free tx_urb_min txq_stops txq_wakes tx_urb_err tx_last_ms rx_urb_lost rx_urb_alive'.split()
RTL23 = 'ba_tx_start ba_tx_oper ba_tx_stop tx_qos_data tx_other'.split()     # patch 0023
HCD = 'bulk_out_nak bulk_in_nak bulk_out_oldest_ms bulk_in_oldest_ms'.split()


def patch(prefix):
    return next(SERIES.glob(prefix + '-*.patch')).read_text(encoding='utf-8')


def sh():
    return shutil.which('busybox') and ['busybox', 'sh'] or [shutil.which('sh') or 'sh']


class WifiStallWatch(unittest.TestCase):
    def test_lf_and_syntax(self):
        data = SCRIPT.read_bytes()
        self.assertNotIn(b'\r', data)
        self.assertTrue(data.startswith(b'#!/bin/sh\n'))
        r = subprocess.run(sh() + ['-n', str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_names_match_the_patches(self):
        src = SCRIPT.read_text()
        self.assertIn('RTL_NAMES="' + ' '.join(RTL + RTL23) + '"', src)
        self.assertIn('HCD_NAMES="' + ' '.join(HCD) + '"', src)
        p20, p21 = patch('0020'), patch('0021')
        for n in RTL:
            self.assertIn('RTL8XXXU_DBG_PARAM(%s,' % n, p20)
            self.assertIn('MODULE_PARM_DESC(%s,' % n, p20)
        p23 = patch('0023')
        for n in RTL23:
            self.assertIn('RTL8XXXU_DBG_PARAM(%s,' % n, p23)
            self.assertIn('MODULE_PARM_DESC(%s,' % n, p23)
            self.assertIn('atomic_inc(&rtl8xxxu_dbg_%s);' % n, p23)
        for n in HCD:
            self.assertRegex(p21, r'module_param_cb\(%s, ' % n)
        self.assertIn('module_param_cb(_name, &rtl8xxxu_dbg_ops_##_name, NULL, 0444)', p20)
        for n in HCD:
            self.assertIn('module_param_cb(%s, &akotg_dbg_ops_%s, NULL, 0444)' % (n, n), p21)
        # the HCD module is otg_hs (drivers/usb/host/anyka/Makefile)
        self.assertIn('/module/otg_hs/parameters', src)
        self.assertIn('otg-hs.o', patch('0003'))

    def test_set_ops_refuse(self):
        for pfx, fn in (('0020', 'rtl8xxxu_dbg_set'), ('0021', 'akotg_dbg_set')):
            p = patch(pfx)
            self.assertRegex(p, r'%s\(const char \*val, const struct kernel_param \*kp\)\n\+\{\n\+\treturn -EPERM;' % fn)

    def test_hcd_does_not_touch_the_urb_after_the_giveback(self):
        p = patch('0021')
        self.assertIn('dbg_bulk = usb_pipebulk(urb->pipe);', p)
        added = [l[1:] for l in p.splitlines() if l.startswith('+')]
        after = added[[i for i, l in enumerate(added) if 'if (dbg_bulk) {' in l][0]:]
        self.assertFalse([l for l in after[:6] if 'urb->' in l and 'urb_list' not in l])

    def test_ampdu_tx_switch(self):
        p = patch('0023')
        self.assertIn('+static bool rtl8xxxu_ampdu_tx = true;', p)
        self.assertIn('+module_param_named(ampdu_tx, rtl8xxxu_ampdu_tx, bool, 0644);', p)
        # the call site is gated, TX_START is not refused (mac80211 would restart the txq on every frame)
        self.assertIn('+\t\t\tif (rtl8xxxu_ampdu_tx &&\n+\t\t\t    !test_bit(tid, priv->tx_aggr_started) &&', p)
        self.assertEqual(p.count('rtl8xxxu_ampdu_tx'), 3)
        self.assertIn('reassociat', p.split('\n---\n')[0])

    def test_giveback_fix(self):
        p = patch('0022')
        self.assertIn('+\tpipetype = usb_pipetype(urb->pipe);', p)
        self.assertIn('-\tswitch(usb_pipetype(urb->pipe)) {', p)
        self.assertIn('+\tswitch (pipetype) {', p)
        self.assertIn('+\t\tif (!ep->period)\n+\t\t\tbreak;', p)

    def test_patch_headers(self):
        for pfx, path in (('0020', 'drivers/net/wireless/realtek/rtl8xxxu/rtl8xxxu_core.c'),
                          ('0021', 'drivers/usb/host/anyka/usb-hc.c'),
                          ('0022', 'drivers/usb/host/anyka/usb-hc.c'),
                          ('0023', 'drivers/net/wireless/realtek/rtl8xxxu/rtl8xxxu_core.c')):
            p = patch(pfx)
            self.assertIn('diff --git a/%s b/%s\n' % (path, path), p)
            self.assertNotIn('\r', p)

    def test_run_on_a_fake_tree(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            for d, names in (('module/rtl8xxxu/parameters', RTL[:7] + RTL23), ('module/otg_hs/parameters', HCD)):
                (t / 'sys' / d).mkdir(parents=True)
                for i, n in enumerate(names):
                    (t / 'sys' / d / n).write_text('%d\n' % (i + 1))
            st = t / 'sys/class/net/wlan0/statistics'
            st.mkdir(parents=True)
            (st / 'tx_packets').write_text('100\n')
            (st / 'rx_packets').write_text('50\n')
            (t / 'proc').mkdir()
            (t / 'proc/interrupts').write_text('  23:       1234   AK-INTC  usb\n  24:  5   AK-INTC  mmc0\n')
            env = {'WATCH_SYS': str(t / 'sys'), 'WATCH_PROC': str(t / 'proc'), 'PATH': '/usr/bin:/bin'}
            r = subprocess.run(sh() + [str(SCRIPT), '1'], capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            line = r.stdout.strip().splitlines()[-1]
            self.assertRegex(line, r'^\d\d:\d\d:\d\d tx/s=0 rx/s=0 irq/s=0 ')
            self.assertIn('tx_urb_free=1', line)
            self.assertIn('txq_wakes=4', line)
            self.assertNotIn('rx_urb_alive', line)       # missing file: skipped
            self.assertIn('ba_tx_start=8 ba_tx_oper=9 ba_tx_stop=10 tx_qos_data=11 tx_other=12', line)
            self.assertIn('bulk_out_oldest_ms=3 bulk_in_oldest_ms=4', line)


if __name__ == '__main__':
    unittest.main()
