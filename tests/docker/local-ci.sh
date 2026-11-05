#!/bin/sh
# Local CI in Docker, run BEFORE pushing (the GitHub runs take 15-20 minutes each).
#   sh tests/docker/local-ci.sh tests    # Python regressions + frontend tests (as the CI job)
#   sh tests/docker/local-ci.sh cross    # ARM build of tc100_rtsp, libakuio, jpegenc, httpfront, tc100-mqttd, tc100-onvifd, tc100-logfwd, libnetacl.so (as the kernel job)
#   sh tests/docker/local-ci.sh kernel   # Linux 6.6 + patches/kernel-6.6/series + zImage + dtbs (slow the first time)
#   sh tests/docker/local-ci.sh whep     # item 35: the WHEP daemon against aiortc (builds mbedTLS, needs network; not part of all)
#   sh tests/docker/local-ci.sh all      # tests, cross, kernel
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
		apt-get update -qq >/dev/null && apt-get install -y -qq busybox-static python3 gawk mawk original-awk >/dev/null 2>&1
		cp -r /src /w && cd /w && git config --global --add safe.directory /w
		# host test programs left in the working tree (ignored by git) look newer than their sources after the copy:
		# make would run them instead of building the current code
		rm -f src/tc100rtsp/test_rec src/tc100rtsp/test_rtsp src/tc100rtsp/test_util src/tc100rtsp/test_livemp4 src/tc100rtsp/test_adsp src/mqttd/tc100-mqttd-host src/supervisord/tc100-supervisord-host
		# a git worktree has a .git file pointing outside the copy: give the tests a repository of their own
		if [ -f .git ]; then rm -f .git; git init -q && git add -A >/dev/null 2>&1; fi
		node --test tests/frontend.test.js tests/settings-save.test.js tests/records-timeline.test.js $(ls tests/live-video.test.js tests/whep-live.test.js 2>/dev/null) >/tmp/node.log 2>&1 && echo "node: ok" || { echo "node: FAILED"; tail -30 /tmp/node.log; exit 1; }
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
		apt-get update -qq >/dev/null && apt-get install -y -qq gcc-arm-linux-gnueabi make gcc libc6-dev qemu-user python3 busybox-static >/dev/null 2>&1
		cp -r /src /w && cd /w && set -e
		# versioned binaries that nothing ships (audit D2): a failed make must not pass on them
		rm -f src/libakuio/libakuio.so src/tc100rtsp/tc100_rtsp src/mqttd/tc100-mqttd src/supervisord/tc100-supervisord src/onvifd/tc100-onvifd src/logfwd/tc100-logfwd src/netacl/libnetacl.so
		arm-linux-gnueabi-gcc -O2 -Wall -static src/jpegenc/jpegenc.c -o /tmp/jpegenc
		arm-linux-gnueabi-gcc -Os -Wall -marm -march=armv5te -nostdlib -static -fno-builtin -fno-pic -no-pie -Wl,--build-id=none -s src/httpfront/httpfront.c -o /tmp/httpfront
		arm-linux-gnueabi-gcc -Os -Wall -marm -march=armv5te -nostdlib -static -fno-builtin -fno-pic -no-pie -Wl,--build-id=none -s src/mdnsd/mdnsd.c -o /tmp/tc100-mdnsd
		# the freestanding ISP tools (audit D3/D9: isp_flip is rebuilt by the release build, isp_fps is a bench tool)
		arm-linux-gnueabi-gcc -Os -Wall -Werror -marm -march=armv5te -nostdlib -static -fno-builtin -fno-pic -no-pie -Wl,--build-id=none -s src/ispflip/isp_flip.c -o /tmp/isp_flip
		arm-linux-gnueabi-gcc -Os -Wall -Werror -marm -march=armv5te -nostdlib -static -fno-builtin -fno-pic -no-pie -Wl,--build-id=none -s src/ispfps/isp_fps.c -o /tmp/isp_fps
		# item 35: the SRTP bench, its self-test under qemu (the published vectors, on the instruction set of the camera)
		arm-linux-gnueabi-gcc -O2 -Wall -Wextra -Werror -static -march=armv5te -mtune=arm926ej-s -s -o /tmp/srtp-bench src/whep/srtp_bench.c
		qemu-arm /tmp/srtp-bench -t | tail -n 1 | grep -q "all ok" || { qemu-arm /tmp/srtp-bench -t; exit 1; }
		# item 35: STUN (RFC 5769 vectors), SDP and base64 of the WebRTC gateway on the instruction set of the camera
		arm-linux-gnueabi-gcc -O2 -Wall -Wextra -Werror -Wno-unused-function -static -march=armv5te -mtune=arm926ej-s -o /tmp/whep_test src/whep/whep_test.c
		qemu-arm /tmp/whep_test | grep -q "whep_test: all ok" || { qemu-arm /tmp/whep_test; exit 1; }
		make -C src/libakuio CROSS=arm-linux-gnueabi- >/tmp/make.log 2>&1 || { tail -30 /tmp/make.log; exit 1; }; grep -iE "warning" /tmp/make.log || true
		make -C src/tc100rtsp CROSS=arm-linux-gnueabi- >/tmp/make.log 2>&1 || { tail -30 /tmp/make.log; exit 1; }; grep -iE "warning" /tmp/make.log || true
		make -C src/mqttd CROSS=arm-linux-gnueabi- >/tmp/make.log 2>&1 || { tail -30 /tmp/make.log; exit 1; }; grep -iE "warning" /tmp/make.log || true
		make -C src/supervisord CROSS=arm-linux-gnueabi- >/tmp/make.log 2>&1 || { tail -30 /tmp/make.log; exit 1; }; grep -iE "warning" /tmp/make.log || true
		make -C src/onvifd CROSS=arm-linux-gnueabi- >/tmp/make.log 2>&1 || { tail -30 /tmp/make.log; exit 1; }; grep -iE "warning" /tmp/make.log || true
		make -C src/logfwd CROSS=arm-linux-gnueabi- >/tmp/make.log 2>&1 || { tail -30 /tmp/make.log; exit 1; }; grep -iE "warning" /tmp/make.log || true
		make -C src/netacl CROSS=arm-linux-gnueabi- >/tmp/make.log 2>&1 || { tail -30 /tmp/make.log; exit 1; }; grep -iE "warning" /tmp/make.log || true
		sh tests/check-libc-data-imports.sh	# rc27 R3: no libc variable through the stand-in libc
		test -s src/tc100rtsp/tc100_rtsp && test -s src/libakuio/libakuio.so && test -s src/mqttd/tc100-mqttd && test -s src/supervisord/tc100-supervisord && test -s src/onvifd/tc100-onvifd && test -s src/logfwd/tc100-logfwd && test -s src/netacl/libnetacl.so
		echo "httpfront (stripped, bytes): $(wc -c < /tmp/httpfront)"
		echo "tc100-mqttd (stripped, bytes): $(wc -c < src/mqttd/tc100-mqttd)"
		echo "tc100-supervisord (stripped, bytes): $(wc -c < src/supervisord/tc100-supervisord)"
		echo "tc100-onvifd (stripped, bytes): $(wc -c < src/onvifd/tc100-onvifd)"
		echo "tc100-logfwd (stripped, bytes): $(wc -c < src/logfwd/tc100-logfwd)"
		echo "libnetacl.so (stripped, bytes): $(wc -c < src/netacl/libnetacl.so)"
		make -C src/tc100rtsp test_rtsp >/dev/null 2>&1 && echo "host test build: ok"
		python3 -m unittest -v tests.test_httpfront_qemu tests.test_httpfront_native tests.test_uclibc_standin_qemu >/tmp/hf.log 2>&1 || { cat /tmp/hf.log; exit 1; }; grep -E "^(Ran|OK)|skipped" /tmp/hf.log
		echo "cross: ok"' || rc=1
}

run_whep() {
	echo "== item 35: tc100-whep against aiortc (mbedTLS 2.28.9 with DTLS-SRTP built in the container; needs network)"
	docker volume create tc100-whep >/dev/null
	docker run --rm -v "$SRC:/src:ro" -v tc100-whep:/tmp/whep-work python:3.12-bookworm sh -c 'cp -r /src /w && cd /w && sh tests/docker/whep-interop.sh' || rc=1
	docker run --rm -v "$SRC:/src:ro" alpine:3.20 sh /src/tests/docker/whep-musl.sh | tail -n 1 || rc=1
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
	whep) run_whep ;;
	all) run_tests; run_cross; run_kernel ;;
	*) echo "usage: $0 tests|cross|kernel|whep|all"; exit 2 ;;
esac
[ "$rc" = 0 ] && echo "== local CI: ok" || echo "== local CI: FAILED"
exit $rc
