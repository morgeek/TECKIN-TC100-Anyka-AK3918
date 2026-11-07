# h265enc: one IDR picture on the encoder core without the vendor libraries (step 2 of the free encoder, see README.md)
CROSS ?= arm-linux-gnueabi-
CFLAGS ?= -O2 -Wall -Wextra -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft

all: h265enc h265live

h265enc: h265enc.c ../libakuio/ak39_venc.h
	$(CROSS)gcc $(CFLAGS) -static -s h265enc.c -o $@

# host build for tests/test_h265cmdlist.py (dry run only)
host: h265enc.c
	$(CC) -O1 -Wall -Wextra -DH265ENC_NO_DEVICE -o h265enc-host h265enc.c

clean:
	rm -f h265enc h265enc-host h265live h265live-host

h265live: h265live.c slicehdr.h paramsets.h listgen.h worktab.h rc.h ../libakuio/ak39_venc.h
	$(CROSS)gcc $(CFLAGS) -static -s h265live.c -o $@ -lm

live-host: h265live.c slicehdr.h
	$(CC) -O1 -Wall -Wextra -DH265LIVE_NO_DEVICE -o h265live-host h265live.c -lm
