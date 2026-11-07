# Programs of the 3.0 system built against musl 1.2.4, the C library of the camera's base system (Buildroot 2024.02,
# /lib/ld-musl-arm.so.1 -> /lib/libc.so): real headers, linked dynamically against the camera's own libc. Replaces the
# stand-in libc technique (uClibc loader of the vendor runtime) for tc100-mqttd, -onvifd, -supervisord, -logfwd and
# rwconf on 2026-11-07: no vendor library in these processes any more, and no glibc-only names (__isoc99_sscanf...)
# can reach the camera. The sysroot comes from v3/musl/build-musl.sh (build/musl by default).
CROSS ?= arm-linux-gnueabi-
MUSL ?= $(abspath $(dir $(lastword $(MAKEFILE_LIST)))../build/musl)
MUSL_CC = REALGCC=$(CROSS)gcc $(MUSL)/bin/musl-gcc
MUSL_CFLAGS ?= -Os -Wall -Wextra -std=gnu11 -fno-pie -fno-stack-protector -U_FORTIFY_SOURCE -march=armv5te -mtune=arm926ej-s \
	-mfloat-abi=soft -ffunction-sections -fdata-sections
MUSL_LDFLAGS ?= -no-pie -Wl,--gc-sections -Wl,--dynamic-linker=/lib/ld-musl-arm.so.1 -Wl,--hash-style=both

$(MUSL)/bin/musl-gcc:
	@echo "no musl sysroot in $(MUSL): run v3/musl/build-musl.sh first" >&2; exit 1
