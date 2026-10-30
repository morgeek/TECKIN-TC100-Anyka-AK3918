#!/bin/sh
# Local CI in Docker, run BEFORE pushing (the GitHub runs take 15-20 minutes each).
#   sh tests/docker/local-ci.sh tests    # Python regressions + frontend tests (as the CI job)
#   sh tests/docker/local-ci.sh cross    # ARM build of tc100_rtsp, libakuio, jpegenc, httpfront (as the kernel job)
#   sh tests/docker/local-ci.sh kernel   # Linux 6.6 + patches/kernel-6.6/series + zImage + dtbs (slow the first time)
#   sh tests/docker/local-ci.sh all      # the three
# Works from Git Bash on Windows (Docker Desktop) and from Linux. The tree is copied into the container (read-only
# mount): nothing in the working copy is changed. The kernel source and the build objects are kept in the Docker
# volume tc100-linux66 between runs.
set -e
cd "$(dirname "$0")/../.."
SRC=$(pwd -W 2>/dev/null || pwd)
export MSYS_NO_PATHCONV=1
what=${1:-all}
rc=0

run_tests() {
	echo "== tests (python + node, busybox ash)"
	docker run --rm -v "$SRC:/src:ro" node:22-bookworm sh -c '
		apt-get update -qq >/dev/null && apt-get install -y -qq busybox-static python3 >/dev/null 2>&1
		cp -r /src /w && cd /w && rm -f .git && git init -q 2>/dev/null; git config --global --add safe.directory /w
		[ -d /src/.git ] && { rm -rf .git; cp -r /src/.git .git; }
		node --test tests/frontend.test.js tests/settings-save.test.js >/tmp/node.log 2>&1 && echo "node: ok" || { echo "node: FAILED"; tail -30 /tmp/node.log; exit 1; }
		python3 -m unittest discover -s tests >/tmp/py.log 2>&1; grep -E "^(FAIL|ERROR):|^Ran|^FAILED|^OK" /tmp/py.log
		# known failure of this image only (awk flavour): JsonFlat.test_paths_types_and_escapes
		n=$(grep -E "^(FAIL|ERROR):" /tmp/py.log | grep -vc "JsonFlat.test_paths_types_and_escapes")
		[ "$n" = 0 ] || { grep -A25 -E "^(FAIL|ERROR):" /tmp/py.log | grep -v JsonFlat | head -80; exit 1; }' || rc=1
}

run_cross() {
	echo "== ARM cross build (arm-linux-gnueabi, as CI)"
	docker run --rm -v "$SRC:/src:ro" debian:bookworm sh -c '
		apt-get update -qq >/dev/null && apt-get install -y -qq gcc-arm-linux-gnueabi make gcc libc6-dev >/dev/null 2>&1
		cp -r /src /w && cd /w && set -e
		arm-linux-gnueabi-gcc -O2 -Wall -static src/jpegenc/jpegenc.c -o /tmp/jpegenc
		arm-linux-gnueabi-gcc -Os -Wall -marm -march=armv5te -nostdlib -static -fno-builtin -fno-pic -no-pie -Wl,--build-id=none -s src/httpfront/httpfront.c -o /tmp/httpfront
		make -C src/libakuio CROSS=arm-linux-gnueabi- 2>&1 | grep -iE "warning|error" || true
		make -C src/tc100rtsp CROSS=arm-linux-gnueabi- 2>&1 | grep -iE "warning|error" || true
		test -s src/tc100rtsp/tc100_rtsp && test -s src/libakuio/libakuio.so
		make -C src/tc100rtsp test_rtsp >/dev/null 2>&1 && echo "host test build: ok"
		echo "cross: ok"' || rc=1
}

run_kernel() {
	echo "== kernel (v6.6 + series, zImage + dtbs)"
	docker volume create tc100-linux66 >/dev/null
	docker run --rm -v "$SRC:/src:ro" -v tc100-linux66:/k debian:bookworm sh -c '
		apt-get update -qq >/dev/null && apt-get install -y -qq build-essential bc libssl-dev libelf-dev flex bison \
			gcc-arm-linux-gnueabi git curl ca-certificates device-tree-compiler u-boot-tools >/dev/null 2>&1
		set -e
		[ -d /k/v6.6 ] || git clone -q --depth 1 -b v6.6 https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git /k/v6.6
		cd /k/v6.6 && git config user.email ci@example.invalid && git config user.name ci
		git am --abort >/dev/null 2>&1 || true
		git reset -q --hard v6.6 2>/dev/null || git reset -q --hard "$(git rev-list --max-parents=0 HEAD | head -1)"
		git am -q --whitespace=nowarn /src/patches/kernel-6.6/series/*.patch
		mkdir -p firmware/rtlwifi
		[ -s firmware/rtlwifi/rtl8188fufw.bin ] || curl -sfL --retry 3 "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/rtlwifi/rtl8188fufw.bin?h=20241017" -o firmware/rtlwifi/rtl8188fufw.bin
		cp /src/patches/kernel-6.6/defconfig_cma .config
		make -s ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- olddefconfig
		make -s ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- -j"$(nproc)" zImage dtbs 2>&1 | grep -E "warning:|error:|Error" | grep -v "^scripts/" | head -40
		test -s arch/arm/boot/zImage && ls -l arch/arm/boot/zImage arch/arm/boot/dts/anyka/*.dtb && echo "kernel: ok"' || rc=1
}

case "$what" in
	tests) run_tests ;;
	cross) run_cross ;;
	kernel) run_kernel ;;
	all) run_tests; run_cross; run_kernel ;;
	*) echo "usage: $0 tests|cross|kernel|all"; exit 2 ;;
esac
[ "$rc" = 0 ] && echo "== local CI: ok" || echo "== local CI: FAILED"
exit $rc
