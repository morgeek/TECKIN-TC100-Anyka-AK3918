---
name: camera-logs
description: Fetch and display recent log files from the camera via FTP. Use to diagnose issues without manually opening an FTP client.
argument-hint: "[log-type] [lines] [camera-ip]"
disable-model-invocation: true
allowed-tools: Bash(curl *)
---

Pull logs from the camera's `/mnt/logs/` directory and display the most recent entries.

## Parsing $ARGUMENTS

$ARGUMENTS format: `[log-type] [lines] [ip]`  
- `log-type`: one of `events`, `syslog`, `watchdog`, `mqtt`, `all` (default: `events`)
- `lines`: number of lines to show (default: 50)
- `ip`: camera IP (default: 192.168.1.24)

Examples:
- `camera-logs` → last 50 lines of events.log
- `camera-logs watchdog 100` → last 100 lines of watchdog log
- `camera-logs all 30` → last 30 lines of every available log
- `camera-logs syslog 50 192.168.1.50` → from a different IP

## Log file paths on camera

| log-type | Camera path |
|----------|-------------|
| events   | /mnt/logs/events.log |
| syslog   | /mnt/logs/syslog.log |
| watchdog | /mnt/logs/watchdog.log |
| mqtt     | /mnt/logs/mqtt-bridge.log |
| all      | all of the above |

## Steps

1. For each target log file, download via FTP:
   ```bash
   curl --max-time 10 -s "ftp://root:pass@$IP:2121/mnt/logs/$LOGFILE" 2>/dev/null
   ```

2. If the file doesn't exist (empty response or curl error), skip it and note "not found".

3. Display the last N lines of each downloaded file. Since `tail` may not be available in the shell context, use:
   ```bash
   # Count lines then print last N
   echo "$CONTENT" | awk -v n=$LINES 'BEGIN{} {lines[NR]=$0} END{start=NR-n+1; if(start<1)start=1; for(i=start;i<=NR;i++) print lines[i]}'
   ```

4. Format the output with a clear header per log:
   ```
   ── events.log (last 50 lines, fetched from 192.168.1.24) ──
   2024-01-15 14:23:01 [motion] Motion detected zone A
   ...
   ```

5. If `log-type=all`, repeat for each log file in order: events → syslog → watchdog → mqtt.

6. At the end, summarize: how many lines shown per file, and flag any ERROR or CRITICAL keywords found.
