#!/bin/bash
# deploy-full.sh — safe full-tree deploy to a TC100 camera over FTP, with a
# complete /mnt backup first and AUTOMATIC ROLLBACK if the camera fails its
# post-deploy health check.
#
# Runs on YOUR computer (Mac/Linux), NOT on the camera and NOT inside Cowork —
# the cloud sandbox and the Cowork device bridge cannot reach a camera on your
# LAN. Requires: bash, curl (with FTP), and the camera's FTP server running.
#
# Why "full tree" and not an incremental diff: a camera still on a pre-1.2 build
# has v1.1.x helpers that the v1.3.0 CGIs call into; a partial deploy mixes them
# and bricks the UI. For a camera already on the target version you can pass
# --changed-only to deploy just what git says changed.
#
# USAGE
#   CAM_HOST=192.168.1.11 CAM_PASS=pass ./tools/deploy-full.sh [options]
#
# OPTIONS
#   --dry-run          Show what would happen; upload nothing.
#   --changed-only     Deploy only files changed vs the last deploy (or vs a base
#                      SHA in .last-deploy-sha). Use only when the camera is
#                      already on a compatible base version.
#   --no-rollback      Do not auto-restore on health-check failure (not advised).
#   --skip-backup      Skip the /mnt backup (NOT advised; backup is your safety net).
#   --port N           FTP port (default 2121).
#   --user NAME        FTP user (default root).
#   --health-retries N Health-check attempts after deploy (default 10, 3s apart).
#
# ENV
#   CAM_HOST (required)  camera IP/host
#   CAM_PASS (required)  FTP/root password
#
# EXIT CODES: 0 ok · 1 usage/precondition · 2 deploy error · 3 health failed
#             (rolled back) · 4 health failed AND rollback failed (INSPECT DEVICE)
set -u

# ---- args / env ----
CAM_HOST="${CAM_HOST:-}"
CAM_PASS="${CAM_PASS:-}"
FTP_PORT=2121
FTP_USER=root
DRY_RUN=0
CHANGED_ONLY=0
DO_ROLLBACK=1
DO_BACKUP=1
HEALTH_RETRIES=10
HEALTH_INTERVAL=3

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --changed-only) CHANGED_ONLY=1 ;;
    --no-rollback) DO_ROLLBACK=0 ;;
    --skip-backup) DO_BACKUP=0 ;;
    --port) shift; FTP_PORT="$1" ;;
    --user) shift; FTP_USER="$1" ;;
    --health-retries) shift; HEALTH_RETRIES="$1" ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

