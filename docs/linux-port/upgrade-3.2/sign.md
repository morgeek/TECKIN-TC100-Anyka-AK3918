# `[up-sign]`: authenticated update packages (Ed25519)

Plan phase 2 ([../plan-upgrade-3.1.md](../plan-upgrade-3.1.md)), finding SEC-4 of
[../audit-2026-11-27-security.md](../audit-2026-11-27-security.md): until now the web update checked the package
with `MD5SUMS`, which catches damage, not forgery. This stream adds an Ed25519 signature that the owner makes on his own
machine. The CI never holds a private key and signs nothing: an unsigned package is the normal CI output.

**What it protects, honestly.** The signature protects against a forged or tampered package installed by someone who does not
have the web password, or by the owner tricked into uploading it (a package from a fake download page, a swapped file). It
does not defend against a holder of the web password: the web administrator is root-equivalent on the camera (configuration
editor, scripts, ssh settings) and can switch the policy off on purpose or add his own public key. Policy 1 is therefore a
guard against mistakes and forged packages, not a barrier against the administrator. Two paths must not do it by accident or
by trick, and they are closed: a settings **restore** never installs or removes keys and never changes the policy (below).

Switch: `UPDATE_REQUIRE_SIG` in `/mnt/config/boot.conf` (`config/boot.conf.dist`, the single source). Default **0** on this
branch.

## What the camera does

`v3/install/update66.sh check DIR` (run at the upload by `www/cgi-bin/update.cgi` and again by `apply`, before anything
is stopped or written) verifies, in this order:

1. **Signature** (`verify_sig`): `SHA256SUMS.sig` against the public keys of the camera, with `tc100-sigcheck`.
2. **SHA256SUMS**: it must list exactly `VERSION stack.sqfs c66.img c66rd.gz MD5SUMS`, once each, then
   `sha256sum -c` (BusyBox; `CONFIG_SHA256SUM=y` is now explicit in `v3/buildroot/board/tc100/busybox.fragment`).
   `MD5SUMS` is in the list, so a signed package cannot carry another `MD5SUMS`.
3. The existing checks, unchanged: `MD5SUMS` names and sums (`flashw` still compares with them), sizes against the
   partitions, kernel and initrd image checks, squashfs magic.

Nothing here writes the flash. The order of `apply` is unchanged (check, backup room, stop, backup, write), so the
backup logic is untouched.

### Policy

| Package | `UPDATE_REQUIRE_SIG=0` (default) | `UPDATE_REQUIRE_SIG=1` |
|---|---|---|
| valid signature of an installed key | accepted, "signed (key ID)" | accepted |
| no signature, or no `SHA256SUMS` (older package) | accepted with a warning | **refused** |
| signed by a key that is not installed | accepted with a warning | **refused** |
| signature present and **bad** (changed `SHA256SUMS`, forged, truncated, garbage, `SHA256SUMS` missing) | **refused** | **refused** |
| `1` but **no usable public key** (the verifier counts the keys that parse: `tc100-sigcheck keys`; unreadable `.pub` files do not count) | | warning, behaves as `0`: it can never lock the owner out. A malformed or garbage signature is still refused |
| `1`, usable keys, signature present but not verifiable (unknown key id, forged, garbage) | | **refused** |
| verifier missing or failing (exit 2: unreadable or oversized file) | accepted with a warning (it cannot lock the owner out) | refused |
| `sha256sum` applet missing, `SHA256SUMS` present | warning, falls back to the MD5 checks (shown as unsigned, never "signed", because the files were not checked) | refused (with a usable key installed) |

"Bad" is decided by the key id written in the signature file: a signature that names an installed key and does not verify
is bad; one that names a key the camera does not have is "unknown" (accepted at 0, refused at 1). Stripping the signature
turns a package into "unsigned", which policy 0 accepts: policy 0 protects against accidents and in-transit tampering of a
signed package, not against an attacker who may also remove the signature. Policy 1 is the protection against that, within the limits stated above.

The value is read at each check from `boot.conf` (the environment variable wins, for tests); `0` or absent = 0, any
other value = 1. No restart needed.

The warning goes to the web page ("Unsigned: accepted (warning)") and, with a card, to `tc100-3/update66.log`
(`update signature: ...` lines, and `WARNING: installing a package that is not authenticated` at apply).

### The state line

`check` leaves one line in `/tmp/update66.sig`: `signed <keyid>`, `unsigned <why>` or `refused <why>`.
`update.cgi` returns it as `"sig"` and `"sig_info"` in the upload answer (also when refused) and in `cmd=status` while a
package is staged. `www/settings.html` shows it under the version line: "Signed (key 1a2b3c4d)", "Unsigned: accepted
(warning)", "Refused: <reason>", with French entries in `www/i18n/fr.js` ("Signé (clé ...)", "Non signé : accepté
(avertissement)", "Refusé : ...").

