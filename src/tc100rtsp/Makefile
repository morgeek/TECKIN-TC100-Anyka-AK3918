# tc100_rtsp: runs under the uClibc loader of the camera (vendor libs), built with the glibc cross compiler.
# What keeps it loadable by uClibc: no fortify / stack protector / time64 / C2x redirects, and NEEDED = libc.so.0 and
# libdl.so.0 (stand-ins that define every imported name, made at link time) instead of libc.so.6.
# The imports then resolve by name against the real uClibc at run time.
CROSS ?= arm-linux-gnueabi-
SYSROOT ?= /usr/arm-linux-gnueabi
CFLAGS ?= -O2 -Wall -std=gnu11 -U_FORTIFY_SOURCE -fno-stack-protector -fno-pie -march=armv5te -mfloat-abi=soft \
	-U_TIME_BITS -D_FILE_OFFSET_BITS=32 -U_LARGEFILE64_SOURCE

all: tc100_rtsp

tc100_rtsp.o: tc100_rtsp.c
	$(CROSS)gcc $(CFLAGS) -c tc100_rtsp.c -o $@

stubs.c: tc100_rtsp.o Makefile
	{ $(CROSS)nm -u tc100_rtsp.o; echo 'U __uClibc_main'; echo 'U abort'; } | awk '$$1=="U" && $$2!~/^(__gmon|__aeabi|_GLOBAL_OFFSET|main$$)/ {print "void " $$2 "(void) {}"}' | sort -u > $@; for x in raise abort; do grep -q "void $$x(" $@ || echo "void $$x(void) {}" >> $@; done

libc.so.0: stubs.c
	$(CROSS)gcc -shared -nostdlib -Wl,-soname,libc.so.0 -o $@ stubs.c

libdl.so.0: dummy.c
	$(CROSS)gcc -shared -nostdlib -Wl,-soname,libdl.so.0 -o $@ dummy.c

start.o: start.S
	$(CROSS)gcc -march=armv5te -c start.S -o $@

tc100_rtsp: start.o tc100_rtsp.o libc.so.0 libdl.so.0
	$(CROSS)gcc -nostdlib -no-pie -Wl,--dynamic-linker=/lib/ld-uClibc.so.0 -Wl,--hash-style=sysv -Wl,--no-as-needed \
		-nostartfiles -o $@ start.o tc100_rtsp.o -L. -l:libc.so.0 -l:libdl.so.0 \
		$$($(CROSS)gcc -print-libgcc-file-name)

clean:
	rm -f tc100_rtsp *.o stubs.c libc.so.0 libdl.so.0