[ -n "$CAM_HOST" ] || { echo "ERROR: set CAM_HOST (camera IP)." >&2; exit 1; }
[ -n "$CAM_PASS" ] || { echo "ERROR: set CAM_PASS (camera password)." >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required." >&2; exit 1; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

FTP_BASE="ftp://${CAM_HOST}:${FTP_PORT}"
CURL_AUTH=(--user "${FTP_USER}:${CAM_PASS}")
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${REPO_ROOT}/backup-${CAM_HOST}-${TS}"
HTTP_BASE="https://${CAM_HOST}"

log()  { printf '\033[1;36m[deploy]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }

# camera-path mapping: repo dir -> /mnt subpath
map_target() {
  case "$1" in
    www/*)            echo "/mnt/${1}" ;;
    scripts/*)        echo "/mnt/${1}" ;;
    controlscripts/*) echo "/mnt/${1}" ;;
    bin/*)            echo "/mnt/${1}" ;;
    lib/*)            echo "/mnt/${1}" ;;
    autorun.sh)       echo "/mnt/autorun.sh" ;;
    VERSION)          echo "/mnt/VERSION" ;;
    config/*.dist)    echo "/mnt/config/$(basename "$1")" ;;
    config/autostart/*) echo "/mnt/config/autostart/$(basename "$1")" ;;
    *) echo "" ;;   # not deployed
  esac
}

# health check + rollback are defined up here because the deploy step may call
# rollback on an upload error, before step 3 would otherwise define it (bash
# registers a function only when its definition line executes).
health_ok() {
  local body
  body="$(curl -sk --max-time 6 "${HTTP_BASE}/cgi-bin/health.cgi" 2>/dev/null)"
  case "$body" in *'"ok":true'*) return 0 ;; *) return 1 ;; esac
}

rollback() {
  local reason="$1"
  if [ "$DO_ROLLBACK" != "1" ]; then
    err "Health check failed ($reason) and --no-rollback set. Camera may be broken."
    return 1
  fi
  if [ ! -d "$BACKUP_DIR" ]; then
    err "Health failed ($reason) but no backup dir to restore from. INSPECT THE CAMERA."
    return 1
  fi
  warn "Health check failed ($reason) — ROLLING BACK from ${BACKUP_DIR}"
  local rc=0
  if command -v lftp >/dev/null 2>&1; then
    lftp -e "set net:timeout 15; mirror -R --parallel=2 '${BACKUP_DIR}' /mnt; bye" \
      -u "${FTP_USER},${CAM_PASS}" "ftp://${CAM_HOST}:${FTP_PORT}" || rc=1
  else
    local dst rel
    for dst in "${UPLOADED[@]}"; do
      rel="${dst#/mnt/}"
      [ -f "${BACKUP_DIR}/${rel}" ] || continue
      curl -s --max-time 30 --ftp-create-dirs "${CURL_AUTH[@]}" \
        -T "${BACKUP_DIR}/${rel}" "${FTP_BASE}${dst}" || rc=1
    done
  fi
  [ "$rc" = "0" ] && warn "Rollback uploaded. Re-checking health..." || err "Rollback had upload errors."
  return "$rc"
}

# files that belong on the camera (tracked, excluding host-only tooling/tests)
collect_files() {
  if [ "$CHANGED_ONLY" = "1" ]; then
    local base=""
    [ -f "${REPO_ROOT}/.last-deploy-sha" ] && base="$(cat "${REPO_ROOT}/.last-deploy-sha")"
    if [ -n "$base" ]; then
      git diff --name-only "$base" HEAD
    else
      warn "no .last-deploy-sha; --changed-only falls back to full tree"
      git ls-files
    fi
  else
    git ls-files
  fi
}

# ---- 0. preflight: camera reachable, FTP up, health endpoint present? ----
log "Target camera: ${CAM_HOST} (FTP ${FTP_PORT}, HTTPS health)"
if ! curl -s --max-time 8 "${CURL_AUTH[@]}" "${FTP_BASE}/mnt/" >/dev/null 2>&1; then
  err "Cannot list ${FTP_BASE}/mnt/ — is the FTP server running on the camera?"
  err "Start it from the web UI (Services -> ftp-server) or:"
  err "  curl -sk '${HTTP_BASE}/cgi-bin/scripts.cgi?cmd=start&script=ftp-server'"
  exit 1
fi
log "FTP reachable."

CUR_VERSION="$(curl -s --max-time 8 "${CURL_AUTH[@]}" "${FTP_BASE}/mnt/VERSION" 2>/dev/null | tr -d '\r\n ')"
NEW_VERSION="$(tr -d '\r\n ' < "${REPO_ROOT}/VERSION" 2>/dev/null)"
log "Camera version: ${CUR_VERSION:-unknown} -> repo version: ${NEW_VERSION:-unknown}"
if [ "$CHANGED_ONLY" = "1" ] && [ "$CUR_VERSION" != "$NEW_VERSION" ]; then
  warn "--changed-only but camera ($CUR_VERSION) != repo ($NEW_VERSION)."
  warn "A partial deploy across versions can brick the UI. Prefer a full deploy."
  printf "Continue anyway? [y/N] "; read -r ans; [ "$ans" = "y" ] || exit 1
fi

# ---- 1. backup /mnt ----
if [ "$DO_BACKUP" = "1" ] && [ "$DRY_RUN" = "0" ]; then
  log "Backing up camera /mnt -> ${BACKUP_DIR}"
  mkdir -p "$BACKUP_DIR"
  if command -v lftp >/dev/null 2>&1; then
    lftp -e "set net:timeout 15; mirror --parallel=2 --only-newer=no /mnt '${BACKUP_DIR}'; bye" \
      -u "${FTP_USER},${CAM_PASS}" "ftp://${CAM_HOST}:${FTP_PORT}" \
      || { err "Backup (lftp) failed — aborting before any change."; exit 1; }
  else
    warn "lftp not found — backing up only the files this deploy will overwrite."
    warn "Install lftp for a FULL /mnt image backup (brew install lftp)."
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      local_target="$(map_target "$f")"; [ -n "$local_target" ] || continue
      rel="${local_target#/mnt/}"
      mkdir -p "${BACKUP_DIR}/$(dirname "$rel")"
      curl -s --max-time 20 "${CURL_AUTH[@]}" "${FTP_BASE}${local_target}" \
        -o "${BACKUP_DIR}/${rel}" 2>/dev/null || true
    done < <(collect_files)
  fi
  log "Backup complete: ${BACKUP_DIR}"
else
  [ "$DRY_RUN" = "1" ] && log "[dry-run] would back up /mnt"
fi

# ---- 2. deploy ----
UPLOADED=()
deploy_one() {
  local src="$1" dst="$2"
  if [ "$DRY_RUN" = "1" ]; then log "[dry-run] ${src} -> ${dst}"; return 0; fi
  curl -s --max-time 30 --ftp-create-dirs "${CURL_AUTH[@]}" -T "$src" "${FTP_BASE}${dst}" \
    || { err "Upload failed: ${src} -> ${dst}"; return 1; }
  case "$dst" in
    *.sh|*.cgi|/mnt/autorun.sh|/mnt/controlscripts/*|/mnt/config/autostart/*)
      curl -s "${CURL_AUTH[@]}" "${FTP_BASE}/" --quote "SITE CHMOD 755 ${dst}" >/dev/null 2>&1 || true ;;
  esac
  UPLOADED+=("$dst")
}

log "Deploying $([ "$CHANGED_ONLY" = 1 ] && echo 'changed' || echo 'all') camera files..."
DEPLOY_FAIL=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  dst="$(map_target "$f")"; [ -n "$dst" ] || continue
  deploy_one "$f" "$dst" || DEPLOY_FAIL=1
done < <(collect_files)

if [ "$DEPLOY_FAIL" = "1" ]; then
  err "One or more uploads failed."
  [ "$DO_ROLLBACK" = "1" ] && rollback "upload error"
  exit 2
fi
[ "$DRY_RUN" = "1" ] && { log "[dry-run] complete."; exit 0; }
log "Uploaded ${#UPLOADED[@]} files."

# ---- 3. health check ----
log "Waiting for camera health (up to $((HEALTH_RETRIES*HEALTH_INTERVAL))s)..."
ok=0
for i in $(seq 1 "$HEALTH_RETRIES"); do
  if health_ok; then ok=1; break; fi
  sleep "$HEALTH_INTERVAL"
done

if [ "$ok" = "1" ]; then
  log "Health check PASSED. Deploy succeeded."
  git rev-parse HEAD > "${REPO_ROOT}/.last-deploy-sha" 2>/dev/null || true
  log "Recorded deployed SHA. Backup kept at ${BACKUP_DIR}"
  log "NOTE: reboot the camera only after confirming the UI loads and the wizard (if any) completes."
  exit 0
fi

if rollback "health.cgi did not report ok"; then
  # verify rollback restored health
  ok2=0
  for i in $(seq 1 "$HEALTH_RETRIES"); do health_ok && { ok2=1; break; }; sleep "$HEALTH_INTERVAL"; done
  if [ "$ok2" = "1" ]; then
    err "Deploy FAILED health check; camera ROLLED BACK to the pre-deploy state (now healthy)."
    exit 3
  fi
  err "Deploy failed AND post-rollback health still failing. INSPECT THE CAMERA. Backup: ${BACKUP_DIR}"
  exit 4
fi
err "Deploy failed and rollback failed. INSPECT THE CAMERA. Backup: ${BACKUP_DIR}"
exit 4
