"""Tests for automatic flash-safe step-by-step core PLL overclocking."""
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'v3/linux66-sd/overclock-step'
PATCH_0001 = ROOT / 'patches/kernel-6.6/series/0001-ARM-anyka-add-AK3918EV300-machine-interrupt-controll.patch'
AUTORUN = ROOT / 'v3/autorun-linux66.sh'
BOOTCONF_DIST = ROOT / 'config/boot.conf.dist'
SUPPORTBUNDLE = ROOT / 'www/cgi-bin/supportbundle.cgi'


@unittest.skipIf(os.name == 'nt', 'needs a POSIX shell')
class OverclockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = self.tmp / 'config'
        self.sys_pll = self.tmp / 'sys/core_pll'
        self.sys_asic = self.tmp / 'sys/asic_hz'
        self.sys_nr3d = self.tmp / 'sys/nr3d'
        self.sys_nr3d_ovf = self.tmp / 'sys/nr3d_overflow'
        self.proc = self.tmp / 'proc'
        self.logs = self.tmp / 'tmp_logs'
        self.sd_logs = self.tmp / 'sd_logs'
        self.trace = self.tmp / 'trace.log'
        self.dmesg_file = self.tmp / 'dmesg.txt'

        for d in (self.cfg, self.sys_pll.parent, self.proc, self.logs, self.sd_logs):
            d.mkdir(parents=True, exist_ok=True)

        self.bootconf = self.cfg / 'boot.conf'
        self.bootconf.write_text('OVERCLOCK_AUTO=1\nOVERCLOCK_HOLD_S=86400\nOVERCLOCK_MAX_MHZ=522\n')

        # Hardware defaults at boot are always 480 MHz / 120 MHz ASIC.
        self.sys_pll.write_text('0x010213f0\n')
        self.sys_asic.write_text('120000000\n')
        self.sys_nr3d.write_text('0\n')
        self.sys_nr3d_ovf.write_text('0\n')

        (self.proc / 'cpuinfo').write_text('Processor\t: ARM926EJ-S rev 5 (v5l)\nBogoMIPS\t: 239.20\n')
        (self.proc / 'uptime').write_text('120.50 110.00\n')
        (self.proc / 'loadavg').write_text('1.12 0.95 0.80 1/64 123\n')
        (self.proc / 'meminfo').write_text('MemTotal: 42000 kB\nMemAvailable: 16200 kB\nCmaFree: 4096 kB\n')
        (self.proc / 'stat').write_text('cpu  1000 0 500 8000 100 0 400 0 0 0\n')
        (self.proc / 'mounts').write_text('/dev/mmcblk0p1 /mnt/sd vfat rw,relatime 0 0\n')
        (self.proc / 'wireless').write_text(
            'Inter-| sta-|   Quality        |   Discarded packets\n'
            ' wlan0: 0000   70.  -48.  -95        0      0      0\n'
        )

        self.rtsp_stat = self.tmp / 'tc100_rtsp.stat'
        self.rtsp_stat.write_text('interval_s 5\ncaptured 125\nmain_bytes 300000\nsub_bytes 60000\nclients 2\ndropped 0\n')
        self.rtsp_log = self.tmp / 'tc100_rtsp.log'
        self.rtsp_log.write_text(
            'audio: echo cancellation active (NLMS)\n'
            'STAT 5s cap 125 enc_ms 14.2 snd_wait 0 clients 2 dropped 0\n'
        )
        self.wifi_qual = self.tmp / 'wifi-quality'
        self.wifi_qual.write_text('rssi=-48\n')
        self.last_reboot = self.tmp / 'last-reboot-reason'
        self.last_reboot.write_text('')
        self.safemode = self.tmp / 'safemode'
        self.dmesg_file.write_text('Booting Linux on physical CPU 0x0\n')
        intent_mock = self.tmp / 'intent_mock.sh'
        intent_mock.write_text(f'#!/bin/sh\nprintf "intent %s\\n" "$1" >> "{self.trace}"\n')
        intent_mock.chmod(0o755)

        self.env = os.environ.copy()
        self.env.update({
            'OC_CFG': str(self.cfg),
            'OC_STATE': str(self.cfg / 'overclock.state'),
            'OC_BOOTCONF': str(self.bootconf),
            'OC_LOG': str(self.cfg / 'log/overclock.log'),
            'OC_SAMPLE_LOG': str(self.logs / 'overclock-samples.log'),
            'OC_SD_SAMPLE_LOG': str(self.sd_logs / 'overclock-samples.log'),
            'OC_SYS_PLL': str(self.sys_pll),
            'OC_SYS_ASIC': str(self.sys_asic),
            'OC_SYS_NR3D': str(self.sys_nr3d),
            'OC_SYS_NR3D_OVF': str(self.sys_nr3d_ovf),
            'OC_CPUINFO': str(self.proc / 'cpuinfo'),
            'OC_UPTIME': str(self.proc / 'uptime'),
            'OC_LOADAVG': str(self.proc / 'loadavg'),
            'OC_MEMINFO': str(self.proc / 'meminfo'),
            'OC_PROC_STAT': str(self.proc / 'stat'),
            'OC_MOUNTS': str(self.proc / 'mounts'),
            'OC_WIRELESS': str(self.proc / 'wireless'),
            'OC_PAUSE': str(self.tmp / 'tc100rec.pause'),
            'OC_RTSP_STAT': str(self.rtsp_stat),
            'OC_RTSP_LOG': str(self.rtsp_log),
            'OC_WIFI_QUAL': str(self.wifi_qual),
            'OC_LAST_REBOOT': str(self.last_reboot),
            'OC_SAFEMODE': str(self.safemode),
            'OC_CPUSTAT': str(self.tmp / 'cpustat'),
            'OC_LAST_H6': str(self.tmp / 'last_h6'),
            'OC_PERSIST_CMD': f'printf "persist pll=%s\\n" "$(cat {self.sys_pll})" >> {self.trace}',
            'OC_INTENT_CMD': str(intent_mock),
            'OC_BOOTGUARD_CMD': f'printf "bootguard_clear\\n" >> {self.trace}',
            'OC_REBOOT_CMD': f'printf "reboot\\n" >> {self.trace}',
            'OC_DMESG_CMD': f'cat {self.dmesg_file}',
        })

    def _run(self, *args, check=True):
        res = subprocess.run(
            ['sh', str(SCRIPT), *args],
            env=self.env, capture_output=True, text=True, timeout=10,
        )
        if check and res.returncode != 0:
            self.fail(f'{args} failed ({res.returncode}):\nstdout={res.stdout}\nstderr={res.stderr}')
        return res

    def _simulate_kernel_boot(self):
        """Reset volatile runtime files as if kernel freshly booted at 480 MHz."""
        self.sys_pll.write_text('0x010213f0\n')
        self.sys_asic.write_text('120000000\n')
        (self.tmp / 'cpustat').unlink(missing_ok=True)
        (self.tmp / 'last_h6').unlink(missing_ok=True)
        self.trace.unlink(missing_ok=True)

    def _state(self):
        out = {}
        for line in (self.cfg / 'overclock.state').read_text().splitlines():
            if '=' in line:
                k, v = line.split('=', 1)
                out[k] = v
        return out

    def test_kernel_patch_0001_valid_hunks_and_runtime_pll_controls(self):
        stat_res = subprocess.run(
            ['git', 'apply', '--numstat', str(PATCH_0001)],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        self.assertIn('arch/arm/mach-anyka/anyka.c', stat_res.stdout)

        text = PATCH_0001.read_text()
        m = re.search(
            r'^--- /dev/null\n\+\+\+ b/arch/arm/mach-anyka/anyka\.c\n@@ -0,0 \+1,(\d+) @@\n(.*?)(?=^diff --git |\Z)',
            text, re.M | re.S,
        )
        self.assertIsNotNone(m)
        expected_lines = int(m.group(1))
        actual_plus = sum(1 for ln in m.group(2).splitlines() if ln.startswith('+'))
        self.assertEqual(actual_plus, expected_lines)

        self.assertIn('AK39_CORE_PLL_480\t0x010213f0', text)
        self.assertIn('anyka_apply_core_pll', text)
        self.assertIn('module_param_cb(core_pll, &ak_core_pll_ops, &ak_core_pll, 0644)', text)
        self.assertIn('module_param_named(asic_hz, ak_asic_hz, uint, 0444)', text)
        self.assertIn('pll_mhz < 400 || pll_mhz > 600', text)

    def test_autorun_bootconf_supportbundle_wiring(self):
        autorun = AUTORUN.read_text()
        i_bg = autorun.index('boot-guard start')
        i_oc = autorun.index('overclock-step boot')
        i_rtsp = autorun.index('tc100_rtsp')
        self.assertLess(i_bg, i_oc)
        self.assertLess(i_oc, i_rtsp)
        self.assertIn('overclock-step hk', autorun)

        bootconf = BOOTCONF_DIST.read_text()
        self.assertIn('OVERCLOCK_AUTO=1', bootconf)
        self.assertIn('OVERCLOCK_HOLD_S=86400', bootconf)
        self.assertIn('OVERCLOCK_MAX_MHZ=522', bootconf)

        sb = SUPPORTBUNDLE.read_text()
        for item in (
            'module/anyka/parameters/core_pll',
            'module/anyka/parameters/asic_hz',
            'overclock.state',
            'overclock.log',
            'overclock-samples.log',
        ):
            self.assertIn(item, sb)

    def test_first_boot_records_baseline_persists_before_pll_and_applies_510(self):
        self._run('boot')

        self.assertEqual(self.sys_pll.read_text().strip(), '0x010212aa')
        # Persistence MUST happen while core_pll is still at safe 480 MHz!
        self.assertEqual(self.trace.read_text().strip(), 'persist pll=0x010213f0')

        st = self._state()
        self.assertEqual(st['status'], 'testing')
        self.assertEqual(st['current_mhz'], '510')
        self.assertEqual(st['validated_mhz'], '480')
        self.assertEqual(st['armed'], '1')
        self.assertEqual(st['step_boots'], '1')
        self.assertEqual(st['bogomips_480'], '239.20')

        ev_log = (self.cfg / 'log/overclock.log').read_text()
        self.assertIn('INIT_BASELINE_480', ev_log)
        self.assertIn('APPLIED mhz=510', ev_log)
        self.assertIn('skew_ppm=0', ev_log)

    def test_hk_telemetry_sample_6h_summary_and_sd_pause_guard(self):
        self._run('boot')
        (self.proc / 'uptime').write_text('900.00 800.00\n')
        (self.proc / 'cpuinfo').write_text('BogoMIPS\t: 254.10\n')
        self._run('hk')

        sample_log = (self.logs / 'overclock-samples.log').read_text()
        self.assertIn('SAMPLE up_s=900 mhz=510 status=testing validated_mhz=480', sample_log)
        self.assertIn('pll_reg=0x010212aa', sample_log)
        self.assertIn('bogomips=254.10', sample_log)
        self.assertIn('cap_5s=125 dropped=0 enc_ms=14.2 snd_wait=0 clients=2', sample_log)
        self.assertIn('adc_hz=8000.75 dac_hz=8000.75 skew_ppm=0 av_drift_ms_min=+5.6', sample_log)
        self.assertIn('rssi=-48 oops=0 mmc_err=0 spi_err=0 i2c_err=0 usb_err=0', sample_log)

        # High-frequency SAMPLE lines go to tmp + SD, never wearing flash overclock.log.
        self.assertNotIn('SAMPLE ', (self.cfg / 'log/overclock.log').read_text())
        self.assertIn('SAMPLE up_s=900', (self.sd_logs / 'overclock-samples.log').read_text())

        # Pause SD writes while recording pause sentinel is active.
        (self.tmp / 'tc100rec.pause').write_text('rec\n')
        (self.proc / 'uptime').write_text('21600.00 20000.00\n')
        self._run('hk')

        self.assertIn('SUMMARY_6H h=6 up_s=21600 mhz=510', (self.cfg / 'log/overclock.log').read_text())
        self.assertNotIn('up_s=21600', (self.sd_logs / 'overclock-samples.log').read_text())

    def test_24h_promotion_ladder_510_to_516_to_522_to_locked(self):
        # Stage 1: 510 MHz
        self._run('boot')
        (self.proc / 'uptime').write_text('86400.50 80000.00\n')
        self.trace.unlink(missing_ok=True)
        self._run('hk')

        st = self._state()
        self.assertEqual(st['validated_mhz'], '510')
        self.assertEqual(st['current_mhz'], '516')
        self.assertEqual(st['status'], 'testing')
        self.assertEqual(st['armed'], '1')
        self.assertEqual(st['step_boots'], '0')
        self.assertEqual(
            self.trace.read_text().splitlines(),
            [
                'bootguard_clear',
                'intent overclock-step: 24h validated at 510MHz, promoting to 516MHz',
                'persist pll=0x010212aa',
                'reboot',
            ],
        )

        # Stage 2: clean promoted boot to 516 MHz
        self._simulate_kernel_boot()
        self.last_reboot.write_text(
            'requested at 2026-11-15 10:00:00 (overclock-step: 24h validated at 510MHz, promoting to 516MHz)\n'
        )
        self._run('boot')
        self.assertEqual(self.sys_pll.read_text().strip(), '0x010212ac')
        self.assertEqual(self._state()['step_boots'], '1')

        (self.proc / 'uptime').write_text('86401.00 80000.00\n')
        self._run('hk')
        st = self._state()
        self.assertEqual(st['validated_mhz'], '516')
        self.assertEqual(st['current_mhz'], '522')

        # Stage 3: clean promoted boot to 522 MHz -> validates after 24h and locks permanently
        self._simulate_kernel_boot()
        self.last_reboot.write_text(
            'requested at 2026-11-16 10:00:00 (overclock-step: 24h validated at 516MHz, promoting to 522MHz)\n'
        )
        self._run('boot')
        self.assertEqual(self.sys_pll.read_text().strip(), '0x010212ae')

        (self.proc / 'uptime').write_text('86405.00 80000.00\n')
        self.trace.unlink(missing_ok=True)
        self._run('hk')

        st = self._state()
        self.assertEqual(st['validated_mhz'], '522')
        self.assertEqual(st['current_mhz'], '522')
        self.assertEqual(st['status'], 'locked')
        self.assertEqual(st['armed'], '0')
        # Locking at max keeps running cleanly with no unnecessary reboot.
        self.assertEqual(self.trace.read_text().splitlines(), ['persist pll=0x010212ae'])

        # Subsequent reboot stays locked on 522 MHz.
        self._simulate_kernel_boot()
        self._run('boot')
        self.assertEqual(self.sys_pll.read_text().strip(), '0x010212ae')

    def test_unexpected_and_unknown_reboot_rollback(self):
        # Crash at first step (510 MHz) locks onto 480 MHz baseline.
        self._run('boot')
        self._simulate_kernel_boot()
        self.last_reboot.write_text('UNEXPECTED (last alive 2026-11-14 12:00:00)\n')
        self._run('boot')

        self.assertEqual(self.sys_pll.read_text().strip(), '0x010213f0')
        st = self._state()
        self.assertEqual(st['status'], 'locked')
        self.assertEqual(st['current_mhz'], '480')
        self.assertEqual(st['validated_mhz'], '480')
        self.assertEqual(st['failed_mhz'], '510')
        self.assertIn('unexpected_reboot:', st['failed_reason'])

        # Reset and test fast panic (<300s / no SD -> "unknown") at 516 MHz after 510 passed.
        self._run('reset')
        self._simulate_kernel_boot()
        self._run('boot')
        (self.proc / 'uptime').write_text('86400.00 80000.00\n')
        self._run('hk')
        self._simulate_kernel_boot()
        self.last_reboot.write_text(
            'requested at 2026-11-15 00:00:00 (overclock-step: 24h validated at 510MHz, promoting to 516MHz)\n'
        )
        self._run('boot')
        self.assertEqual(self.sys_pll.read_text().strip(), '0x010212ac')

        # Fast panic before first heartbeat -> reboot-tracker reports "unknown (no heartbeat recorded yet)".
        self._simulate_kernel_boot()
        self.last_reboot.write_text('unknown (no heartbeat recorded yet)\n')
        self._run('boot')

        self.assertEqual(self.sys_pll.read_text().strip(), '0x010212aa')
        st = self._state()
        self.assertEqual(st['status'], 'locked')
        self.assertEqual(st['current_mhz'], '510')
        self.assertEqual(st['validated_mhz'], '510')
        self.assertEqual(st['failed_mhz'], '516')

    def test_clean_user_reboot_resumes_testing(self):
        self._run('boot')
        self._simulate_kernel_boot()
        self.last_reboot.write_text('requested at 2026-11-14 02:00:00 (user via reboot)\n')
        self._run('boot')

        st = self._state()
        self.assertEqual(st['status'], 'testing')
        self.assertEqual(st['current_mhz'], '510')
        self.assertEqual(st['step_boots'], '2')
        self.assertEqual(self.sys_pll.read_text().strip(), '0x010212aa')
        self.assertIn('USER_REBOOT_RESUME', (self.cfg / 'log/overclock.log').read_text())

    def test_health_rollback_on_spi_timeout_and_oops(self):
        self._run('boot')
        self.dmesg_file.write_text('[ 120.000000] ak39-spi: transfer timeout on mtd1\n')
        self.trace.unlink(missing_ok=True)
        self._run('hk')

        st = self._state()
        self.assertEqual(st['status'], 'locked')
        self.assertEqual(st['current_mhz'], '480')
        self.assertEqual(st['failed_mhz'], '510')
        self.assertIn('spi_err=1', st['failed_reason'])
        self.assertEqual(
            self.trace.read_text().splitlines(),
            [
                'bootguard_clear',
                'intent overclock-step: health rollback from 510MHz to 480MHz',
                'persist pll=0x010212aa',
                'reboot',
            ],
        )

        # Kernel Oops during second test campaign rolls back similarly.
        self._run('reset')
        self.dmesg_file.write_text('clean\n')
        self._simulate_kernel_boot()
        self._run('boot')
        self.dmesg_file.write_text('Internal error: Oops: 817 [#1] ARM\n')
        self._run('hk')
        st = self._state()
        self.assertEqual(st['status'], 'locked')
        self.assertIn('oops=1', st['failed_reason'])

    def test_safemode_disable_sysfs_reject_and_status_reset(self):
        # Safe mode triggers rollback when armed.
        self._run('boot')
        self._simulate_kernel_boot()
        self.safemode.write_text('boot-guard\n')
        self._run('boot')
        self.assertEqual(self.sys_pll.read_text().strip(), '0x010213f0')
        st = self._state()
        self.assertEqual(st['status'], 'locked')
        self.assertEqual(st['failed_reason'], 'safemode_triggered')

        # Status output and OVERCLOCK_AUTO=0 disable switch.
        self.safemode.unlink()
        st_out = self._run('status').stdout
        self.assertIn('status=locked', st_out)
        self.bootconf.write_text('OVERCLOCK_AUTO=0\n')
        self._simulate_kernel_boot()
        self._run('boot')
        self.assertEqual(self.sys_pll.read_text().strip(), '0x010213f0')
        self.assertEqual(self._state()['status'], 'disabled')

        # Re-enabling starts cleanly, and sysfs rejection rolls back safely.
        self.bootconf.write_text('OVERCLOCK_AUTO=1\n')
        try:
            self._simulate_kernel_boot()
            os.chmod(self.sys_pll, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            res = self._run('boot', check=False)
            self.assertEqual(res.returncode, 1)
            st = self._state()
            self.assertEqual(st['status'], 'locked')
            self.assertEqual(st['current_mhz'], '480')
            self.assertEqual(st['failed_mhz'], '510')
            self.assertEqual(st['failed_reason'], 'sysfs_write_rejected')
        finally:
            os.chmod(self.sys_pll, 0o644)

        self._run('reset')
        self.assertEqual(self._state()['status'], 'init')

    def test_kernel_patch_reprograms_adc2_div_on_live_pll_change(self):
        patch = PATCH_0001.read_text()
        self.assertIn('if (readl(sys + 0x10) & BIT(8))', patch)
        self.assertIn('DIV_ROUND_CLOSEST(pll_mhz * 1000u, 2048u) - 1u', patch)
        self.assertIn('| adc_div | BIT(9), sys + 0x10', patch)

    def test_live_set_json_and_manual_rollback(self):
        # Switch manually on the fly: 480 -> 510 -> 516 -> 522 -> off (480) -> auto 516.
        self._run('set', 'manual', '510', '522')
        self.assertEqual(self.sys_pll.read_text().strip(), '0x010212aa')
        self.assertIn('OVERCLOCK_AUTO=0', self.bootconf.read_text())
        self.assertIn('OVERCLOCK_TARGET_MHZ=510', self.bootconf.read_text())
        d = json.loads(self._run('json').stdout)
        self.assertTrue(d['ok'])
        self.assertEqual(d['mode'], 'manual')
        self.assertEqual(d['target_mhz'], 510)
        self.assertEqual(d['current_mhz'], 510)
        self.assertEqual(d['live_mhz'], 510)
        self.assertEqual(d['pll_reg'], '0x010212aa')

        self._run('set', 'manual', '516', '522')
        self.assertEqual(self.sys_pll.read_text().strip(), '0x010212ac')
        d = json.loads(self._run('json').stdout)
        self.assertEqual(d['live_mhz'], 516)

        self._run('set', 'manual', '522', '522')
        self.assertEqual(self.sys_pll.read_text().strip(), '0x010212ae')
        self.assertIn('LIVE_SET mode=manual mhz=522', (self.cfg / 'log/overclock.log').read_text())

        # Unexpected reboot in manual 522 MHz rolls back to 480 MHz and resets OVERCLOCK_TARGET_MHZ.
        self._simulate_kernel_boot()
        self.last_reboot.write_text('UNEXPECTED (test crash at 522)\n')
        self._run('boot')
        self.assertEqual(self.sys_pll.read_text().strip(), '0x010213f0')
        st = self._state()
        self.assertEqual(st['status'], 'locked')
        self.assertEqual(st['current_mhz'], '480')
        self.assertEqual(st['failed_mhz'], '522')
        self.assertIn('OVERCLOCK_TARGET_MHZ=480', self.bootconf.read_text())

        # Switching to off keeps 480 MHz and clears mode=off.
        self._run('set', 'off')
        self.assertEqual(self.sys_pll.read_text().strip(), '0x010213f0')
        d = json.loads(self._run('json').stdout)
        self.assertEqual(d['mode'], 'off')
        self.assertEqual(d['status'], 'disabled')

        # Switching back to auto with max=516 starts testing at 510 MHz immediately live.
        self._run('set', 'auto', '510', '516')
        self.assertEqual(self.sys_pll.read_text().strip(), '0x010212aa')
        d = json.loads(self._run('json').stdout)
        self.assertEqual(d['mode'], 'auto')
        self.assertEqual(d['max_mhz'], 516)
        self.assertEqual(d['current_mhz'], 510)

        # Sysfs rejection during live set rolls back cleanly.
        try:
            os.chmod(self.sys_pll, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            res = self._run('set', 'manual', '522', '522', check=False)
            self.assertEqual(res.returncode, 1)
            d = json.loads(self._run('json').stdout)
            self.assertEqual(d['status'], 'locked')
            self.assertEqual(d['failed_reason'], 'sysfs_write_rejected')
            self.assertEqual(d['failed_mhz'], 522)
            self.assertIn('OVERCLOCK_TARGET_MHZ=480', self.bootconf.read_text())
        finally:
            os.chmod(self.sys_pll, 0o644)

    def test_web_ui_and_cgi_wiring(self):
        action = (ROOT / 'www/cgi-bin/action.cgi').read_text()
        system_sh = (ROOT / 'scripts/action.d/system.sh').read_text()
        settings = (ROOT / 'www/settings.html').read_text()
        self.assertIn('overclock_info', action)
        self.assertIn('set_overclock', action)
        self.assertIn('overclock_reset', action)
        self.assertIn('overclock_info)', system_sh)
        self.assertIn('set_overclock)', system_sh)
        self.assertIn('overclock_reset)', system_sh)
        for elem in ('oc_summary', 'oc_mode', 'oc_mhz', 'oc_max_mhz', 'btnOcApply', 'btnOcReset'):
            self.assertIn(f'id="{elem}"', settings)


if __name__ == '__main__':
    unittest.main()
