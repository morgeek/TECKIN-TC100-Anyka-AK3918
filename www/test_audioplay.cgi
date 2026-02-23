#!/bin/sh
echo "Content-type: text/plain"
echo ""
echo "test start"
/usr/bin/audioplay /mnt/media/police.wav 100 2>&1
echo "test end"
