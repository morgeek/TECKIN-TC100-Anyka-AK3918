"""www/css/ui.pico.min.css, the one style sheet of index.html, is built by src/webui/build-css.sh from Pico CSS,
pico-shim.css and ui.css (item 50; the Classic look, Bulma, was removed in rc32, owner 2026-11-06)."""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / 'www/css'


def classes(css):
    return set(re.findall(r'\.(-?[A-Za-z_][\w-]*)', re.sub(r'url\([^)]*\)|"[^"]*"', '', css)))


class CssBundle(unittest.TestCase):

    @unittest.skipUnless(shutil.which('node'), 'node needed')
    def test_bundle_and_cache_buster_are_built_from_the_sources(self):
        r = subprocess.run(['node', str(ROOT / 'src/webui/build-css.mjs'), '--check'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_one_sheet_linked_and_no_engine_switch(self):
        html = (ROOT / 'www/index.html').read_text(encoding='utf-8')
        self.assertEqual(re.findall(r'<link href="(css/[^"?]*)', html), ['css/ui.pico.min.css'])
        self.assertIn('<html class="has-navbar-fixed-top" data-ui="pico">', html)   # the shim's token map keys on it
        for gone in ('tc100_ui', 'ui.bundle.min.css', 'document.write'):
            self.assertNotIn(gone, html)
        self.assertNotIn('ui_engine', (ROOT / 'www/settings.html').read_text(encoding='utf-8'))
        for f in ('ui.bundle.min.css', 'bulma.1.0.2.purged.min.css', 'ui-modern.min.css'):
            self.assertFalse((CSS / f).exists(), f)

    def test_pico_bundle_is_pico_then_shim_then_ui(self):
        b = (CSS / 'ui.pico.min.css').read_text(encoding='utf-8')
        self.assertTrue(b.startswith('@charset "UTF-8";\n'))
        self.assertEqual(b.count('@charset'), 1)
        pico = re.sub(r'@charset "UTF-8";\s*', '', (CSS / 'pico-2.0.6.min.css').read_text(encoding='utf-8')).strip()
        self.assertIn('Pico CSS', pico[:200])                        # as published, licence header kept
        self.assertEqual(b.index(pico), len('@charset "UTF-8";\n'))
        self.assertLess(b.index('.navbar-burger'), b.index('--v2-bg:'))   # shim before ui.css
        self.assertIn('html[data-ui="pico"]', b)                      # the token dictionary

    def test_the_shim_draws_every_bulma_class_the_pages_use(self):
        # tests/fixtures/bulma-classes-used.txt: the Bulma 1.0.2 classes found in www/ when Bulma was removed; each one
        # must be styled by the shim, ui.css or Pico itself, or the page loses its layout (Settings -> Network lost its
        # horizontal fields until the shim had them). Words that only look like classes are listed here.
        used = (ROOT / 'tests/fixtures/bulma-classes-used.txt').read_text(encoding='utf-8').split()
        words = {'block', 'delete', 'dropdown', 'footer', 'grid', 'image', 'media', 'menu', 'panel'}
        styled = classes((CSS / 'pico-shim.css').read_text(encoding='utf-8')) | classes((CSS / 'ui.css').read_text(encoding='utf-8')) | \
            classes((CSS / 'pico-2.0.6.min.css').read_text(encoding='utf-8'))
        self.assertEqual(sorted(c for c in used if c not in styled and c not in words), [])


if __name__ == '__main__':
    unittest.main()
