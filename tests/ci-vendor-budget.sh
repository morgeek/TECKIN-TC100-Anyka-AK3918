#!/bin/sh
# ci-vendor-budget.sh: the `vendor` flash partition against its budget (audit 2026-11-16, item CI-PIN).
# The vendor image is made on each camera at install (v3/install/install66.sh: mksquashfs of the sensor tuning isp.conf,
# xz, 256 KiB blocks), so CI cannot build the real one. It builds a stand-in the same way from a worst case isp.conf
# (ISP_MAX bytes of random data, which xz cannot shrink; the real file is about 12 KB compressed, docs/linux-port/flash-budget.md)
# and runs `scripts/flash_budget.py --vendor` on it: the build fails when the vendor part would exceed the partition.
# The budget: isp.conf at most ISP_MAX = 64 KiB (five times the measured size). A larger one needs this limit, the doc
# and VENDOR_MAX in v3/install/install66.sh changed together (tests/test_flash_budget.py).
#   sh tests/ci-vendor-budget.sh [FLASH_BUDGET_EXTRA_ARGS...]
set -eu
ISP_MAX=65536
REPO=$(cd "$(dirname "$0")/.." && pwd)
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
mkdir "$W/root"
head -c "$ISP_MAX" /dev/urandom > "$W/root/isp.conf"
mksquashfs "$W/root" "$W/vendor.sqfs" -comp xz -b 256K -noappend -all-root -quiet -processors 1 -mem 8M >/dev/null
python3 "$REPO/scripts/flash_budget.py" --vendor "$W/vendor.sqfs" "$@"
