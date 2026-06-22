---
name: validate-cgi
description: Review a CGI shell script for safety, correctness and camera compatibility. Use when adding or modifying a CGI endpoint.
---

Review the CGI script at $ARGUMENTS (or the most recently modified `.cgi` file if no argument given).

## Checklist

### Headers
- [ ] First output line is `Content-Type: application/json` (or appropriate MIME type)
- [ ] Blank line separates headers from body
- [ ] No output before the Content-Type header (sourced files must not echo)

### Input handling
- [ ] `QUERY_STRING` is URL-decoded before use
- [ ] `POST_DATA` is read from stdin when `REQUEST_METHOD=POST`
- [ ] No unsanitized input is passed to `eval`, `sh -c`, backtick expansion, or shell glob

### POSIX compliance (Busybox ash target)
- [ ] `#!/bin/sh` shebang (not bash)
- [ ] No `[[`, `]]`, `(( ))`, `$'...'`, `declare`, `local` (ash-only `local` is OK)
- [ ] `grep` without `-E`/`-P` flags, or uses `awk` instead
- [ ] No bash arrays; use space-separated strings or temp files

### JSON output
- [ ] Valid JSON even on error paths (return `{"error":"message"}` not raw text)
- [ ] Numbers unquoted, booleans as `true`/`false` not `"true"`/`"false"`
- [ ] Use `jq -n` for complex construction rather than manual string concatenation

### Security
- [ ] File paths validated/sanitized before use in `cat`, `rm`, `cp`
- [ ] No credentials or secrets hardcoded
- [ ] Config values read from `/mnt/config/*.conf`, not hardcoded

### Performance
- [ ] Long operations (`getimage`, `ffmpeg`) wrapped with `timeout N`
- [ ] Avoid `find` with unlimited depth on `/mnt/` — use targeted paths

Report each failing item with the line number and a suggested fix.
