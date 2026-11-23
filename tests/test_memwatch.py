"""Host tests of scripts/memwatch.sh (memory.csv / memory-hourly.csv) on a fake /proc.
Run: python3 -m unittest tests/test_memwatch.py
"""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['/bin/sh']
MW = str(ROOT / 'scripts/memwatch.sh')

MEMINFO = """MemTotal:          59000 kB
MemFree:            3000 kB
MemAvailable:      20000 kB
Buffers:             100 kB
Cached:            15000 kB
Active(anon):       4000 kB
Inactive(anon):      500 kB
Active(file):       8000 kB
Inactive(file):     7000 kB
Unevictable:           0 kB
Shmem:               900 kB
SReclaimable:       2500 kB
SUnreclaim:         3300 kB
KernelStack:         200 kB
PageTables:          150 kB
Percpu:               40 kB
VmallocUsed:           0 kB
CmaFree:            9000 kB
AnonPages:          4400 kB
"""
VMSTAT = "nr_free_pages 750\nnr_free_cma 2250\ncompact_stall 3\ncompact_fail 1\n"


class MemWatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.t = t
        self.proc = t / 'proc'
        (self.proc / 'net').mkdir(parents=True)
        (self.proc / 'sys/vm').mkdir(parents=True)
        (self.proc / 'meminfo').write_text(MEMINFO)
        (self.proc / 'vmstat').write_text(VMSTAT)
        (self.proc / 'stat').write_text('cpu 1 2 3\nbtime 1700000000\n')
        self.uptime(700)
        (self.proc / 'loadavg').write_text('0.10 0.20 0.30 1/57 1234\n')
        (self.proc / 'mounts').write_text('rootfs / rootfs rw 0 0\n')
        (self.proc / 'net/sockstat').write_text('sockets: used 40\nTCP: inuse 5 orphan 1 tw 7 alloc 9 mem 3\nUDP: inuse 2 mem 0\n')
        (self.proc / 'buddyinfo').write_text('Node 0, zone   Normal    10     5     2     1     0\n')
        sysd = t / 'sys/module/rtl8xxxu/parameters'
        sysd.mkdir(parents=True)
        (sysd / 'rx_urb_alive').write_text('32\n')
        (sysd / 'tx_urb_free').write_text('62\n')
        bindir = t / 'bin'
        bindir.mkdir()
        df = bindir / 'df'
        df.write_text('#!/bin/sh\necho "Filesystem 1K-blocks Used Available Use% Mounted on"\n'
                      'echo "tmpfs 100 11 89 11% /tmp"\necho "ubi 100 22 78 22% /mnt"\necho "tmpfs 100 33 67 33% /var"\n',
                      newline='\n')
        df.chmod(df.stat().st_mode | stat.S_IEXEC)
        (t / 'boot.conf').write_text('MEMWATCH=1\nMEMWATCH_DROP_HOUR=\n')
        self.out = t / 'out'
        self.env = dict(os.environ, MEMWATCH_PROC=str(self.proc), MEMWATCH_SYS=str(t / 'sys'),
                        MEMWATCH_CONF=str(t / 'boot.conf'), MEMWATCH_PENDING=str(t / 'pend/memwatch.pending'),
                        MEMWATCH_STATE=str(t / 'state'), MEMWATCH_DIR=str(self.out), MEMWATCH_HISTORY=str(t / 'hist'),
                        MEMWATCH_DROP_WAIT='0', MEMWATCH_DF=str(df))
        (t / 'hist').mkdir()
        (t / 'hist/rtsp-h26x').write_text('4\n')

    def tearDown(self):
        self.tmp.cleanup()

    def uptime(self, s):
        (self.proc / 'uptime').write_text('%d.50 100.00\n' % s)

    def run_mw(self, mode='sample', **env):
        e = dict(self.env)
        e.update(env)
        r = subprocess.run(SH + [MW, mode], capture_output=True, text=True, timeout=60, env=e)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def rows(self, name='memory.csv'):
        p = self.out / name
        return [l.split(',') for l in p.read_text().splitlines()] if p.exists() else []

    def test_row_columns_and_flush_on_boot_kind(self):
        self.run_mw()                       # uptime 700 >= 600: the boot baseline, flushed at once
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        h = dict(zip(rows[0], rows[1]))
        self.assertEqual(len(rows[0]), 26)
        self.assertEqual(len(rows[1]), 26)
        self.assertEqual(h['kind'], 'boot')
        self.assertEqual(h['timestamp'], str(1700000000 + 700))
        self.assertEqual(h['MemAvailable'], '20000')
        self.assertEqual(h['Active_file'], '8000')
        self.assertEqual(h['SUnreclaim'], '3300')
        self.assertEqual(h['CmaFree'], '9000')
        self.assertEqual(h['nr_free_cma'], '2250')
        self.assertEqual(h['compact_fail'], '1')
        self.assertEqual(h['cma_alloc_success'], '')      # absent in the fake vmstat: empty, not an error

    def test_missing_fields_are_empty_and_sample_rows_wait_for_the_flush(self):
        (self.proc / 'meminfo').write_text('MemTotal: 59000 kB\nMemAvailable: 1 kB\n')
        (self.proc / 'vmstat').unlink()
        self.uptime(100)                    # before boot + 10 min: a plain sample, only pending
        self.run_mw()
        self.assertEqual(self.rows(), [])
        self.assertEqual(len((self.t / 'pend/memwatch.pending').read_text().splitlines()), 1)
        self.run_mw('flush')
        rows = self.rows()
        h = dict(zip(rows[0], rows[1]))
        self.assertEqual((h['kind'], h['MemAvailable'], h['SUnreclaim'], h['nr_free_pages']), ('sample', '1', '', ''))
        self.assertEqual(len(rows[1]), 26)
        self.assertEqual((self.t / 'pend/memwatch.pending').read_text(), '')

    def test_boot_once_then_hourly_with_extras(self):
        self.run_mw()                       # boot at 700 s
        self.uptime(1000)
        self.run_mw()                       # sample
        self.uptime(700 + 3600)
        self.run_mw()                       # hourly
        kinds = [r[2] for r in self.rows()[1:]]
        self.assertEqual(kinds, ['boot', 'sample', 'hourly'])
        hr = self.rows('memory-hourly.csv')
        self.assertEqual(len(hr), 2)
        h = dict(zip(hr[0], hr[1]))
        self.assertEqual((h['tcp_inuse'], h['tcp_orphan'], h['tcp_tw'], h['tcp_mem']), ('5', '1', '7', '3'))
        self.assertEqual((h['tmp_used_kb'], h['mnt_used_kb'], h['var_used_kb']), ('11', '22', '33'))
        self.assertEqual((h['threads'], h['rx_urb_alive'], h['tx_urb_free'], h['rtsp_restarts']), ('57', '32', '62', '4'))
        self.assertEqual(h['buddyinfo'], 'Normal:10/5/2/1/0')
        self.assertEqual(len(hr[0]), len(hr[1]))

    def test_open_deleted_files_counted(self):
        fd = self.proc / '12/fd'
        fd.mkdir(parents=True)
        try:
            os.symlink('/tmp/x (deleted)', fd / '3')
            os.symlink('/tmp/y', fd / '4')
        except OSError:
            self.skipTest('no symlinks')
        self.run_mw()
        self.uptime(700 + 3600)
        self.run_mw()
        hr = self.rows('memory-hourly.csv')
        self.assertEqual(dict(zip(hr[0], hr[1]))['open_deleted'], '1')

    def test_cap(self):
        self.out.mkdir()
        self.run_mw()
        (self.t / 'state').write_text('1 0 \n')
        for i in range(60):
            self.uptime(700 + (i * 300) % 3000)     # always under an hour from the mark: only samples
            self.run_mw(MEMWATCH_MAX_ROWS='24')
            self.run_mw('flush', MEMWATCH_MAX_ROWS='24')
        n = len(self.rows())
        self.assertLessEqual(n, 24 + 25 + 1)
        self.assertEqual(self.rows()[0][0], 'timestamp')   # header kept after a trim
        self.assertGreater(n, 24)

    def test_row_size_estimate_stays_small(self):
        self.run_mw()
        line = (self.out / 'memory.csv').read_text().splitlines()[1]
        self.assertLess(len(line), 170)            # 1008 rows x 170 bytes = 171 KB at the very most

    def test_switch_off_writes_nothing(self):
        (self.t / 'boot.conf').write_text('MEMWATCH=0\n')
        self.run_mw()
        self.run_mw('flush')
        self.assertFalse(self.out.exists())
        self.assertFalse((self.t / 'pend').exists())

    def test_default_on_without_conf_key(self):
        (self.t / 'boot.conf').write_text('OTHER=1\n')
        self.run_mw()
        self.assertEqual(len(self.rows()), 2)

    def drop_rows(self):
        return [r for r in self.rows()[1:] if r[2] == 'drop']

    def test_drop_off_by_default(self):
        self.run_mw(MEMWATCH_HOUR_DAY='04 100')
        self.assertEqual(self.drop_rows(), [])

    def test_drop_hour_pair_once_a_day(self):
        (self.t / 'boot.conf').write_text('MEMWATCH_DROP_HOUR=4\n')
        self.run_mw(MEMWATCH_HOUR_DAY='03 100')
        self.assertEqual(self.drop_rows(), [])
        self.run_mw(MEMWATCH_HOUR_DAY='04 100')
        self.assertEqual(len(self.drop_rows()), 2)
        self.run_mw(MEMWATCH_HOUR_DAY='04 100')       # same day: not again
        self.assertEqual(len(self.drop_rows()), 2)
        self.run_mw(MEMWATCH_HOUR_DAY='04 101')       # next day: again
        self.assertEqual(len(self.drop_rows()), 4)

    def test_drop_writes_the_cache_file(self):
        (self.t / 'boot.conf').write_text('MEMWATCH_DROP_HOUR="04"\n')
        self.run_mw(MEMWATCH_HOUR_DAY='04 100')
        self.assertEqual((self.proc / 'sys/vm/drop_caches').read_text().strip(), '3')

    def test_health_snapshot_hooks_it_in(self):
        s = (ROOT / 'scripts/health-snapshot.sh').read_text()
        self.assertIn('MEMWATCH_SCRIPT" sample', s)
        self.assertIn('MEMWATCH_SCRIPT" flush', s)

    def test_script_is_lf_and_in_boot_conf_dist(self):
        self.assertNotIn(b'\r', Path(MW).read_bytes())
        d = (ROOT / 'config/boot.conf.dist').read_text()
        self.assertIn('\nMEMWATCH=1\n', d)
        self.assertIn('\nMEMWATCH_DROP_HOUR=\n', d)


if __name__ == '__main__':
    unittest.main()
