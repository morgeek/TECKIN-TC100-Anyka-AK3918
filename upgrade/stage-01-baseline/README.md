# Stage 01 - Baseline

This folder captures the known-good package baseline before any future binary/library upgrade.

Files:
- `manifest.sha256`: hash snapshot of all `bin/*` and `lib/*` files
- `versions.txt`: extracted package version strings
- `abi.txt`: key ELF interpreter and `NEEDED` dependency list for critical binaries

Use this stage as rollback reference.
