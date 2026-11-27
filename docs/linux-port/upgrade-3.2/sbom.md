# `[up-sbom]`: software bill of materials and CVE report (plan phase 1, audit SEC-9)

Nothing here runs on the camera. Every CI build of the kernel workflow now writes the list of what is in the image
and a non-blocking report of known vulnerabilities, and ships both with the release.

## What is produced

| File | Content |
|---|---|
| `sbom.cdx.json` | CycloneDX 1.5 JSON: one component per package or program, `bom-ref` unique, licence, source URL, `cpe` and `purl` where they exist, `scope` (`required` = in the image, `excluded` = build-time only), the place in the image (`tc100:where`) |
| `sbom.md` | the same as a table: component, version, licence, source, where in the image; then the kernel patch series |
| `cve-report.md` / `cve-report.json` | the CVE report (below) |

Sources of the SBOM (`scripts/sbom.py`; no version is written in the script, everything is read):
- the Buildroot base system: `make show-info` JSON of the base build (`br-out/show-info.json`, saved next to
  `rootfs.cpio.gz` in the `tc100-base-rootfs` artifact; target packages only, host tools are not in the image);
- the kernel: `LINUX_TAG` / `LINUX_COMMIT` of `.github/ci-pins.sh` (on this branch `v6.6.163`, listed as
  6.6.163) and the names of `patches/kernel-6.6/series/*.patch`; the RTL8188FU firmware pin;
- musl of the free programs (`v3/musl/build-musl.sh`), the standalone Mbed TLS pin and the Buildroot pin (both
  `excluded`: test builds and build system; the image's Mbed TLS is the Buildroot package);
- the free programs of `src/` and the web UI: version = `VERSION` + 12 characters of the git commit, licence GPL-2.0-only;
  `esbuild` (from `src/webui/package-lock.json`) is listed as `excluded`: a build tool.

Without `show-info.json` (for example a base image restored from a cache made before this stream) the SBOM is still
written and says "the base system packages are NOT listed".

## Where it is in a CI run

- Artifact `tc100-3-release` (and the `-TESTKERNEL-` variant): `sbom.cdx.json`, `sbom.md`, `cve-report.md`,
  `cve-report.json` next to the zip and the tar.
- Artifact `tc100-base-rootfs`: now `rootfs.cpio.gz` and `show-info.json`.
- A tag `v3*` also attaches the four files to the GitHub release (the CVE ones only if present).
- Local: `python3 scripts/sbom.py --out /tmp/sbom` (without `--show-info` the base system is missing);
  `sh scripts/cve-report.sh sbom.cdx.json cve-report` (needs network; never fails).

## How to read the CVE report

1. **Data problems** come first: whatever could not be fetched (kernel.org, the NVD data of pkg-stats) is named. A
   missing answer is not a clean answer.
2. **Kernel**: the plain fact, for example "kernel 6.6.0, latest 6.6.y is 6.6.163 (163 stable releases behind)", from
   kernel.org `releases.json`. The remedy is the kernel stream (`[up-kernel]`), not a CVE list.
3. **Buildroot packages**: the CVEs Buildroot's own `support/scripts/pkg-stats` finds for the exact package versions
   (NVD data, fetched by pkg-stats itself). Packages without findings are counted, not listed; `unsure` marks a
   match the NVD data could not settle.

The step (`scripts/cve-report.sh`, then `scripts/cve-report.py`) has `continue-on-error: true`, ends in `exit 0`
and the Python part catches every exception: a network problem, a timeout (25 minutes for pkg-stats) or a finding
never fails the build. It checks out the pinned Buildroot tag (`git_clone_pinned`), so the CVE matching tool is the
version the base build uses. The NVD and kernel.org data are live data, not pinned: that is the point of a CVE
check, and the reason it only informs.

## Limits

- Kernel CVEs are not matched one by one (thousands per year, most in code this configuration does not build).
- The free programs of `src/`, the RTL8188FU firmware and the musl of the free programs have no CVE database
  matching; the first is our own code (see `[up-fuzz]` and the audit), the others are read from the SBOM by hand.
- There are no vendor binaries in the 3.0 image; if one is ever added it must be added to `FREE_PROGRAMS` or a pin so
  the SBOM lists it, otherwise it is invisible here.
- Licences are the strings of the Buildroot packages (`name`, not validated SPDX identifiers).
- `pkg-stats` options were written from Buildroot 2024.02 and the 2025.02 tooling is expected to accept them; if a
  later Buildroot changes them, the report says "pkg-stats did not finish" and the rest is still produced. Only a
  GitHub run confirms this.

## How a release uses it

Before tagging, read `cve-report.md` of the release run: note the kernel distance in the release notes, and decide per
finding (update the package, accept with a reason, or Buildroot has patched it). Keep `sbom.cdx.json` with the release:
a later CVE can be matched against it without rebuilding (any CycloneDX 1.5 scanner, for example `grype sbom:` or
`osv-scanner`, reads it). `tests/test_sbom.py` checks the generator on fixtures and that the workflow steps exist and
the CVE part is non-blocking.
