# Day watch of 2026-11-25, both cameras on 3.0.2-rc4 (tester)

IPCAM1 = the camera named .24 in the test queue, IPCAM2 = the .11. Both on 3.0.2-rc4 since 09:04 (IPCAM2) and
09:10 (IPCAM1), no SD card, no reboot since. One reading every 5 minutes from `/tmp/watch.sh` (kept in RAM, lost
at a reboot) plus the last line of `/tmp/logs/daynight.log`. Times are UTC on the camera (Paris = UTC+1).
Rows below are every 30 minutes; the full 5-minute series is in the tester's session notes, nothing in it differs.

| UTC | IPCAM2 luma | IPCAM2 ae | IPCAM2 MemAvailable kB | IPCAM1 luma | IPCAM1 ae | IPCAM1 MemAvailable kB |
|---|---|---|---|---|---|---|
| 09:35 | 90 | 30 | 17560 | 104 | 40 | 17688 |
| 10:05 | 105 | 41 | 17660 | 110 | 45 | 17512 |
| 10:35 | 95 | 30 | 17540 | 117 | 50 | 17516 |
| 11:05 | 86 | 28 | 17716 | 125 | 55 | 17524 |
| 11:15 | 96 | 34 | 17296 | 114 | 47 | 17552 |

Read:
- **Counters** `starts pic_fail enc_reopen cap_stall dq_err sub_off exit3` stay `1 0 0 0 0 0 0` on both cameras
  for the whole period (about 1 h 40 min of watch, the video server never restarted, same pid all the time).
- **Mode** `day` with source `vendor` all morning on both; no day/night flap, no backoff line.
- **Memory** flat inside +-250 kB on both (17.3 to 17.9 MB available); 2 h is far too short for the 0.4 MB/day trend
  question, three days are still needed.
- **Wi-Fi** `wifi-signal.avg` and the ping were fine; the `sig=` column of the script reads `-256` about half of the
  time on IPCAM1: that is the "no value" marker of `/proc/net/wireless` taken at the wrong instant, not a real
  signal drop (the same file read by hand gave -51 dBm), so ignore that column.
- **Script limit found:** the `cap=` and `bytes=` columns of the script are empty (the STAT lines are not in
  `/tmp/messages`, where the script looked). The bit rate is therefore not in this series; the evening report
  reads it from the video server log instead. Not a camera bug.

For the NIGHT-CEIL **relevé A** (gain and `lumi` by period) the useful source is the `daynight.log` of the night
24-25/11 already saved in `tc100-fix/night-2411/`. For the **relevé B** the plan is to run it tonight on IPCAM1
when the night bit rate has settled, in this order: three reads of `/tmp/cam_ae /tmp/cam_awb
/var/run/isp_tune.status` and the two `ak39_vi` parameters, 5 minutes of `STAT ... bytes`, the `grep` of the
parameter set lines in `/tmp/logs/tc100_rtsp.log`, then `controlscripts/rtsp-h26x restart` and the same again.
