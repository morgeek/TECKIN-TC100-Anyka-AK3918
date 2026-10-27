#!/usr/bin/env python3
"""Web UI wiring: every CGI command a page or script calls has a handler, and every field a settings form posts is
read by the handler (an F_<name> variable). Static check, no camera needed. Run: python3 -m unittest tests.test_webui_wiring
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WWW = ROOT / 'www'
CGI = WWW / 'cgi-bin'
REF = re.compile(r"cgi-bin/([a-z_]+)\.cgi(\?[^\"'`\s)]*)?")
# commands handled in the browser only (HTTP Basic auth has no server-side logout: the page replaces the credentials)
CLIENT_SIDE = {('action', 'logout')}


def handler_text(cgi):
    t = (CGI / (cgi + '.cgi')).read_text(errors='ignore')
    if cgi == 'action':
        t += ''.join(p.read_text(errors='ignore') for p in (ROOT / 'scripts/action.d').glob('*.sh'))
    return t


def handles(text, cmd):
    return bool(re.search(r'(^|[\s|(:"])' + re.escape(cmd) + r'(\|[^)\n]*)?\)', text, re.M))


class WebUiWiring(unittest.TestCase):
    def test_every_called_command_has_a_handler(self):
        files = list(WWW.glob('*.html')) + list((WWW / 'scripts').glob('*.js')) + [CGI / 'wizard.cgi']
        refs = set()
        for f in files:
            for m in REF.finditer(f.read_text(errors='ignore')):
                cm = re.search(r'cmd=([A-Za-z0-9_]+)', m.group(2) or '')
                self.assertTrue((CGI / (m.group(1) + '.cgi')).exists(), (f.name, m.group(1)))
                if cm:
                    refs.add((m.group(1), cm.group(1)))
        self.assertGreater(len(refs), 50)
        missing = sorted(r for r in refs - CLIENT_SIDE if not handles(handler_text(r[0]), r[1]))
        self.assertEqual(missing, [], 'commands called by the UI without a handler')

    def test_every_called_action_command_is_routed(self):
        # action.cgi runs a command only when its dispatch table names it (or it is handled before the table):
        # a handler in scripts/action.d that the table forgets answers "Unsupported command".
        a = (CGI / 'action.cgi').read_text(errors='ignore')
        i = a.index('# Each command lives in scripts/action.d')
        j = a.index('*) _action_group= ;;', i)
        routed = set()
        for m in re.finditer(r'^\s+([a-z0-9_|.-]+)\)\s*$', a[i:j], re.M):
            routed |= set(m.group(1).split('|'))
        called = set()
        for f in list(WWW.glob('*.html')) + list((WWW / 'scripts').glob('*.js')) + [CGI / 'wizard.cgi']:
            called |= set(re.findall(r'cgi-bin/action\.cgi\?cmd=([A-Za-z0-9_]+)', f.read_text(errors='ignore')))
        missing = sorted(c for c in called - routed - {c for _, c in CLIENT_SIDE} if not handles(a[:i], c))
        self.assertEqual(missing, [], 'action.cgi commands called by the UI but not routed')

    def test_json_answers_are_asked_for(self):
        # action.cgi answers JSON only with format=json (or Accept: application/json, which the pages do not send);
        # otherwise it appends "<hr/>" and a page that parses the answer as JSON shows an error after a success.
        bad = []
        for f in list(WWW.glob('*.html')) + list((WWW / 'scripts').glob('*.js')):
            s = f.read_text(errors='ignore')
            for m in re.finditer(r"cgi-bin/action\.cgi\?cmd=([A-Za-z0-9_]+)[^'\"]*", s):
                if 'format=json' in m.group(0):
                    continue
                if re.search(r'\.json\(\)', s[m.end():m.end() + 260]):
                    bad.append((f.name, m.group(1)))
        self.assertEqual(sorted(bad), [], 'action.cgi answers parsed as JSON without format=json')

    def test_every_form_field_is_read_by_its_handler(self):
        html = (WWW / 'settings.html').read_text(errors='ignore')
        unread = []
        for fm in re.finditer(r'<form([^>]*)>(.*?)</form>', html, re.S):
            a = re.search(r'action="cgi-bin/([a-z_]+)\.cgi\?cmd=([a-z_0-9]+)"', fm.group(1))
            if not a:
                continue
            text = handler_text(a.group(1))
            for n in set(re.findall(r'<(?:input|select|textarea)[^>]*\bname="([^"]+)"', fm.group(2))):
                if not re.search(r'F_' + re.escape(n) + r'\b', text):
                    unread.append((a.group(2), n))
        self.assertEqual(sorted(unread), [], 'form fields no handler reads')


if __name__ == '__main__':
    unittest.main()
