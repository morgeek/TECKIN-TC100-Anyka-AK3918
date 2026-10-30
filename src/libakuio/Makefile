# libakuio: free replacement for the vendor library (see libakuio.c)
#
# It is loaded by the uClibc programs of the camera (vendor libs), so it is built to be loadable there:
# no fortify / stack protector / time64, and NEEDED = libc.so.0 and libpthread.so.0 (empty-looking stand-ins that
# define the imported names, made at link time) instead of the glibc libc.so.6. Imports resolve by name at run time.
# --hash-style=sysv: the uClibc dynamic loader does not know DT_GNU_HASH.
CROSS ?= arm-linux-gnueabi-
CC = $(CROSS)gcc
CFLAGS ?= -O2 -Wall -Wextra -U_FORTIFY_SOURCE -fno-stack-protector -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft \
	-U_TIME_BITS -D_FILE_OFFSET_BITS=32 -U_LARGEFILE64_SOURCE
LIB = libakuio.so

all: $(LIB)

libakuio.o: libakuio.c ak39_venc.h
	$(CC) $(CFLAGS) -fPIC -I. -c $< -o $@

stub_libc.c: libakuio.o
	$(CROSS)nm -u libakuio.o | awk '$$1=="U" && $$2!~/^(_ITM|__gmon|__cxa|_GLOBAL_OFFSET|pthread_)/ {print $$2}' | sort -u | \
		awk '$$1=="stderr" {print "void *stderr;"; next} {print "void " $$1 "(void) {}"}' > $@

stub_pthread.c: libakuio.o
	$(CROSS)nm -u libakuio.o | awk '$$1=="U" && $$2~/^pthread_/ {print "void " $$2 "(void) {}"}' | sort -u > $@

libc.so.0: stub_libc.c
	$(CC) -shared -nostdlib -Wl,-soname,libc.so.0 -o $@ $<

libpthread.so.0: stub_pthread.c
	$(CC) -shared -nostdlib -Wl,-soname,libpthread.so.0 -o $@ $<

# loaded into RAM (/tmp) on the camera: shipped stripped, the symbols stay in libakuio.dbg.so
$(LIB): libakuio.dbg.so
	$(CROSS)strip --strip-unneeded -R .comment -o $@ $<

libakuio.dbg.so: libakuio.o libc.so.0 libpthread.so.0
	$(CC) -shared -nostdlib -Wl,-soname,libakuio.so -Wl,--hash-style=sysv -Wl,--no-as-needed libakuio.o -L. -l:libc.so.0 -l:libpthread.so.0 \
		$$($(CC) -print-libgcc-file-name) -o $@

# host test of the allocator (no device needed)
selftest: libakuio.c selftest.c ak39_venc.h
	gcc -Wall -Wextra -O2 -DAKUIO_SELFTEST -I. libakuio.c selftest.c -o selftest.bin -lpthread
	./selftest.bin

clean:
	rm -f $(LIB) libakuio.dbg.so *.o stub_*.c libc.so.0 libpthread.so.0 selftest.bin
