# rwconf: a program of the 3.0 system, built against musl 1.2.4, the C library of the camera's base system (see
# src/musl.mk; sysroot from v3/musl/build-musl.sh). Until 2026-11-07 it ran under the vendor uClibc loader with a
# stand-in libc made at link time.
all: rwconf
include ../musl.mk

rwconf.dbg: rwconf.c Makefile ../musl.mk | $(MUSL)/bin/musl-gcc
	$(MUSL_CC) $(MUSL_CFLAGS) $(MUSL_LDFLAGS) rwconf.c -o $@

rwconf: rwconf.dbg
	$(CROSS)strip --strip-unneeded -R .comment -o $@ $<

# host build for tests/test_rwconf.py (gcc of the build host)
host: rwconf.c
	$(CC) -O1 -Wall -Wextra -std=gnu11 -o rwconf-host rwconf.c

clean:
	rm -f rwconf rwconf.dbg rwconf-host *.o stubs.c defined.txt imports.txt libc.so.0
