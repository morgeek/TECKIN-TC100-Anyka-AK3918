#!/bin/sh
echo "Content-type: text/plain"
echo ""

# The browser sends pure audio/webm bytes in the POST body.
# Lighttpd automatically pipes POST payload to stdin.
cat > /tmp/pttaudio.webm

if [ -s /tmp/pttaudio.webm ]; then
    # Convert webm to 8000Hz mono PCM wav
    /mnt/bin/ffmpeg-min-recorder -i /tmp/pttaudio.webm -acodec pcm_s16le -ar 8000 -ac 1 /tmp/pttaudio.wav -y >/dev/null 2>&1
    
    if [ -s /tmp/pttaudio.wav ]; then
        # kill previous audioplay if running to prevent overlapping yells
        killall audioplay >/dev/null 2>&1
        /usr/bin/audioplay /tmp/pttaudio.wav 100 >/dev/null 2>&1 &
        # Delete the webm immediately as it's no longer needed
        rm -f /tmp/pttaudio.webm
        # Delete the wav after a short delay to ensure audioplay has started reading it
        (sleep 2; rm -f /tmp/pttaudio.wav) &
        echo "OK"
    else
        rm -f /tmp/pttaudio.webm
        echo "Error: conversion failed"
    fi
else
    echo "Error: empty input"
fi
