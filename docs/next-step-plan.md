# Next Step Plan

This plan prepares the next hardening/performance pass after the current update.

## Step 1: CGI parser hardening (`func.cgi`)
- Remove `eval`-based assignment from query parsing.
- Keep strict allowlist for parameter names and safe decoding.
- Add regression tests for parameter edge cases (`$`, backticks, quotes, long payloads).

## Step 2: Motion snapshot safety (`scripts/detectionOn.sh`)
- Replace `ls|awk|wc` pruning with `find`-based, filename-safe cleanup.
- Avoid races between cleanup and capture writes.
- Add a limit test ensuring oldest snapshots are removed safely.

## Step 3: Services UI output escaping (`scripts.cgi`)
- Add HTML escaping helper for service names/status labels before rendering.
- Keep table layout and current actions unchanged.
- Add UI test for escaped output (no raw `<`, `>`, `&` injection in table cells).

## Step 4: Validation tests expansion
- Add focused tests for:
  - `rewrite_config` escaping with `&`, `|`, backslashes.
  - Telnet/FTP port validation reject paths and accept paths.
  - `func.cgi` parse hardening.

## Rollout notes
- Deploy in two phases:
  1. parser + tests
  2. motion/services escaping + tests
- Keep FTP push/verify checklist:
  - upload changed CGI/JS/CSS
  - verify via FTP grep checks
  - hard-refresh browser cache
