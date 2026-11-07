# venctrace.so: preloaded into tc100_rtsp (LD_PRELOAD) on a test camera, see venctrace.c. Built like libakuio:
# loadable by the camera's uClibc loader (stand-in libc / libdl / libpthread made at link time, --hash-style=sysv).
CROSS ?= arm-linux-gnueabi-
CC = $(CROSS)gcc
CFLAGS ?= -O2 -Wall -Wextra -U_FORTIFY_SOURCE -fno-stack-protector -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft \
	-U_TIME_BITS -D_FILE_OFFSET_BITS=32 -U_LARGEFILE64_SOURCE

all: venctrace.so

venctrace.o: venctrace.c
	$(CC) $(CFLAGS) -fPIC -c $< -o $@

stubs: venctrace.o
	$(CROSS)nm -u venctrace.o | awk '$$1=="U" && $$2!~/^(_ITM|__gmon|__cxa|_GLOBAL_OFFSET|pthread_|dl)/ {print "void " $$2 "(void) {}"}' | sort -u > stub_c.c
	$(CROSS)nm -u venctrace.o | awk '$$1=="U" && $$2~/^dl/ {print "void " $$2 "(void) {}"}' | sort -u > stub_dl.c
	$(CROSS)nm -u venctrace.o | awk '$$1=="U" && $$2~/^pthread_/ {print "void " $$2 "(void) {}"}' | sort -u > stub_pthread.c
	touch stubs

venctrace.so: venctrace.o stubs
	$(CC) -shared -fPIC -nostdlib -o libc.so.0 -Wl,-soname,libc.so.0 stub_c.c
	$(CC) -shared -fPIC -nostdlib -o libdl.so.0 -Wl,-soname,libdl.so.0 stub_dl.c
	$(CC) -shared -fPIC -nostdlib -o libpthread.so.0 -Wl,-soname,libpthread.so.0 stub_pthread.c
	$(CC) -shared -nostdlib -Wl,--hash-style=sysv -Wl,-soname,venctrace.so -o venctrace.dbg.so venctrace.o \
		./libpthread.so.0 ./libdl.so.0 ./libc.so.0 $$($(CC) -print-libgcc-file-name)
	$(CROSS)strip --strip-unneeded -R .comment -o $@ venctrace.dbg.so

clean:
	rm -f *.o *.so *.so.0 stub_*.c stubs
