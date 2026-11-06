"""Implementer fixes for the rc32 (owner: "do everything", 2026-11-06), from the tester's rc31 reports (R22-R26) and the
cleanup list of a-faire-implementeur.md."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def text(p):
    return (ROOT / p).read_text(encoding='utf-8')


class BrowserCacheAfterUpdate(unittest.TestCase):
    """R22: busybox httpd sends no Cache-Control; its Last-Modified let Chrome reuse index.html for hours by heuristic
    freshness, so the rc29 interface stayed after the rc31 update. Without Last-Modified every page is revalidated by
    ETag (304), and the stamped assets change URL."""

    def test_no_last_modified_etag_kept(self):
        frag = text('v3/buildroot/board/tc100/busybox.fragment')
        self.assertIn('# CONFIG_FEATURE_HTTPD_LAST_MODIFIED is not set', frag)
        self.assertNotIn('CONFIG_FEATURE_HTTPD_LAST_MODIFIED=y', frag)
        self.assertIn('CONFIG_FEATURE_HTTPD_ETAG=y', frag)
        self.assertIn('CONFIG_FEATURE_HTTPD_GZIP=y', frag)


if __name__ == '__main__':
    unittest.main()
