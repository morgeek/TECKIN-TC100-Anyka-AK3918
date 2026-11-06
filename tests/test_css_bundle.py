"""www/css/ui.bundle.min.css is built by src/webui/build-css.sh from the three stylesheets index.html used to load."""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / 'www/css'


@unittest.skipUnless(shutil.which('node'), 'node needed')
class CssBundle(unittest.TestCase):

    def test_bundle_and_cache_buster_are_built_from_the_sources(self):
        r = subprocess.run(['node', str(ROOT / 'src/webui/build-css.mjs'), '--check'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_order_is_the_old_link_order(self):
        b = (CSS / 'ui.bundle.min.css').read_text()
        self.assertTrue(b.startswith('@charset "UTF-8";\n'))
        self.assertEqual(b.count('@charset'), 1)   # the one from ui.css would be invalid in the middle
        bulma = re.sub(r'@charset "UTF-8";\s*', '', (CSS / 'bulma.1.0.2.purged.min.css').read_text()).strip()
        modern = re.sub(r'@charset "UTF-8";\s*', '', (CSS / 'ui-modern.min.css').read_text()).strip()
        self.assertEqual(b.index(bulma), len('@charset "UTF-8";\n'))
        self.assertEqual(b.index(modern), b.index(bulma) + len(bulma) + 1)
        tail = b[b.index(modern) + len(modern):]
        self.assertTrue(tail.startswith('\n:root{'), tail[:40])   # ui.css, minified, last: it wins ties as before

    def test_only_the_bundles_are_linked_by_the_main_page(self):
        # item 50: the engine switch writes one of the two bundles (Pico by default since rc31, Bulma on request until
        # rc32); <noscript> loads Pico without script
        html = (ROOT / 'www/index.html').read_text()
        links = re.findall(r'<link href="(css/[^"?]*)', html)
        self.assertEqual(links, ['css/ui.pico.min.css', 'css/ui.bundle.min.css', 'css/ui.pico.min.css'])
        self.assertIn("var ui = 'pico';", html)
        self.assertIn("localStorage.getItem('tc100_ui') === 'bulma'", html)
        self.assertIn('<noscript><link href="css/ui.pico.min.css?v=', html)

    def test_pico_bundle_is_pico_then_shim_then_ui(self):
        b = (CSS / 'ui.pico.min.css').read_text()
        self.assertTrue(b.startswith('@charset "UTF-8";\n'))
        self.assertEqual(b.count('@charset'), 1)
        pico = re.sub(r'@charset "UTF-8";\s*', '', (CSS / 'pico-2.0.6.min.css').read_text()).strip()
        self.assertIn('Pico CSS', pico[:200])                        # as published, licence header kept
        self.assertEqual(b.index(pico), len('@charset "UTF-8";\n'))
        self.assertLess(b.index('.navbar-burger'), b.index('--v2-bg:'))   # shim before ui.css
        self.assertIn('html[data-ui="pico"]', b)                      # the token dictionary


if __name__ == '__main__':
    unittest.main()
