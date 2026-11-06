"""Audit 2026-11-06 S5 (owner: JS and HTML only, the shell stays readable): v3/build-stack.sh minifies the web
JavaScript and the inline <script>/<style> of the pages in its build tree with src/webui/minify.mjs (esbuild), before
the .gz step; the CI makes it mandatory. git keeps the readable files."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / 'src/webui'
HAVE_ESBUILD = bool(shutil.which('node')) and (WEBUI / 'node_modules/esbuild').is_dir()


class Wiring(unittest.TestCase):
    def test_build_minifies_before_the_gz_and_never_the_shell(self):
        s = (ROOT / 'v3/build-stack.sh').read_text()
        self.assertLess(s.index('node src/webui/minify.mjs "$T/www"'), s.index('GZ_WWW='))
        self.assertIn('[ "$mrc" = 3 ] && [ "${MINIFY_WWW:-auto}" != 1 ]', s)
        self.assertNotRegex(s, r'shfmt|minify[^\n]*\$T/(scripts|controlscripts)')
        m = (WEBUI / 'minify.mjs').read_text()
        self.assertNotIn('.cgi', m)                       # CGI shell scripts (wizard.cgi included) untouched

    def test_ci_installs_a_pinned_esbuild_and_requires_it(self):
        wf = (ROOT / '.github/workflows/build-kernel-linux66.yml').read_text()
        self.assertIn('npm install --prefix src/webui --no-save --no-audit --no-fund esbuild@0.21.5', wf)
        self.assertIn('MINIFY_WWW=1 READELF=arm-linux-gnueabi-readelf sh v3/build-stack.sh', wf)
        self.assertEqual(json.loads((WEBUI / 'package.json').read_text())['devDependencies']['esbuild'], '0.21.5')


@unittest.skipUnless(HAVE_ESBUILD, 'esbuild not installed (npm install --prefix src/webui)')
class Minify(unittest.TestCase):
    def run_min(self, files):
        with tempfile.TemporaryDirectory() as t:
            for name, text in files.items():
                Path(t, name).write_text(text, encoding='utf-8')
            r = subprocess.run(['node', str(WEBUI / 'minify.mjs'), t], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            return {n: Path(t, n).read_text(encoding='utf-8') for n in files}

    def test_globals_kept_markup_untouched(self):
        page = ('<p class="help">Card  with   files.</p>\n<pre>a\n  b</pre>\n'
                '<script>\n  // comment\n  function showThing(longArgument) { var localName = longArgument; return localName; }\n</script>\n'
                '<script type="application/json">{ "keep" :  1 }</script>\n<script src="x.js"></script>\n'
                '<style>\n  .a  {  color : red ; }\n</style>\n<button onclick="showThing(1)">Go</button>')
        out = self.run_min({'p.html': page, 'fr.js': 'var dict = {\n  "Café": "Café"\n};\n'})
        h = out['p.html']
        self.assertIn('<p class="help">Card  with   files.</p>', h)          # text nodes untouched (i18n)
        self.assertIn('<pre>a\n  b</pre>', h)
        self.assertIn('function showThing(', h)                             # global kept for onclick
        self.assertNotIn('// comment', h)
        self.assertIn('{ "keep" :  1 }', h)                                 # not JavaScript: left alone
        self.assertIn('.a{color:red}', h)
        self.assertIn('Café', out['fr.js'])                                  # UTF-8 kept


if __name__ == '__main__':
    unittest.main()
