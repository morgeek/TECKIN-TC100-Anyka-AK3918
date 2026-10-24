# Linux 6.6 SD-boot stack: glue for the vendor web UI (2.1.9 stack, commit 7fe58d5 on the card)

The card carries the 2.1.9 web UI and its CGIs. They assume the original firmware (card on /mnt, vendor RTSP server
`rtsp-h26x`, flash boot). These files adapt them to the free stack (tc100_rtsp). Copy to the card:

| file | goes to | why |
|---|---|---|
| `rtsp-launch.sh` | `tc100test/rtsp-launch.sh` | starts tc100_rtsp from `config/rtspserver.conf` (codec, bit rate, port) and applies the mic gain (Audio page -> codec "LineIn Capture Volume"); used by the boot script and the shim |
| `rtsp-h26x` | `controlscripts/rtsp-h26x` | shim: start/stop/restart/status/health for tc100_rtsp, so Services and the "Apply" buttons of Flux vidéo work (never leave the vendor script in `controlscripts/`) |
| `sdinfo-sd.sh` | `scripts/sdinfo-sd.sh` | writes `/tmp/sd-card` for the SD-card panel |

One-time `sed` patches of the card's CGIs (card is mounted twice, at `/mnt` and `/mnt/sd`, so `df -k /mnt` reports
`/mnt/sd`):
- `www/cgi-bin/state.cgi`: `/mnt|/mnt/)` -> `/mnt|/mnt/|/mnt/sd)`
- `www/cgi-bin/viewrecords.cgi`: `case "$_mp" in /mnt|/mnt/)` -> add `|/mnt/sd`
- `www/cgi-bin/disk.cgi`: `$NF=="/mnt"` -> `($NF=="/mnt"||$NF=="/mnt/sd")`
- `www/cgi-bin/action.cgi`, first line of the `sd_card_info)` handler: `[ -f /tmp/tc100-storage ] || sh /mnt/scripts/sdinfo-sd.sh >/dev/null 2>&1`

Not available on this stack (they live in the vendor RTSP server / ISP daemon): live image tuning, privacy masks,
black-and-white switch (`setconf`), motion detection inside the stream, local MP4 backup recording (REC_LOCAL),
resolution/fps of the Flux vidéo page (tc100_rtsp is 1080p, 15 fps nominal).

Also: `www/settings.html` of the card: `cmd=wifi_get_ssid&_=` -> `cmd=wifi_get_ssid&format=json&_=` (the CGI appends `<hr/>` to
non-JSON requests, which broke `r.json()` and showed "Read error" under Réseau).
