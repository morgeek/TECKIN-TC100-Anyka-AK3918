# tc100_rtsp: runs under the uClibc loader of the camera (vendor libs), built with the glibc cross compiler.
# What keeps it loadable by uClibc: no fortify / stack protector / time64 / C2x redirects, and NEEDED =
# libpthread.so.0, libc.so.0 and libdl.so.0 (stand-ins that define every imported name, made at link time) instead of
# libc.so.6. The imports then resolve by name against the real uClibc at run time. libpthread.so.0 comes first: the
# uClibc libc.so.0 carries do-nothing pthread_* fallbacks, the real ones must be found before them. libpthread is
# already in the process anyway (libakuio.so needs it); the recorder's card writer (rec.c) is a thread.
CROSS ?= arm-linux-gnueabi-
SYSROOT ?= /usr/arm-linux-gnueabi
CFLAGS ?= -I../jpegenc -O2 -Wall -std=gnu11 -U_FORTIFY_SOURCE -fno-stack-protector -fno-pie -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft \
	-U_TIME_BITS -D_FILE_OFFSET_BITS=32 -U_LARGEFILE64_SOURCE
OBJS = tc100_rtsp.o rec.o mp4box.o livemp4.o talk.o alisten.o

all: tc100_rtsp

tc100_rtsp.o: tc100_rtsp.c rec.h util.h talk.h alisten.h livemp4.h
	$(CROSS)gcc $(CFLAGS) -c tc100_rtsp.c -o $@

talk.o: talk.c talk.h
	$(CROSS)gcc $(CFLAGS) -Os -c talk.c -o $@

alisten.o: alisten.c alisten.h
	$(CROSS)gcc $(CFLAGS) -Os -c alisten.c -o $@

mp4box.o: mp4box.c mp4box.h
	$(CROSS)gcc $(CFLAGS) -Os -c mp4box.c -o $@

livemp4.o: livemp4.c livemp4.h mp4box.h
	$(CROSS)gcc $(CFLAGS) -Os -c livemp4.c -o $@

rec.o: rec.c rec.h mp4box.h	# card I/O bound: -Os keeps the binary small (the flash stack has a size budget)
	$(CROSS)gcc $(CFLAGS) -Os -c rec.c -o $@

defined.txt: $(OBJS)
	$(CROSS)nm -g --defined-only $(OBJS) | awk 'NF == 3 {print $$3}' | sort -u > $@

imports.txt: $(OBJS) defined.txt Makefile
	{ $(CROSS)nm -u $(OBJS); echo 'U __uClibc_main'; echo 'U abort'; } | \
		awk '$$1=="U" && $$2!~/^(__gmon|__aeabi|_GLOBAL_OFFSET|main$$)/ {print $$2}' | sort -u | grep -vxF -f defined.txt > $@

stubs.c: imports.txt
	grep -v '^pthread_' imports.txt | awk '{print "void " $$1 "(void) {}"}' > $@; \
		for x in raise abort; do grep -q "void $$x(" $@ || echo "void $$x(void) {}" >> $@; done

stub_pthread.c: imports.txt
	grep '^pthread_' imports.txt | awk '{print "void " $$1 "(void) {}"}' > $@

libc.so.0: stubs.c
	$(CROSS)gcc -shared -nostdlib -Wl,-soname,libc.so.0 -o $@ stubs.c

libpthread.so.0: stub_pthread.c
	$(CROSS)gcc -shared -nostdlib -Wl,-soname,libpthread.so.0 -o $@ stub_pthread.c

libdl.so.0: dummy.c
	$(CROSS)gcc -shared -nostdlib -Wl,-soname,libdl.so.0 -o $@ dummy.c

start.o: start.S
	$(CROSS)gcc -march=armv5te -c start.S -o $@

# The camera copies it to /tmp (RAM): the symbol table stays out of it, in tc100_rtsp.dbg (CI symbols artifact).
tc100_rtsp: tc100_rtsp.dbg
	$(CROSS)strip --strip-unneeded -R .comment -o $@ $<

tc100_rtsp.dbg: start.o $(OBJS) libpthread.so.0 libc.so.0 libdl.so.0
	$(CROSS)gcc -nostdlib -no-pie -Wl,--dynamic-linker=/lib/ld-uClibc.so.0 -Wl,--hash-style=sysv -Wl,--no-as-needed \
		-nostartfiles -o $@ start.o $(OBJS) -L. -l:libpthread.so.0 -l:libc.so.0 -l:libdl.so.0 \
		$$($(CROSS)gcc -print-libgcc-file-name)

# host tests of the pure parts (util.h, rec.c): gcc of the build host, no camera needed
test: test_util test_rec test_livemp4 test_rtsp
	./test_util

# the whole server without camera and encoder (RTSP, audio, backchannel, listeners): tests/test_tc100rtsp.py runs it
test_rtsp: tc100_rtsp.c rec.c mp4box.c livemp4.c talk.c alisten.c rec.h mp4box.h livemp4.h talk.h alisten.h util.h
	gcc -O1 -Wall -Wno-unused -std=gnu11 -DTC100_HOST_TEST -DCONF='"conf/"' -I../jpegenc -o $@ tc100_rtsp.c rec.c mp4box.c livemp4.c talk.c alisten.c -ldl -lpthread -lm

test_util: test_util.c util.h
	gcc -O2 -Wall -Wextra -o $@ test_util.c -lm

test_rec: test_rec.c rec.c rec.h mp4box.c mp4box.h
	gcc -O2 -Wall -Wextra -DREC_HOST_TEST -o $@ test_rec.c rec.c mp4box.c -lpthread -lm

# the live muxer alone: frames in, the fMP4 a browser gets out of a FIFO (tests/test_tc100rtsp.py checks it)
test_livemp4: test_livemp4.c livemp4.c livemp4.h mp4box.c mp4box.h
	gcc -O2 -Wall -Wextra -o $@ test_livemp4.c livemp4.c mp4box.c

clean:
	rm -f tc100_rtsp tc100_rtsp.dbg *.o stubs.c stub_pthread.c defined.txt imports.txt libc.so.0 libpthread.so.0 libdl.so.0 test_util test_rec test_livemp4 test_rtsp
