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

    def test_only_the_bundle_is_linked_by_the_main_page(self):
        html = (ROOT / 'www/index.html').read_text()
        links = re.findall(r'<link href="(css/[^"?]*)', html)
        self.assertEqual(links, ['css/ui.bundle.min.css'])


if __name__ == '__main__':
    unittest.main()
