---
name: deploy
description: Deploy modified files to the camera via FTP. Use when the user asks to deploy, push, upload or sync files to the camera.
disable-model-invocation: true
---

Deploy the project files to the camera at the configured FTP address.

## Steps

1. Run `npm run check:web` to verify frontend/src and www are in sync. If it fails, run `npm run build:web` first.

2. Determine which files changed since last commit:
   ```bash
   git diff --name-only HEAD
   ```

3. For each changed file that belongs on the camera, upload via FTP:
   ```bash
   curl --max-time 30 -s --ftp-create-dirs -T <local-path> ftp://root:pass@192.168.1.24:2121/mnt/<camera-path>
   ```

   Path mapping:
   - `www/` → `/mnt/www/`
   - `scripts/` → `/mnt/scripts/`
   - `controlscripts/` → `/mnt/controlscripts/`
   - `config/*.conf.dist` → `/mnt/config/`
   - `bin/` → `/mnt/bin/`
   - `lib/` → `/mnt/lib/`

4. For shell scripts, set executable permissions on camera:
   ```bash
   curl -s "ftp://root:pass@192.168.1.24:2121" --quote "SITE CHMOD 755 /mnt/<path>"
   ```

5. Verify deployment: `curl -s --max-time 5 http://192.168.1.24/cgi-bin/health.cgi`

6. If $ARGUMENTS specifies a camera IP, use that instead of 192.168.1.24.

Report which files were uploaded and the health check result.
