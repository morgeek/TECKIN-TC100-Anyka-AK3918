## Frontend Workflow

Frontend source now lives under `frontend/src/`.

Current source-to-output mapping:

- `frontend/src/js/camcontrols.js` -> `www/scripts/camcontrols.cgi.js`, `www/scripts/camcontrols.bundle.min.js`
- `frontend/src/js/index.js` -> `www/scripts/index.bundle.min.js`
- `frontend/src/js/scripts.js` -> `www/scripts/scripts.cgi.js`, `www/scripts/scripts.bundle.min.js`
- `frontend/src/js/status.js` -> `www/scripts/status.cgi.js`, `www/scripts/status.bundle.min.js`
- `frontend/src/js/view_records.js` -> `www/scripts/view_records.bundle.min.js`
- `frontend/src/css/ui-modern.css` -> `www/css/ui-modern.css`, `www/css/ui-modern.min.css`

Use:

```bash
npm run build:web
npm run check:web
```

Notes:

- This first pass is intentionally zero-dependency and offline-friendly.
- The build currently copies source bytes exactly to the shipped asset paths.
- `.bundle.min.js` and `.min.css` are legacy deploy filenames; they are not re-minified yet.
- `www/index.html` still contains a small inline script for PTT volume state. Moving inline page scripts into `frontend/src/` is the next cleanup step.
