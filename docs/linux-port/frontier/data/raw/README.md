# Raw measurements behind the frontier data summaries

Read-only captures from the two test cameras (.11 and .24); times are UTC. The summaries one level up are what the
briefs carry; these files let anyone check a number against its source.

| file | what | summary |
|---|---|---|
| `daynight-{11,24}-2026-11-12.log` | supervisor day / night log, one line per 5 min (`mode src luma ae[...] idx lum awb[10] rex bex u v`) | `../daynight-2026-11-12.md` |
| `dn-capture-24-vendor-2026-11-12.csv` | .24 every 5 s from 18:10 to 07:05: `time luma \| cam_ae \| ircut` (1 = filter in, day) | `../daynight-2026-11-12.md` |
| `perfcap-{11,24}-2026-11-11.txt` | 25 samples 5 min apart: meminfo, /proc/stat, per process PSS / utime / stime / minor faults; two bursts of new processes | `../background-2026-11-11.md`, `../rtsp-2026-11-11.md` |
| `threads-{11,24}-2026-11-11.txt` | tc100_rtsp per thread, two reads 60 s apart (3.0.0) | `../rtsp-2026-11-11.md` |
| `stat-{11,24}-2026-11-11.txt` | tc100_rtsp STAT lines and encoder log lines (3.0.0) | `../rtsp-2026-11-11.md` |
| `rtsp-11-rc37-*-2026-11-11.txt` | .11 on rc37: baseline 120 s, then `RTSP_PROFILE=1` at 24 fps (10 min) and 10 fps (5 min): per thread reads, STAT and PROF lines | `../rtsp-prof-2026-11-11.md` |
