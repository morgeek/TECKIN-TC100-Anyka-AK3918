# tc100-logfwd: runs under the uClibc loader of the camera, built with the glibc cross compiler, exactly like
# src/mqttd and src/tc100rtsp (same start.S, same stand-in libc made at link time: see the comments in
# src/tc100rtsp/Makefile). No libc variable may be imported (tests/check-libc-data-imports.sh): the source has its own
# option loop and writes errors with write(2).
CROSS ?= arm-linux-gnueabi-
CFLAGS ?= -Os -Wall -Wextra -std=gnu11 -U_FORTIFY_SOURCE -fno-stack-protector -fno-pie -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft \
	-U_TIME_BITS -D_FILE_OFFSET_BITS=32 -U_LARGEFILE64_SOURCE
TR = ../tc100rtsp

all: tc100-logfwd

tc100-logfwd.o: tc100-logfwd.c
	$(CROSS)gcc $(CFLAGS) -c tc100-logfwd.c -o $@

defined.txt: tc100-logfwd.o
	$(CROSS)nm -g --defined-only tc100-logfwd.o | awk 'NF == 3 {print $$3}' | sort -u > $@

imports.txt: tc100-logfwd.o defined.txt Makefile
	{ $(CROSS)nm -u tc100-logfwd.o; echo 'U __uClibc_main'; echo 'U abort'; } | \
		awk '$$1=="U" && $$2!~/^(__gmon|__aeabi|_GLOBAL_OFFSET|main$$)/ {print $$2}' | sort -u | grep -vxF -f defined.txt > $@

stubs.c: imports.txt
	awk '{print "void " $$1 "(void) {}"}' imports.txt > $@; \
		for x in raise abort; do grep -q "void $$x(" $@ || echo "void $$x(void) {}" >> $@; done

libc.so.0: stubs.c
	$(CROSS)gcc -shared -nostdlib -Wl,-soname,libc.so.0 -o $@ stubs.c

start.o: $(TR)/start.S
	$(CROSS)gcc -march=armv5te -c $(TR)/start.S -o $@

tc100-logfwd.dbg: start.o tc100-logfwd.o libc.so.0
	$(CROSS)gcc -nostdlib -no-pie -Wl,--dynamic-linker=/lib/ld-uClibc.so.0 -Wl,--hash-style=sysv -Wl,--no-as-needed \
		-nostartfiles -o $@ start.o tc100-logfwd.o -L. -l:libc.so.0 $$($(CROSS)gcc -print-libgcc-file-name)

tc100-logfwd: tc100-logfwd.dbg
	$(CROSS)strip --strip-unneeded -R .comment -o $@ $<

clean:
	rm -f tc100-logfwd tc100-logfwd.dbg *.o stubs.c defined.txt imports.txt libc.so.0
