"""Item 41: at restart / power-off (rcK -> "S39tc100 stop", before init's "umount -a -r") the recorder is stopped and
the card goes read-only, so the next boot does not find it "not properly unmounted"; a busy card is logged on it."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def stop_block():
    s = (ROOT / 'v3/S39tc100-linux66').read_text()
    m = re.search(r'^if \[ "\$1" = stop \]; then\n.*?^fi\n', s, re.M | re.S)
    assert m, 'no stop branch'
    return m.group(0)


class ShutdownClean(unittest.TestCase):
    def run_stop(self, remount_ok=True, mounted_rw=True):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / 'sd').mkdir()
            (t / 'mounts').write_text('/dev/mmcblk0p1 /mnt/sd vfat %s,noatime 0 0\n' % ('rw' if mounted_rw else 'ro'))
            code = stop_block().replace('/proc/mounts', str(t / 'mounts')).replace('/mnt/sd', str(t / 'sd'))
            code = code.replace(' %s ' % (t / 'sd'), ' /mnt/sd ')        # the pattern on the mounts line keeps /mnt/sd
            log = t / 'calls'
            stubs = ('killall() { echo "killall $*" >> %s; }\n' % log +
                     'pidof() { return 1; }\n'
                     'sync() { echo sync >> %s; }\n' % log +
                     'mount() { echo "mount $*" >> %s; return %d; }\n' % (log, 0 if remount_ok else 1) +
                     'fuser() { echo " 123 456"; }\n'
                     'sleep() { :; }\n')
            r = subprocess.run(SH + ['-c', stubs + 'set -- stop\n' + code + 'echo after'], capture_output=True, text=True)
            calls = log.read_text().splitlines() if log.exists() else []
            shut = t / 'sd/tc100-3/shutdown.log'
            return r, calls, shut.read_text() if shut.exists() else ''

    def test_recorder_stopped_then_card_read_only(self):
        r, calls, shut = self.run_stop()
        self.assertEqual(r.stdout, '')                                   # exit 0 in the branch: nothing after it
        self.assertEqual(calls[0], 'killall -TERM tc100_rtsp')
        self.assertLess(calls.index('sync'), calls.index('mount -o remount,ro %s' % calls[-1].split()[-1]))
        self.assertTrue(calls[-1].startswith('mount -o remount,ro '))
        self.assertEqual(shut, '')

    def test_busy_card_logged(self):
        r, calls, shut = self.run_stop(remount_ok=False)
        self.assertIn('card still busy at shutdown: 123 456', shut)

    def test_card_already_read_only_left_alone(self):
        r, calls, shut = self.run_stop(mounted_rw=False)
        self.assertFalse(any(c.startswith('mount') for c in calls))

    def test_fsck_in_the_user_space_and_auto_repair_wiring(self):
        d = (ROOT / 'v3/buildroot/configs/tc100_defconfig').read_text()
        self.assertIn('BR2_PACKAGE_DOSFSTOOLS_FSCK_FAT=y', d)
        prune = (ROOT / 'v3/initramfs-prune.txt').read_text().split('\n')
        self.assertIn('sbin/fsck.fat', prune)                           # not in the fixed-size initrd
        self.assertIn('for b in sbin/fsck.fat usr/sbin/fsck.fat; do', (ROOT / 'v3/build-stack.sh').read_text())
        self.assertIn('PATH="/mnt/ext/bin:$PATH"', (ROOT / 'scripts/sd-diag.sh').read_text())
        self.assertNotIn('dosfsck -a', (ROOT / 'scripts/rec-storage.sh').read_text())
        a = (ROOT / 'v3/autorun-linux66.sh').read_text()
        self.assertIn('on "$BC_SD_AUTO_REPAIR"', a)
        self.assertIn('( sleep 60; exec sh /mnt/scripts/sd-diag.sh repair )', a)
        self.assertIn('SD_AUTO_REPAIR=0', (ROOT / 'config/boot.conf.dist').read_text())

    def test_start_still_needs_start(self):
        s = (ROOT / 'v3/S39tc100-linux66').read_text()
        self.assertLess(s.index('if [ "$1" = stop ]; then'), s.index('[ "$1" = start ] || exit 0'))


if __name__ == '__main__':
    unittest.main()
