# Browser checks of the web UI (manual, not in CI)

Audit D7: these scripts drive a real Chrome through its DevTools port; the CI has no browser, so they are a tool for
whoever changes the layout, not a test that runs by itself.

1. `python3 tests/ui-browser/make_fixture.py OUT` writes `OUT/fixture.html`: the Settings page with the style sheets
   and a fake `state.cgi`.
2. Start Chrome with `--remote-debugging-port=9339`.
3. `node tests/ui-browser/check.mjs OUT`: load result, script errors, layout at desktop and phone widths.
   `live-check.mjs` is the live video check: headless Chromium against a fake camera that streams a fragmented MP4
   (usage at the top of the file; it runs in the Playwright image).

The automatic checks of the UI are `tests/*.test.js` (node) and the Python tests that read the pages.
