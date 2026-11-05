"""Item 24: scripts/time-fallback.sh sets the clock from an HTTP Date header when NTP did not (router page by default)."""
import calendar
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']
SCRIPT = str(ROOT / 'scripts/time-fallback.sh')


class TimeFallback(unittest.TestCase):
    def test_parse_matches_python(self):
        for d in ('Thu, 05 Nov 2026 09:30:00 GMT', 'Mon, 29 Feb 2028 23:59:59 GMT', 'Wed, 01 Jan 2025 00:00:00 GMT',
                  'Sun, 31 Dec 2045 12:00:07 GMT'):
            r = subprocess.run(SH + [SCRIPT, 'parse', d], capture_output=True, text=True)
            self.assertEqual(int(r.stdout), calendar.timegm(time.strptime(d, '%a, %d %b %Y %H:%M:%S GMT')), d)
        for bad in ('', 'garbage', 'Thu, 05 Foo 2026 09:30:00 GMT', 'Thu, 05 Nov 1999 09:30:00 GMT', 'Thu, xx Nov 2026 09:30:00 GMT'):
            self.assertNotEqual(subprocess.run(SH + [SCRIPT, 'parse', bad], capture_output=True).returncode, 0, bad)

    def run_once(self, conf, curl_out, year='1970', mode='once'):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / 'boot.conf').write_text(conf)
            (t / 'curl').write_text('#!/bin/sh\necho "$@" >> %s/asked\nprintf "%%b" "%s"\n' % (t, curl_out)); (t / 'curl').chmod(0o755)
            (t / 'setdate').write_text('#!/bin/sh\necho "$@" >> %s/set\n' % t); (t / 'setdate').chmod(0o755)
            env = dict(TF_CONF=str(t / 'boot.conf'), TF_CURL=str(t / 'curl'), TF_DATE_SET=str(t / 'setdate'),
                       TF_GW='192.168.1.1', TF_YEAR=year, TF_CONSOLE='/dev/null', TF_TRIES='2', TF_GAP='0', PATH='/usr/bin:/bin')
            r = subprocess.run(SH + [SCRIPT, mode], env=env, capture_output=True, text=True, timeout=20)
            asked = (t / 'asked').read_text() if (t / 'asked').exists() else ''
            seta = (t / 'set').read_text() if (t / 'set').exists() else ''
            return r.returncode, asked, seta

    def test_router_page_by_default(self):
        rc, asked, seta = self.run_once('', 'HTTP/1.1 200 OK\\r\\nDate: Thu, 05 Nov 2026 09:30:00 GMT\\r\\n\\r\\n')
        self.assertEqual(rc, 0)
        self.assertIn('http://192.168.1.1/', asked)
        self.assertNotIn('google', asked)
        self.assertEqual(seta.strip(), '@1793871000')

    def test_list_order_and_no_date(self):
        rc, asked, seta = self.run_once('TIME_HTTP_URLS="gateway http://example.invalid/ ftp://x"\n', 'HTTP/1.1 200 OK\\r\\n\\r\\n')
        self.assertEqual(rc, 1)
        self.assertEqual(asked.count('http://'), 2)              # router, then the listed http:// address; ftp skipped
        self.assertEqual(seta, '')

    def test_run_does_nothing_when_set_or_off(self):
        rc, asked, _ = self.run_once('', 'Date: Thu, 05 Nov 2026 09:30:00 GMT\\r\\n', year='2026', mode='run')
        self.assertEqual((rc, asked), (0, ''))
        rc, asked, _ = self.run_once('TIME_HTTP_FALLBACK=0\n', 'Date: Thu, 05 Nov 2026 09:30:00 GMT\\r\\n', mode='run')
        self.assertEqual((rc, asked), (0, ''))

    def test_started_by_autorun_after_ntpd(self):
        a = (ROOT / 'v3/autorun-linux66.sh').read_text()
        self.assertLess(a.index('ntpd -p "$S"'), a.index('( sleep 120; exec sh /mnt/scripts/time-fallback.sh run )'))
        self.assertIn('TIME_HTTP_URLS=gateway', (ROOT / 'config/boot.conf.dist').read_text())


if __name__ == '__main__':
    unittest.main()
