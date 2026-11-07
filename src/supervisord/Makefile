# tc100-supervisord: a program of the 3.0 system, built against musl 1.2.4, the C library of the camera's base system (see
# src/musl.mk; sysroot from v3/musl/build-musl.sh). Until 2026-11-07 it ran under the vendor uClibc loader with a
# stand-in libc made at link time.
all: tc100-supervisord
include ../musl.mk

tc100-supervisord.dbg: supervisord.c Makefile ../musl.mk | $(MUSL)/bin/musl-gcc
	$(MUSL_CC) $(MUSL_CFLAGS) $(MUSL_LDFLAGS) supervisord.c -o $@

tc100-supervisord: tc100-supervisord.dbg
	$(CROSS)strip --strip-unneeded -R .comment -o $@ $<

# host build for tests/test_supervisord.py (gcc of the build host)
host: supervisord.c
	$(CC) -O1 -Wall -Wextra -std=gnu11 -o tc100-supervisord-host supervisord.c

clean:
	rm -f tc100-supervisord tc100-supervisord.dbg tc100-supervisord-host *.o stubs.c defined.txt imports.txt libc.so.0
