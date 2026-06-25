---
name: deploy
description: Deploy modified files to the camera via FTP. Use when the user asks to deploy, push, upload or sync files to the camera.
argument-hint: "[camera-ip]"
disable-model-invocation: true
---

Deploy the project files to the camera at the configured FTP address.

## Steps

1. Run `npm run check:web` to verify frontend/src and www are in sync. If it fails, run `npm run build:web` first.

2. Determine the base SHA for comparison:
   ```bash
   # Read last deployed SHA (written at end of a successful deploy)
   LAST_SHA=$(cat .claude/.last-deploy-sha 2>/dev/null || echo "")
   CURRENT_SHA=$(git rev-parse HEAD)
   ```
   - If `LAST_SHA` is set and different from `CURRENT_SHA`: diff from `LAST_SHA` to `HEAD`
   - If `LAST_SHA` equals `CURRENT_SHA`: nothing to deploy — confirm with user before continuing
   - If `LAST_SHA` is empty (first deploy): ask user whether to deploy all tracked files or only recently changed ones

3. List changed files:
   ```bash
   # If LAST_SHA is known:
   git diff --name-only $LAST_SHA HEAD
   # Otherwise (uncommitted changes):
   git diff --name-only HEAD
   ```

4. For each changed file that belongs on the camera, upload via FTP:
   ```bash
   curl --max-time 30 -s --ftp-create-dirs -T <local-path> ftp://root:pass@$IP:2121/mnt/<camera-path>
   ```

   Path mapping:
   - `www/` → `/mnt/www/`
   - `scripts/` → `/mnt/scripts/`
   - `controlscripts/` → `/mnt/controlscripts/`
   - `config/*.conf.dist` → `/mnt/config/`
   - `bin/` → `/mnt/bin/`
   - `lib/` → `/mnt/lib/`

5. For shell scripts, set executable permissions on camera:
   ```bash
   curl -s "ftp://root:pass@$IP:2121" --quote "SITE CHMOD 755 /mnt/<path>"
   ```

6. Verify deployment: `curl -s --max-time 5 http://$IP/cgi-bin/health.cgi`

7. On success, record the deployed SHA so next deploy only sends new changes:
   ```bash
   git rev-parse HEAD > .claude/.last-deploy-sha
   ```

8. If $ARGUMENTS specifies a camera IP, use that as `$IP`; otherwise default to `192.168.1.24`.

Report which files were uploaded and the health check result.