### Keys on the camera

- `/mnt/v3/install/update-keys/*.pub`: the keys of the image (the repository folder `v3/install/update-keys/`, public keys
  only, **none yet**).
- `/mnt/config/update-keys/*.pub`: keys the owner adds on the camera itself (kept across updates; also the way to test a
  key before committing it).

Persistence: `cfg-persist` saves every file of `config/` that differs from the shipped defaults, so `config/update-keys/*.pub`
goes to the flash slots with the other settings and comes back at each boot (checked by `tests/test_update_sig.py`). The
key list is never edited by a restore or a deletion list: the restore of an archive (Backup page,
`config_exchange.cgi cmd=restore`) skips everything under `config/update-keys/` (the answer says `skipped_update_keys`) and
keeps the camera's own `UPDATE_REQUIRE_SIG` line in the restored `boot.conf` (the archive's value is dropped, whether it
lowers or raises the policy); `cfg-persist`'s `apply_deleted` ignores `update-keys` entries. Changing the policy or the keys
is a deliberate act: the configuration editor (`configeditor.cgi`, which logs `configeditor_save` in the audit log), `ssh`,
or the SD-booted system. It is not a side effect of a restore or of the JSON import (that one only touches listed keys, and
`UPDATE_REQUIRE_SIG` is not listed).

Several keys can be installed at once (rotation). The keys that verify a package are the ones of the **running** image, so
a new key is first shipped in an image signed with the old one.

## Formats

- Public key `*.pub`: one line `<64 hex digits> [comment]` (lines starting with `#` are ignored). Private key `*.key`:
  one line, the 32-byte Ed25519 seed in 64 hex digits (mode 0600).
- Key id: the first 4 bytes of BLAKE2b-256 of the public key, 8 hex digits.
- `SHA256SUMS.sig`: one line `tc100-sig1 <keyid> <128 hex digits>`: a standard Ed25519 (RFC 8032, SHA-512) signature of
  the exact bytes of `SHA256SUMS`. The format is text so the shell can handle it; the signature itself checks with any
  Ed25519 library (the test does it with `cryptography` when installed).
- Update package (`tc100-<version>-update.tar`): `VERSION stack.sqfs c66.img c66rd.gz MD5SUMS SHA256SUMS` from the CI,
  plus `SHA256SUMS.sig` once signed. `SHA256SUMS` is written by `v3/build-release.sh` in the `sha256sum` format.

## Code

| Piece | File |
|---|---|
| verifier, host `keygen` / `sign` / `verify` | `src/sigcheck/sigcheck.c`, `Makefile` (musl, `src/musl.mk`, same hardening flags; `make host`) |
| Monocypher 4.0.2, unchanged | `src/sigcheck/monocypher.c`, `monocypher.h`, `monocypher-ed25519.c`, `monocypher-ed25519.h`, `LICENCE-monocypher.md` |
| image | `bin/tc100-sigcheck` (built by the release step of the CI workflow, copied by `v3/build-stack.sh`), `/mnt/bin/tc100-sigcheck` |
| updater | `v3/install/update66.sh` (`verify_sig`, `check`) |
| web | `www/cgi-bin/update.cgi`, `www/settings.html`, `www/i18n/fr.js` |
| package | `v3/build-release.sh` (`SHA256SUMS`, never the signature) |
| owner's tool | `scripts/sign_update.py` |
| tests | `tests/test_update_sig.py` (+ the ARM build under qemu in `tests/test_musl_programs_qemu.py`, flags in `tests/test_harden.py`) |

Monocypher: release tarball `monocypher-4.0.2.tar.gz` from monocypher.org, SHA-256
`38d07179738c0c90677dba3ceb7a7b8496bcfea758ba1a53e803fed30ae0879c`. Its `src/` files are identical to the GitHub tag `4.0.2`
except for the version line in the first line of each file (checked). Dual licence BSD-2-Clause / CC0, listed in
`CREDITS.md`. The camera build has no signing code (`-DSIGCHECK_HOST` only on the host).

## The owner's procedure

Needs `python3` and a C compiler (`cc`, `gcc` or `clang`) on the owner's machine; the tool compiles `src/sigcheck` itself.

1. **Make the key pair, once**, on his own machine, outside the repository:
   `python3 scripts/sign_update.py keygen ~/tc100-keys/owner` writes `owner.key` (PRIVATE) and `owner.pub` and prints the
   key id. Back up `owner.key` (an offline copy). Never put it in the repository, a chat or a synchronised folder.
2. **Publish the public key**: copy `owner.pub` to `v3/install/update-keys/<keyid>.pub` and commit it (public key only).
   It reaches the cameras with the next image.
