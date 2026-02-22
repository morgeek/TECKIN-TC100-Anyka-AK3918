# Stage 02 - Safe Drop-In Replacements

This stage tracks package sets that are safe to drop in without breaking the
project.

## Policy

Only hash-locked replacements are considered "safe drop-in":
- same path (`bin/...` or `lib/...`)
- same SHA-256 as baseline lock (`config/packages.lock.dist`)
- passes `tools/check_bundle_compat.sh`

## Current status (verified on February 22, 2026)

- No newer `bin/` or `lib/` package set has been validated as safe.
- Known TECKIN forks provide the same package hashes as the baseline.
- BusyBox alternates tested so far failed required applet checks.

## Build a safe drop-in bundle

```bash
./tools/build_hash_locked_dropin_bundle.sh /path/to/source-repo /tmp/safe-dropin-bundle
```

Then apply on camera with the existing safe upgrader:

```bash
/mnt/scripts/pkg-upgrade-safe.sh backup
/mnt/scripts/pkg-upgrade-safe.sh apply /mnt/upgrade-bundle
```
