---
name: camera-probe
description: Test a CGI endpoint on the live camera and validate the JSON response. Use after deploying a new or modified CGI script to confirm it works on real hardware.
argument-hint: "<cgi-path-and-query> [camera-ip]"
disable-model-invocation: true
allowed-tools: Bash(curl *)
---

Hit a CGI endpoint on the live camera and validate the response.

## Parsing $ARGUMENTS

$ARGUMENTS format: `<endpoint> [ip]`  
Examples:
- `camera-probe cgi-bin/health.cgi`
- `camera-probe "cgi-bin/action.cgi?cmd=statusline"`
- `camera-probe cgi-bin/state.cgi?cmd=all 192.168.1.50`

Parse:
- Last token that matches an IP pattern → camera IP (default: 192.168.1.24)
- Remaining tokens → endpoint path (e.g. `cgi-bin/action.cgi?cmd=statusline`)

## Steps

1. Build the URL: `http://$IP/$ENDPOINT`

2. Send GET request (10s timeout, follow redirects):
   ```bash
   curl -s --max-time 10 -L "http://$IP/$ENDPOINT"
   ```
   If that fails, retry with HTTPS:
   ```bash
   curl -sk --max-time 10 -L "https://$IP/$ENDPOINT"
   ```

3. Validate the response:
   - Is it non-empty?
   - Is it valid JSON? (Try `echo "$RESPONSE" | jq .` or manual check)
   - Does it contain `"error"` or `"ok":false`?
   - HTTP status code (use `-w "%{http_code}"` in curl)

4. Display a structured summary:
   ```
   URL:     http://192.168.1.24/cgi-bin/action.cgi?cmd=statusline
   Status:  200 OK
   JSON:    valid
   Content: { ... pretty-printed top-level keys ... }
   Result:  OK / ERROR (reason)
   ```

5. If the response is not valid JSON, show the raw first 500 chars and flag as FAIL.

If the endpoint requires POST or a CSRF token, note that in the output and suggest using `csrfFetch` from the browser console for interactive testing.
