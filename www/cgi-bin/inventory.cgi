#!/bin/sh
# inventory.cgi : read-only hardware inventory of this camera (v3/install/inventory.sh, made at each start) and the
# board profile it matched, as plain text to paste in a GitHub issue "Hardware inventory". ?full=1 adds the md5 of
# U-Boot (reads 228 KiB of the slow flash: about 15 s).
echo "Content-type: text/plain"; echo "Cache-Control: no-store"; echo ""
I=/mnt/v3/install
case "$QUERY_STRING" in
	*full=1*) sh $I/inventory.sh > /tmp/inventory-full.txt 2>/dev/null; F=/tmp/inventory-full.txt ;;
	*) [ -s /tmp/inventory.txt ] || sh $I/inventory.sh --quick > /tmp/inventory.txt 2>/dev/null; F=/tmp/inventory.txt ;;
esac
echo "# board check: $(HWCHECK_FLASH_ID=1 sh $I/hwcheck.sh $F /mnt/v3/board 2>/dev/null)"
cat $F
