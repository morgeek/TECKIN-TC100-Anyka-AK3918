#!/bin/sh
# build-slim-stack.sh <sd-stack.tar> <out.sqfs>
# Builds the light squashfs (xz) of the user space that today lives on the SD card, for the SPI flash.
# Input: tar of the SD card content (www scripts controlscripts bin lib v3 VERSION tc100test/{tc100_rtsp,libakuio.so,httpfront,rtsp-launch.sh}).
# Keeps only what the running system really loads (checked with /proc/*/maps on the camera) and what the scripts call.
# Left out on purpose (kept as optional extras on the SD card): curl + libcurl/libssl/libcrypto (2 MiB packed; Telegram, update check).
set -e
TAR=$1; OUT=$2; W=$(mktemp -d); trap 'rm -rf $W' EXIT
mkdir $W/in $W/out; tar xf "$TAR" -C $W/in; cd $W/in; find . -name '._*' -delete
O=$W/out; mkdir -p $O/bin $O/lib $O/tc100test
cp -a www scripts controlscripts v3 VERSION $O/
find $O -name '*.bak*' -o -name '*.orig' -o -name '*.v5bak' -o -name '*.vendor' | xargs rm -f
for b in busybox ffmpeg-min-recorder getflag getimage jq min-recorder-list monvifd rwconf setconf swapon_zram tc100-logfwd telegram tinymix wpa_supplicant; do cp -a bin/$b $O/bin/; done
for l in ld-uClibc-0.9.33.2.so libc.so.0 libuClibc-0.9.33.2.so libdl.so.0 libm.so.0 libpthread.so.0 librt.so.0 libgcc_s.so.1 \
         libcrypt.so.0 libstdc++.so.6.0.19 libakv_encode.so libmpi_venc_ex.so libplat_common.so libplat_drv.so libplat_ipcsrv.so \
         libplat_thread.so libplat_venc_cb.so libwolfmqtt.so.5 libzbar.so.0 libtc100fix.so; do cp -a lib/$l $O/lib/; done
ln -sf libstdc++.so.6.0.19 $O/lib/libstdc++.so.6
cp -a tc100test/tc100_rtsp tc100test/libakuio.so tc100test/httpfront tc100test/rtsp-launch.sh $O/tc100test/
mksquashfs $O "$OUT" -comp xz -b 256K -noappend -quiet
ls -l "$OUT"
