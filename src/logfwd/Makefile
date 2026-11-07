# tc100-logfwd: a program of the 3.0 system, built against musl 1.2.4, the C library of the camera's base system (see
# src/musl.mk; sysroot from v3/musl/build-musl.sh). Until 2026-11-07 it ran under the vendor uClibc loader with a
# stand-in libc made at link time.
all: tc100-logfwd
include ../musl.mk

tc100-logfwd.dbg: tc100-logfwd.c Makefile ../musl.mk | $(MUSL)/bin/musl-gcc
	$(MUSL_CC) $(MUSL_CFLAGS) $(MUSL_LDFLAGS) tc100-logfwd.c -o $@

tc100-logfwd: tc100-logfwd.dbg
	$(CROSS)strip --strip-unneeded -R .comment -o $@ $<

clean:
	rm -f tc100-logfwd tc100-logfwd.dbg tc100-logfwd-host *.o stubs.c defined.txt imports.txt libc.so.0
