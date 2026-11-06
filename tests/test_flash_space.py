"""Item 54: the flash image (v3/build-stack.sh) uses the xz ARM branch filter and leaves out what no page or script
on the camera loads: the 1 kHz test tones and the style sheets css/ui.bundle.min.css is built from."""
from pathlib import Path
import re
import unittest

from tests.test_flash_image import excluded

ROOT = Path(__file__).resolve().parents[1]


class FlashSpace(unittest.TestCase):
    def test_bcj_filter_with_a_switch(self):
        src = (ROOT / 'v3/build-stack.sh').read_text(encoding='utf-8')
        self.assertIn('case "${SQFS_BCJ:-arm}" in none) bcj= ;; *) bcj="-Xbcj ${SQFS_BCJ:-arm}" ;; esac', src)
        self.assertIn('mksquashfs "$T" "$OUT/stack.sqfs" -comp xz $bcj -b 128K', src)
        conf = (ROOT / 'patches/kernel-6.6/defconfig_cma').read_text()
        for k in ('CONFIG_XZ_DEC_ARM=y', 'CONFIG_XZ_DEC_BCJ=y', 'CONFIG_SQUASHFS_XZ=y'):
            self.assertIn(k, conf)

    def test_left_out_web_files_are_not_loaded(self):
        out = [n for n in excluded() if n.startswith('www/')]
        self.assertEqual(len(out), 10)   # the sources of the Bulma bundle (6) and of the Pico bundle (4)
        for n in out:
            self.assertTrue((ROOT / n.removesuffix('.gz')).is_file(), n)
        pages = list((ROOT / 'www').glob('*.html')) + list((ROOT / 'www/scripts').glob('*.js')) + \
            [p for p in (ROOT / 'www/cgi-bin').iterdir() if p.is_file()]
        for p in pages:
            text = p.read_text(encoding='utf-8', errors='replace')
            for n in out:
                name = Path(n).name.removesuffix('.gz')
                # a reference is a quoted URL (href=, src=, a JS string), not a word in a comment
                self.assertIsNone(re.search(r'["\'][^"\'\s]*' + re.escape(name) + r'(?:\?[^"\']*)?["\']', text),
                                  (name, str(p.relative_to(ROOT))))

    def test_test_tones_left_out(self):
        tones = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / 'sounds').glob('test-1k-*.pcm'))
        self.assertTrue(tones)
        self.assertEqual(sorted(n for n in excluded() if n.startswith('sounds/')), tones)

    def test_wizard_keeps_a_reset(self):
        w = (ROOT / 'www/cgi-bin/wizard.cgi').read_text(encoding='utf-8')
        self.assertNotIn('<link rel="stylesheet"', w)
        self.assertIn('html, body { margin: 0; }', w)


if __name__ == '__main__':
    unittest.main()
