# Programs of the 3.0 system built against musl 1.2.6, the C library of the camera's base system (Buildroot 2025.02,
# /lib/ld-musl-arm.so.1 -> /lib/libc.so): real headers, linked dynamically against the camera's own libc. Replaces the
# stand-in libc technique (uClibc loader of the vendor runtime) for tc100-mqttd, -onvifd, -supervisord, -logfwd and
# rwconf on 2026-11-07: no vendor library in these processes any more, and no glibc-only names (__isoc99_sscanf...)
# can reach the camera. The sysroot comes from v3/musl/build-musl.sh (build/musl by default).
CROSS ?= arm-linux-gnueabi-
MUSL ?= $(abspath $(dir $(lastword $(MAKEFILE_LIST)))../build/musl)
MUSL_CC = REALGCC=$(CROSS)gcc $(MUSL)/bin/musl-gcc
# Hardening ([harden], 2026-11-23; docs/linux-port/flash-budget.md "Hardening"): a stack canary in every function with a
# local array or an address-taken local (musl 1.2.6 has __stack_chk_fail and __stack_chk_guard, set from AT_RANDOM by
# its loader), and full RELRO (-z now puts the GOT in the segment the musl loader makes read-only after relocation; musl
# binds every symbol at load anyway). About +3.7 KB in the xz squashfs for all the free programs. HARDEN=0 (make
# argument or environment) builds as before. _FORTIFY_SOURCE stays off: musl has no fortified headers (it would change
# nothing), and PIE is not used (+8 KB xz, slower code on the ARM926).
HARDEN ?= 1
ifeq ($(HARDEN),0)
HARDEN_CFLAGS = -fno-stack-protector
HARDEN_LDFLAGS =
else
HARDEN_CFLAGS = -fstack-protector-strong
HARDEN_LDFLAGS = -Wl,-z,relro,-z,now
endif
MUSL_CFLAGS ?= -Os -Wall -Wextra -std=gnu11 -fno-pie $(HARDEN_CFLAGS) -U_FORTIFY_SOURCE -march=armv5te -mtune=arm926ej-s \
	-mfloat-abi=soft -ffunction-sections -fdata-sections
MUSL_LDFLAGS ?= -no-pie -Wl,--gc-sections -Wl,--dynamic-linker=/lib/ld-musl-arm.so.1 -Wl,--hash-style=both $(HARDEN_LDFLAGS)

$(MUSL)/bin/musl-gcc:
	@echo "no musl sysroot in $(MUSL): run v3/musl/build-musl.sh first" >&2; exit 1
