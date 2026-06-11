# Frontend Workflow

Frontend source lives under `frontend/src/` and is the **single source of
truth** for the dashboard JS/CSS. The camera serves the copies under `www/`
verbatim — there is no transpile or minify step, so source and shipped files
must stay byte-identical. `npm run build:web` syncs them; `npm run check:web`
fails (exit 1) if they have drifted, which makes it suitable as a CI gate and
a pre-commit check.

```bash
npm run build:web   # sync frontend/src -> www
npm run check:web   # verify no drift (CI)
```

Source-to-output mapping (see `tools/build-web-assets.mjs`):

- `frontend/src/js/camcontrols.js`  -> `www/scripts/camcontrols.bundle.min.js`
- `frontend/src/js/index.js`        -> `www/scripts/index.bundle.min.js`
- `frontend/src/js/ptt-audio.js`    -> `www/scripts/ptt-audio.bundle.min.js`
- `frontend/src/js/scripts.js`      -> `www/scripts/scripts.bundle.min.js`
- `frontend/src/js/view_records.js` -> `www/scripts/view_records.bundle.min.js`
- `frontend/src/css/ui-modern.css`  -> `www/css/ui-modern.min.css`

The `.bundle.min.*` target names are historical deploy filenames referenced by
the HTML/CGI pages; the content is not minified.

## Editing rules

1. Edit files under `frontend/src/`, never the copies under `www/`.
2. Run `npm run build:web` before committing.
3. If `check:web` reports drift you did not cause, someone edited `www/`
   directly — diff the pair and port the change back into `frontend/src/`
   before rebuilding, or the rebuild will overwrite it.

## History

- The original `frontend/src` was deleted in commit `897e8b5` (2026-04-19)
  while the `www/` bundles kept evolving for ~13 commits without source.
- On 2026-06-11 the source tree was reconstructed **from the live bundles**
  (lossless: the bundles are plain readable JS/CSS). The bundles were
  authoritative until that date; `frontend/src` is authoritative since.
- `frontend/src/js/status.js` was retired: its output
  (`status.bundle.min.js.legacy`) was unreferenced and has been deleted.
- `www/css/ui-modern.css` (unreferenced "deep cobalt" design draft from
  commit `6a45117`) is intentionally **not** a build target: the pages load
  `ui-modern.min.css`. Adopt the draft by copying it over
  `frontend/src/css/ui-modern.css` and rebuilding — or delete it.

## Notes

- The dashboard is intentionally zero-dependency and offline-friendly
  (plain ES5-ish JS, no framework, no bundler).
- PTT requires HTTPS or localhost for microphone access (browser policy).
- Two-way audio requires the audio capture CGI support on the device.
- Both audio features degrade gracefully when unavailable.
