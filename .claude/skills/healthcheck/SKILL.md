---
name: healthcheck
description: Check camera reachability and live status. Use before or after any deploy, or when the camera seems unresponsive.
argument-hint: "[camera-ip]"
disable-model-invocation: true
allowed-tools: Bash(ping *) Bash(curl *)
---

Check whether the camera at $ARGUMENTS (default: 192.168.1.24) is alive and report its status.

## Steps

1. Resolve the target IP:
   ```
   IP=${ARGUMENTS:-192.168.1.24}
   ```

2. Ping (1 packet, 2s timeout):
   ```bash
   ping -n 1 -w 2000 $IP
   ```
   If ping fails, report "Camera unreachable at $IP" and stop.

3. Fetch `health.cgi` over HTTP (5s timeout):
   ```bash
   curl -s --max-time 5 http://$IP/cgi-bin/health.cgi
   ```

4. If HTTP fails, try HTTPS:
   ```bash
   curl -sk --max-time 5 https://$IP/cgi-bin/health.cgi
   ```

5. Parse and display the JSON response in a readable summary:
   - Uptime
   - Free memory (mem_free_kb)
   - CPU load (if present)
   - RTSP status
   - MQTT status
   - Any `"error"` fields

6. Also fetch `sysusageinfo.cgi` for a memory snapshot:
   ```bash
   curl -s --max-time 5 http://$IP/cgi-bin/sysusageinfo.cgi
   ```

Report: "OK — camera at $IP is alive" or "DEGRADED — <reason>" with the parsed values.
