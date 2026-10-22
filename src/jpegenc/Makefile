# jpegenc: free JPEG encoder for the AK3918EV300 hardware JPEG core (see README.md)
CROSS ?= arm-linux-gnueabi-
CFLAGS ?= -O2 -Wall -Wextra

all: jpegenc

# for the camera (static, runs on the vendor-libc-free 6.6 user space as well)
jpegenc: jpegenc.c jpeg_std_tables.h ../libakuio/ak39_venc.h
	$(CROSS)gcc $(CFLAGS) -static jpegenc.c -o $@

# host build without the device code: dry run only
jpegenc.host: jpegenc.c jpeg_std_tables.h
	gcc $(CFLAGS) -DJPEGENC_NO_DEVICE jpegenc.c -o $@

jpeg_std_tables.h: gen_tables_h.py jpeg_hw_tables.py
	python3 gen_tables_h.py

clean:
	rm -f jpegenc jpegenc.host
