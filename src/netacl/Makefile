# libnetacl.so: a shared object preloaded (LD_PRELOAD) into the uClibc programs of the camera (busybox telnetd/ftpd),
# built with the glibc cross compiler like the programs of src/mqttd and src/tc100rtsp: same stand-in libc made at link
# time. The library has DT_NEEDED libdl.so.0 and libc.so.0 (the sonames uClibc has), so every import resolves by name
# against the real uClibc at run time. The stand-ins are never installed; they only exist for the link.
#   - It defines accept, accept4 and bind itself: they are left out of the stand-ins (defined.txt), and the loader finds
#     ours first because LD_PRELOAD puts the library before libc.
#   - dlsym(RTLD_NEXT, ...) is the call that matters: RTLD_NEXT is ((void *) -1) in uClibc as in glibc, and dlsym is
#     imported from libdl.so.0 (the dl* names go to that stand-in, the rest to libc.so.0).
#   - libgcc helpers (__bswapsi2 for htonl on armv5) are linked in statically from libgcc.a: uClibc does not export them,
#     and the stand-in must not define them (found by tests/test_uclibc_standin_qemu.py).
#   - No libc variable may be imported (tests/check-libc-data-imports.sh).
CROSS ?= arm-linux-gnueabi-
CFLAGS ?= -Os -Wall -Wextra -std=gnu11 -fPIC -U_FORTIFY_SOURCE -fno-stack-protector -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft \
	-U_TIME_BITS -D_FILE_OFFSET_BITS=32 -U_LARGEFILE64_SOURCE

all: libnetacl.so

# The same filter for the musl programs of the 3.0 base system (its busybox telnetd/ftpd: the uClibc build above is never
# preloaded there, netacl_exec checks the loader). Built against musl 1.2.4 (src/musl.mk), the camera's libc.
musl: libnetacl-musl.so

include ../musl.mk

libnetacl-musl.dbg.so: netacl.c netacl.h Makefile ../musl.mk | $(MUSL)/bin/musl-gcc
	$(MUSL_CC) $(filter-out -fno-pie,$(MUSL_CFLAGS)) -fPIC -shared -Wl,-soname,libnetacl.so -Wl,--hash-style=both -o $@ netacl.c

libnetacl-musl.so: libnetacl-musl.dbg.so
	$(CROSS)strip --strip-unneeded -R .comment -o $@ $<

netacl.o: netacl.c netacl.h
	$(CROSS)gcc $(CFLAGS) -c netacl.c -o $@

defined.txt: netacl.o
	$(CROSS)nm -g --defined-only netacl.o | awk 'NF == 3 {print $$3}' | sort -u > $@

imports.txt: netacl.o defined.txt Makefile
	$(CROSS)nm -u netacl.o | \
		awk '$$1=="U" && $$2!~/^(__gmon|__aeabi|__bswap|_GLOBAL_OFFSET)/ {print $$2}' | sort -u | grep -vxF -f defined.txt > $@

stubs.c: imports.txt
	grep -v '^dl' imports.txt | awk '{print "void " $$1 "(void) {}"}' > $@
	echo 'void abort(void) {}' >> $@

stub_dl.c: imports.txt
	grep '^dl' imports.txt | awk '{print "void " $$1 "(void) {}"}' > $@

libc.so.0: stubs.c
	$(CROSS)gcc -shared -nostdlib -Wl,-soname,libc.so.0 -o $@ stubs.c

libdl.so.0: stub_dl.c
	$(CROSS)gcc -shared -nostdlib -Wl,-soname,libdl.so.0 -o $@ stub_dl.c

libnetacl.dbg.so: netacl.o libc.so.0 libdl.so.0
	$(CROSS)gcc -shared -nostdlib -Wl,-soname,libnetacl.so -Wl,--hash-style=sysv -Wl,--no-as-needed \
		-o $@ netacl.o -L. -l:libdl.so.0 -l:libc.so.0 \
		$$($(CROSS)gcc -print-libgcc-file-name)

libnetacl.so: libnetacl.dbg.so
	$(CROSS)strip --strip-unneeded -R .comment -o $@ $<

clean:
	rm -f libnetacl.so libnetacl.dbg.so libnetacl-musl.so libnetacl-musl.dbg.so *.o stubs.c stub_dl.c defined.txt imports.txt libc.so.0 libdl.so.0
