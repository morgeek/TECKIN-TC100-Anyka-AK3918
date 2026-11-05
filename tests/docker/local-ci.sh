#!/bin/sh
# Local CI in Docker, run BEFORE pushing (the GitHub runs take 15-20 minutes each).
#   sh tests/docker/local-ci.sh tests    # Python regressions + frontend tests (as the CI job)
#   sh tests/docker/local-ci.sh cross    # ARM build of tc100_rtsp, libakuio, jpegenc, httpfront, tc100-mqttd, tc100-onvifd (as the kernel job)
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
		apt-get update -qq >/dev/null && apt-get install -y -qq busybox-static python3 gawk mawk >/dev/null 2>&1
		cp -r /src /w && cd /w && git config --global --add safe.directory /w
		# host test programs left in the working tree (ignored by git) look newer than their sources after the copy:
		# make would run them instead of building the current code
		rm -f src/tc100rtsp/test_rec src/tc100rtsp/test_rtsp src/tc100rtsp/test_util src/tc100rtsp/test_livemp4 src/tc100rtsp/test_adsp src/mqttd/tc100-mqttd-host
		# a git worktree has a .git file pointing outside the copy: give the tests a repository of their own
		if [ -f .git ]; then rm -f .git; git init -q && git add -A >/dev/null 2>&1; fi
		node --test tests/frontend.test.js tests/settings-save.test.js tests/records-timeline.test.js $(ls tests/live-video.test.js 2>/dev/null) >/tmp/node.log 2>&1 && echo "node: ok" || { echo "node: FAILED"; tail -30 /tmp/node.log; exit 1; }
		# as an ordinary user, like the GitHub runner: root reads through missing permission bits (a restore test
		# passed here and failed there for a week)
		chown -R node /w
		su node -c "git config --global --add safe.directory /w; cd /w && python3 -m unittest discover -s tests" >/tmp/py.log 2>&1
		grep -E "^(FAIL|ERROR):|^Ran|^FAILED|^OK" /tmp/py.log
		# no "Ran N tests" (python3 missing, an import error): not a pass
		grep -q "^Ran [1-9]" /tmp/py.log || { echo "python tests did not run"; tail -20 /tmp/py.log; exit 1; }
		# no known failure any more (audit D1: scripts/jsonflat.awk is portable, tested with every awk present)
		! grep -qE "^(FAIL|ERROR):" /tmp/py.log || { grep -A25 -E "^(FAIL|ERROR):" /tmp/py.log | head -80; exit 1; }' || rc=1
}

run_cross() {
	echo "== ARM cross build (arm-linux-gnueabi, as CI)"
	docker run --rm -v "$SRC:/src:ro" debian:bookworm sh -c '
		apt-get update -qq >/dev/null && apt-get install -y -qq gcc-arm-linux-gnueabi make gcc libc6-dev qemu-user python3 >/dev/null 2>&1
		cp -r /src /w && cd /w && set -e
		# versioned binaries that nothing ships (audit D2): a failed make must not pass on them
		rm -f src/libakuio/libakuio.so src/tc100rtsp/tc100_rtsp src/mqttd/tc100-mqttd src/onvifd/tc100-onvifd
		arm-linux-gnueabi-gcc -O2 -Wall -static src/jpegenc/jpegenc.c -o /tmp/jpegenc
		arm-linux-gnueabi-gcc -Os -Wall -marm -march=armv5te -nostdlib -static -fno-builtin -fno-pic -no-pie -Wl,--build-id=none -s src/httpfront/httpfront.c -o /tmp/httpfront
		arm-linux-gnueabi-gcc -Os -Wall -marm -march=armv5te -nostdlib -static -fno-builtin -fno-pic -no-pie -Wl,--build-id=none -s src/mdnsd/mdnsd.c -o /tmp/tc100-mdnsd
		# the freestanding ISP tools (audit D3/D9: isp_flip is rebuilt by the release build, isp_fps is a bench tool)
		arm-linux-gnueabi-gcc -Os -Wall -Werror -marm -march=armv5te -nostdlib -static -fno-builtin -fno-pic -no-pie -Wl,--build-id=none -s src/ispflip/isp_flip.c -o /tmp/isp_flip
		arm-linux-gnueabi-gcc -Os -Wall -Werror -marm -march=armv5te -nostdlib -static -fno-builtin -fno-pic -no-pie -Wl,--build-id=none -s src/ispfps/isp_fps.c -o /tmp/isp_fps
		make -C src/libakuio CROSS=arm-linux-gnueabi- >/tmp/make.log 2>&1 || { tail -30 /tmp/make.log; exit 1; }; grep -iE "warning" /tmp/make.log || true
		make -C src/tc100rtsp CROSS=arm-linux-gnueabi- >/tmp/make.log 2>&1 || { tail -30 /tmp/make.log; exit 1; }; grep -iE "warning" /tmp/make.log || true
		make -C src/mqttd CROSS=arm-linux-gnueabi- >/tmp/make.log 2>&1 || { tail -30 /tmp/make.log; exit 1; }; grep -iE "warning" /tmp/make.log || true
		make -C src/onvifd CROSS=arm-linux-gnueabi- >/tmp/make.log 2>&1 || { tail -30 /tmp/make.log; exit 1; }; grep -iE "warning" /tmp/make.log || true
		test -s src/tc100rtsp/tc100_rtsp && test -s src/libakuio/libakuio.so && test -s src/mqttd/tc100-mqttd && test -s src/onvifd/tc100-onvifd
		echo "tc100-mqttd (stripped, bytes): $(wc -c < src/mqttd/tc100-mqttd)"
		echo "tc100-onvifd (stripped, bytes): $(wc -c < src/onvifd/tc100-onvifd)"
		make -C src/tc100rtsp test_rtsp >/dev/null 2>&1 && echo "host test build: ok"
		python3 -m unittest -v tests.test_httpfront_qemu >/tmp/hf.log 2>&1 || { cat /tmp/hf.log; exit 1; }; grep -E "^(Ran|OK)|skipped" /tmp/hf.log
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
