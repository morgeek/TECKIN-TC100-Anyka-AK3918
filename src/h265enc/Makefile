# h265enc: one IDR picture on the encoder core without the vendor libraries (step 2 of the free encoder, see README.md)
CROSS ?= arm-linux-gnueabi-
CFLAGS ?= -O2 -Wall -Wextra -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft

all: h265enc

h265enc: h265enc.c ../libakuio/ak39_venc.h
	$(CROSS)gcc $(CFLAGS) -static -s h265enc.c -o $@

# host build for tests/test_h265cmdlist.py (dry run only)
host: h265enc.c
	$(CC) -O1 -Wall -Wextra -DH265ENC_NO_DEVICE -o h265enc-host h265enc.c

clean:
	rm -f h265enc h265enc-host
