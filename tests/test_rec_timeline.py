"""Item 36: the recordings timeline. The recorder writes the event times into the .evt marker; viewrecords.cgi
day_index turns a day of files into a compact index (start, duration from the mtime, size, event spans) that the
page draws, so the camera does no drawing or video work."""
from pathlib import Path
import calendar
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def func():
    s = (ROOT / 'www/cgi-bin/viewrecords.cgi').read_text(encoding='utf-8')
    return s[s.index('rec_day_index() {'):s.index('sanitize_record_name() {')]


class DayIndex(unittest.TestCase):
    def run_index(self, d, conf, date='2026-11-05'):
        code = 'DCIM_FOLDER=%s\n' % shlex.quote(d.as_posix()) + \
            func().replace('/mnt/config/boot.conf', conf.as_posix()) + 'rec_day_index %s\n' % date
        r = subprocess.run(SH + ['-c', code], capture_output=True, text=True, env=dict(os.environ, TZ='UTC-2'))
        self.assertEqual(r.stderr, '')
        return json.loads(r.stdout)

    def test_index(self):
        def local(h, m, s, day=5):	# camera local time (UTC+2) -> epoch
            return calendar.timegm((2026, 11, day, h, m, s)) - 2 * 3600

        with tempfile.TemporaryDirectory() as t:
            d = Path(t, 'DCIM'); d.mkdir()
            conf = Path(t, 'boot.conf'); conf.write_text('REC_SEGMENT_SEC=300\n')
            files = {
                '2026-11-05_10-00-00.mp4': (local(10, 5, 0), 'on 12\noff 40\non 250\n'),
                '2026-11-05_10-05-00.mp4': (local(10, 7, 0), ''),          # an old empty marker
                '2026-11-05_12-00-00.mp4': (local(14, 0, 0), None),        # mtime far after: unknown length
                '2026-11-05_23-58-00.mkv': (local(0, 3, 0, 6), 'bad line\noff 3\non x\non 5\noff 9\n'),
            }
            for name, (mtime, evt) in files.items():
                p = d / name; p.write_bytes(b'x' * 3000); os.utime(p, (mtime, mtime))
                if evt is not None:
                    (d / (name[:19] + '.evt')).write_text(evt)
            (d / '2026-11-05_10-00-00.jpg').write_bytes(b'j')
            (d / '2026-11-04_10-00-00.mp4').write_bytes(b'x')              # another day
            got = self.run_index(d, conf)
            self.assertEqual(got['seg'], 300)
            self.assertEqual(got['files'], [
                {'t': '10-00-00', 'x': 'mp4', 'd': 300, 'kb': 3, 'e': [12, 40, 250, -1]},
                {'t': '10-05-00', 'x': 'mp4', 'd': 120, 'kb': 3, 'e': []},
                {'t': '12-00-00', 'x': 'mp4', 'd': -1, 'kb': 3},
                {'t': '23-58-00', 'x': 'mkv', 'd': 300, 'kb': 3, 'e': [5, 9]},
            ])
            conf.write_text('REC_SEGMENT_SEC=60\n')
            self.assertEqual(self.run_index(d, conf)['seg'], 60)
            self.assertEqual(self.run_index(d, conf, '2026-11-07'), {'seg': 60, 'files': []})
            self.assertEqual(self.run_index(Path(t, 'none'), conf), {'seg': 300, 'files': []})

    def test_cgi_command_checks_the_date(self):
        s = (ROOT / 'www/cgi-bin/viewrecords.cgi').read_text(encoding='utf-8')
        arm = s[s.index('    day_index)'):s.index('    list_records)')]
        self.assertIn('[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) rec_day_index "$dateVal" ;;', arm)

    def test_recorder_writes_the_times(self):
        s = (ROOT / 'src/tc100rtsp/rec.c').read_text(encoding='utf-8')
        self.assertIn('if (W.fd >= 0 && !r_motion != !W.evt_on) mark_event(!!r_motion, W.last_ts);', s)
        self.assertIn(r'k = snprintf(l, sizeof l, "%s %lu\n", on ? "on" : "off", off);', s)


if __name__ == '__main__':
    unittest.main()
