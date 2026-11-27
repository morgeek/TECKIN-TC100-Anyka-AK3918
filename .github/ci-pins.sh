#!/bin/sh
# Pinned third-party inputs of the CI and of the local build scripts (audit 2026-11-16, item CI-PIN). One place per
# artifact: the workflows, tests/docker/*.sh and scripts/build-kernel-docker.sh source this file, so a version and its
# checksum can only be changed here. tests/test_ci_pinning.py checks that every download is followed by a hash check.
#   . .github/ci-pins.sh
#   fetch_sha256 SHA256 OUTFILE URL [URL...]      first URL whose content has this SHA-256; fails otherwise
#   git_clone_pinned TAG COMMIT DIR URL [URL...]  shallow clone of TAG; fails unless HEAD is COMMIT
# Not pinned here, by design: the musl tarball (v3/musl/build-musl.sh keeps its own SHA-256), the Buildroot downloads
# (Buildroot checks each one against its .hash file), the npm packages (src/webui/package-lock.json, `npm ci`), the
# Python packages (tests/docker/requirements-whep-interop.txt, `pip --require-hashes`), apt packages (signed by the
# distribution) and the Docker base images (tags).

LINUX_TAG=v6.6
LINUX_COMMIT=ffc253263a1375a65fa6c9f62a893e9767fbebfa
BUILDROOT_TAG=2025.02.20
BUILDROOT_COMMIT=2f9129e7909bff6d78ae8cfda3d0e73503dfcac6
MBEDTLS_VERSION=3.6.7
MBEDTLS_SHA256=a7e8bcbec0e6f761b4af24f25677626b35f762f68eef79c08677a363212d11f6
# RTL8188FU firmware (embedded in the kernel), linux-firmware tag and the file's checksum (patches/kernel-6.6/series/README.md)
LINUX_FIRMWARE_TAG=20241017
RTL8188FU_FW_SHA256=e6189d6d7032b83f0ed4284629c43db66262449a866f33fd329e611239f62e1f
RTL8188FU_FW_URLS="https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/rtlwifi/rtl8188fufw.bin?h=$LINUX_FIRMWARE_TAG https://gitlab.com/kernel-firmware/linux-firmware/-/raw/$LINUX_FIRMWARE_TAG/rtlwifi/rtl8188fufw.bin"
LINUX_URLS="https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git https://github.com/torvalds/linux.git"
MBEDTLS_URL="https://github.com/Mbed-TLS/mbedtls/releases/download/mbedtls-$MBEDTLS_VERSION/mbedtls-$MBEDTLS_VERSION.tar.bz2"

fetch_sha256() {
	_sha=$1; _out=$2; shift 2
	for _u in "$@"; do
		curl -sfL --retry 3 "$_u" -o "$_out" || continue
		if echo "$_sha  $_out" | sha256sum -c - >/dev/null 2>&1; then return 0; fi
		echo "fetch_sha256: SHA-256 mismatch for $_u" >&2
		rm -f "$_out"
	done
	echo "fetch_sha256: no source gave $_out with SHA-256 $_sha" >&2
	return 1
}

git_clone_pinned() {
	_tag=$1; _commit=$2; _dir=$3; shift 3
	for _u in "$@"; do
		rm -rf "$_dir"
		git clone -q --depth 1 -b "$_tag" "$_u" "$_dir" || continue
		_head=$(git -C "$_dir" rev-parse HEAD)
		if [ "$_head" = "$_commit" ]; then return 0; fi
		echo "git_clone_pinned: $_u $_tag is $_head, expected $_commit" >&2
		rm -rf "$_dir"
	done
	echo "git_clone_pinned: no source gave $_tag at $_commit" >&2
	return 1
}
