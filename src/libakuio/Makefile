# libakuio: free replacement for the vendor library (see libakuio.c)
CROSS ?= arm-linux-gnueabi-
CC = $(CROSS)gcc
CFLAGS ?= -O2 -Wall -Wextra
LIB = libakuio.so

all: $(LIB)

$(LIB): libakuio.c ak39_venc.h
	$(CC) $(CFLAGS) -fPIC -shared -Wl,-soname,libakuio.so -I. $< -o $@ -lpthread

# host test of the allocator (no device needed)
selftest: libakuio.c selftest.c ak39_venc.h
	gcc -Wall -Wextra -O2 -DAKUIO_SELFTEST -I. libakuio.c selftest.c -o selftest.bin -lpthread
	./selftest.bin

clean:
	rm -f $(LIB) selftest.bin
