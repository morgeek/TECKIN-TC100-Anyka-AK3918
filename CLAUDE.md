# TECKIN TC100 — Anyka AK3918 Firmware Extension

See @README.md for project overview and @package.json for available npm commands.

## Commands

```bash
npm run build:web      # Sync frontend/src/ → www/ (run after every JS/CSS edit)
npm run check:web      # Verify no drift between source and served assets (CI gate)
node tools/build-web-assets.mjs --check  # Same as check:web, verbose
```

## CRITICAL: Frontend source of truth

**NEVER edit files in `www/scripts/` or `www/css/ui-modern.min.css` directly.**
Always edit `frontend/src/js/*.js` or `frontend/src/css/ui-modern.css`, then run `npm run build:web`.
The `.min.*` suffix is historical — no actual minification happens.

## Code style

### Shell (CGI scripts and daemons)
- POSIX sh only — no bash-isms (`[[`, `$((...))`, arrays, etc.)
- Camera runs Busybox ash; assume no `grep -E`, use `grep -e` or `awk`
- CGI scripts: always print `Content-Type: application/json` header, then blank line, then JSON
- Config files: `key=value` format (no spaces around `=`), sourced with `. /mnt/config/foo.conf`
- Use `command -v tool` to test availability before calling optional binaries

### JavaScript (frontend)
- Vanilla ES5 — no modules, no transpiler, no frameworks beyond Bulma
- Zero npm runtime dependencies
- Functions are global; no `class`, no arrow functions in hot paths (camera browser compat)

## Camera environment

- Default IP: `192.168.1.24`, FTP port `2121`, HTTP port `80`/`443`
- FTP credentials: `root:pass` (set in `config/boot.conf`)
- All paths on camera: `/mnt/` prefix (MicroSD mount)
- Binaries available: `busybox`, `curl`, `jq`, `ffmpeg`, `lighttpd`, `openssl`, `v4l2rtspserver`

## Workflow

1. Edit source files in `frontend/src/` or shell scripts
2. Run `npm run build:web` after any JS/CSS change
3. Deploy to camera via FTP: `curl --ftp-create-dirs -T <file> ftp://root:pass@192.168.1.24:2121/mnt/<path>`
4. Verify: `npm run check:web` must pass before committing
5. Branch naming: `feature/`, `fix/`, `chore/` prefixes

## Architecture rules

- CGI endpoints live in `www/cgi-bin/` — shell scripts, executable, `#!/bin/sh`
- `controlscripts/` are on/off toggles (start/stop daemons); they read `$1 = on|off`
- `scripts/` are autonomous daemons or one-shot operations
- `config/autostart/` scripts run in numeric order at boot via `autorun.sh`
- Config templates: `*.conf.dist` — never modify; user copies to `*.conf`

## Common pitfalls

- `jq` on camera is limited; avoid complex `.[]` chained filters
- `lighttpd` CGI: QUERY_STRING is URL-encoded; always decode before use
- Motion events log to `/mnt/logs/events.log`; rotate with `tail -n 500`
- `getimage` blocks until frame captured; timeout with `timeout 5 getimage`
- PTT audio requires HTTPS (browser mic API) — HTTP fallback shows error
