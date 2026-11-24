"""CLEANUP-1124 (audit 2026-11-24, section 5): the optimisations that were off by default, never paid or impossible are
gone. Their switches must not come back by accident: no source reads them, no shipped script or settings file sets
them. An rtsp.env that still sets one does no harm (tc100_rtsp ignores unknown variables; tests/test_tc100rtsp.py runs
the server with RTSP_UDPMMSG=1 and the live muxer with RTSP_LIVE_DIRECT=0 and gets the default bytes)."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

# tc100_rtsp switches removed on 2026-11-24
RTSP_GONE = ['RTSP_UDPMMSG', 'RTSP_PACING_US', 'RTSP_SNDBUF', 'RTSP_FRAMECOPY', 'RTSP_LIVE_DIRECT']

# what the camera runs or installs: a line there that sets one of the switches would be dead
SHIPPED = ['config', 'controlscripts', 'scripts', 'v3', 'www']


def shipped_files():
    for top in SHIPPED:
        for p in (ROOT / top).rglob('*'):
            if p.is_file() and p.suffix not in ('.png', '.jpg', '.gz', '.ico', '.woff2', '.svg'):
                yield p


class RemovedSwitches(unittest.TestCase):
    def test_tc100_rtsp_reads_none_of_the_removed_switches(self):
        for c in sorted((ROOT / 'src' / 'tc100rtsp').glob('*.c')):
            s = c.read_text(encoding='utf-8')
            for k in RTSP_GONE:
                self.assertNotIn('getenv("%s")' % k, s, '%s reads %s' % (c.name, k))

    def test_no_shipped_file_sets_a_removed_switch(self):
        pat = re.compile(r'^\s*(export\s+)?(%s)=' % '|'.join(RTSP_GONE), re.M)
        for p in shipped_files():
            try:
                s = p.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                continue
            m = pat.search(s)
            self.assertIsNone(m, '%s sets %s' % (p.relative_to(ROOT), m and m.group(2)))


if __name__ == '__main__':
    unittest.main()