3. **Sign a release**: download the CI artifact `tc100-3-release`, take `tc100-<version>-update.tar`, then
   `python3 scripts/sign_update.py sign ~/tc100-keys/owner.key tc100-<version>-update.tar -o tc100-<version>-update-signed.tar`.
   The tool re-checks `SHA256SUMS` against the files first, signs it, checks its own signature, and rebuilds the tar with the
   same members, order and times plus `SHA256SUMS.sig` (the same input gives the same bytes). Upload that tar in the web
   page.
4. **Check** (optional): `python3 scripts/sign_update.py verify tc100-<version>-update-signed.tar owner.pub` does what
   the camera does.
5. **Rotation**: make a second key, commit its `.pub` next to the first, release an image signed with the first key; once
   cameras run it, sign with the second and remove the first `.pub` in a later image. During the overlap both verify.
6. **Key lost or leaked**: a lost key means no more signed packages can be made, not a brick. With
   `UPDATE_REQUIRE_SIG=0` (or `1` with no key left) everything still installs. With `1` and the old key in the image, the
   next update goes through the **SD card**, which is not checked: `install66.sh` / `auto-install.sh` trust whoever holds
   the card (same trust as the physical camera), so a new image with a new `.pub` is installed that way, or the owner
   sets `UPDATE_REQUIRE_SIG=0` in `boot.conf` over ssh. A leaked key: do the same, then remove its `.pub`.

The SD-card install is deliberately left as it is: physical access is trusted, and it is the way back.

## Camera test (owner, from the SD-booted system, RAM only, nothing written to the flash)

The web page refuses uploads in trial mode (no `/tmp/flashmode`), and `update66.sh check` too. So the authenticity part
has its own read-only command, which runs on the camera started from the SD card (kernel and initramfs in RAM, nothing
written): `sh /mnt/v3/install/update66.sh sigcheck <folder>` (an unpacked package; `tar xf package.tar -C <folder>`) prints
`ok` or the reason, and leaves the state line in `/tmp/update66.sig`. The policy is read from `/mnt/config/boot.conf`, or
set for one run with `UPDATE_REQUIRE_SIG=1 sh ...`. Steps (the same on the web page of a camera running from the flash,
where the upload shows the same words):

1. **Unsigned CI package, policy 0**: unpack the CI `tc100-<version>-update.tar` and run `sigcheck`: `ok`, state
   `unsigned no signature ...` (web: "Unsigned: accepted (warning)" and the install button; "Discard" if only the check is wanted).
2. **Signed with a test key**: `python3 scripts/sign_update.py keygen test`, copy `test.pub` to
   `/mnt/config/update-keys/` on the camera, sign the package, unpack it, `sigcheck`. Expect `ok`, state `signed <key id>`.
3. **One byte changed**: change one byte of `stack.sqfs` in the signed tar (a hex editor), `sigcheck`. Expect "Refused: the package is
   damaged or changed (sha256)", before any write: the SD card backup folder and `tc100-3/update66.log` show no `writing` line.
   Change a byte of `SHA256SUMS` instead: "Refused: the signature of the package is not valid", also at policy 0.
4. **Policy 1**: `UPDATE_REQUIRE_SIG=1` in `/mnt/config/boot.conf`, the unsigned package: "Refused: the package is not
   signed...". The signed one still passes. Remove the test key and check the signed package again: refused (key not installed).
   With no key at all and `=1`: accepted with the warning (no lock-out).
5. Remove the test key and restore `UPDATE_REQUIRE_SIG=0` at the end.

On the camera the verifier can also be run directly:
`/mnt/bin/tc100-sigcheck verify SHA256SUMS SHA256SUMS.sig /mnt/config/update-keys; echo $?`.

## Tests

`tests/test_update_sig.py` (host, gcc and busybox ash): valid, changed file, changed `SHA256SUMS`, wrong key, truncated and
garbage signatures, key folders and rotation, missing signature at 0 and 1, 1 without keys, the policy from `boot.conf`,
the `SHA256SUMS` format, the CGI JSON, the owner's tool end to end including a reproducible tar. The ARM build runs under
qemu (`tests/test_musl_programs_qemu.py`). Local CI: `sh tests/docker/local-ci.sh tests` and `cross`.

## Remaining before 3.2 final

- The owner makes his key pair and commits his public key in `v3/install/update-keys/`.
- Switch the default to `UPDATE_REQUIRE_SIG=1` in `config/boot.conf.dist` (cameras already installed keep the value of
  their `boot.conf`; the key must be in the image first, otherwise `1` falls back to `0` with a warning).
- Camera round of the section above; then `CHANGELOG.md`, `test-queue.md` and the release notes (the main session).
- CI publishes `SHA256SUMS.txt` in the release artifact and the SHA-256 table in the workflow run summary
  (`$GITHUB_STEP_SUMMARY`) so the owner can verify the `.tar` before signing (`[up32-harden]`).
- Not covered by design: the boot chain (U-Boot is never written, no secure boot), and the SD-card install.
