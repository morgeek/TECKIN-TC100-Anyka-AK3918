#!/bin/bash
# deploy-full.sh — safe full-tree deploy to a TC100 camera over FTP, with a
# backup first and AUTOMATIC ROLLBACK if the camera fails its post-deploy
# health check.
#
# Runs on YOUR computer (Mac/Linux), NOT on the camera. Requires: bash, curl
# (with FTP), and the camera's FTP server running.
#
# Lessons this version encodes (all hit on real hardware, 2026-08-11):
#   - NEVER overwrite a binary whose daemon is running: the FTP write fails
#     with ETXTBSY and can leave the service dead until a power cycle (this
#     killed lighttpd mid-deploy). Binaries identical to the repo are skipped
#     by size comparison; differing ones are refused unless --force-binaries.
#   - The camera's FTP login costs ~7 s per connection. Everything is batched:
#     many URLs per curl invocation so the control connection is reused.
#     (160 files: ~2-3 min instead of ~80.)
#   - health.cgi sits behind HTTP auth: an unauthenticated probe reads the 401
#     page and always concludes "unhealthy". The probe now authenticates.
#   - SITE CHMOD answers 500 on the camera's ftpd and the SD card is vfat
#     (exec bits come from mount options), so no chmod is attempted at all.
#   - curl with several URLs returns only the LAST transfer's status, so
#     success is established by re-listing the tree and comparing sizes,
#     never by curl's exit code.
#
# USAGE
#   CAM_HOST=<camera-ip> CAM_PASS=pass ./tools/deploy-full.sh [options]
#
# OPTIONS
#   --dry-run          Show what would happen; upload nothing.
#   --changed-only     Deploy only files changed vs .last-deploy-sha. Use only
#                      when the camera is already on a compatible base version.
#   --force-binaries   Upload bin/* and lib/* files even when they differ from
#                      the camera's copy. DANGEROUS while daemons run (ETXTBSY):
#                      stop the owning services first, and expect to reboot.
#   --no-rollback      Do not auto-restore on health-check failure (not advised).
#   --skip-backup      Skip the backup (NOT advised; backup is the safety net).
#   --port N           FTP port (default 2121).
#   --user NAME        FTP/HTTP user (default root).
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
FORCE_BINARIES=0
DO_ROLLBACK=1
DO_BACKUP=1
HEALTH_RETRIES=10
HEALTH_INTERVAL=3
BATCH_SIZE=20

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --changed-only) CHANGED_ONLY=1 ;;
    --force-binaries) FORCE_BINARIES=1 ;;
    --no-rollback) DO_ROLLBACK=0 ;;
    --skip-backup) DO_BACKUP=0 ;;
    --port) shift; FTP_PORT="$1" ;;
    --user) shift; FTP_USER="$1" ;;
    --health-retries) shift; HEALTH_RETRIES="$1" ;;
    -h|--help) sed -n '2,50p' "$0"; exit 0 ;;
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
WORK="$(mktemp -d "${TMPDIR:-/tmp}/deploy-full.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

log()  { printf '\033[1;36m[deploy]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
# Unambiguous outcome marker: survives being piped into tail/tee, where the
# script's exit code is masked by the pipeline.
finish() { printf '\033[1;36m[deploy]\033[0m RESULT: exit %s (%s)\n' "$1" "$2"; exit "$1"; }

# camera-path mapping: repo path -> /mnt subpath ("" = not deployed)
map_target() {
  case "$1" in
    www/*|scripts/*|controlscripts/*|bin/*|lib/*) echo "/mnt/${1}" ;;
    autorun.sh)         echo "/mnt/autorun.sh" ;;
    VERSION)            echo "/mnt/VERSION" ;;
    config/autostart/*) echo "/mnt/config/autostart/$(basename "$1")" ;;
    config/*.dist)      echo "/mnt/config/$(basename "$1")" ;;
    *) echo "" ;;
  esac
}

local_size() {
  if stat -f%z "$1" >/dev/null 2>&1; then stat -f%z "$1"; else stat -c%s "$1"; fi
}

# files that belong on the camera
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

# ---- remote inventory: list every target directory in ONE curl invocation
# (one FTP login total instead of one per directory), each listing written to
# its own file via -o so per-directory attribution survives.
# Produces $WORK/remote_sizes: "<size>|<path relative to /mnt>"
scan_remote() {
  : > "$WORK/remote_sizes"
  local dirs=() rel dir
  while IFS= read -r rel; do
    dir="${rel%/*}"; [ "$dir" = "$rel" ] && dir="."
    case " ${dirs[*]-} " in *" $dir "*) ;; *) dirs+=("$dir") ;; esac
  done < "$WORK/relpaths"

  local args=() d i=0
  mkdir -p "$WORK/ls"
  for d in "${dirs[@]}"; do
    local url
    if [ "$d" = "." ]; then url="${FTP_BASE}/mnt/"; else url="${FTP_BASE}/mnt/${d}/"; fi
    args+=(-o "$WORK/ls/$i" "$url")
    printf '%s\n' "$d" >> "$WORK/ls/index"
    i=$((i+1))
  done
  curl -s --max-time 600 "${CURL_AUTH[@]}" "${args[@]}" 2>/dev/null || true

  # The camera's ftpd sheds load by answering empty listings right after heavy
  # transfer bursts (observed on hardware: a post-upload scan came back empty
  # for most directories and flagged 133 healthy files as failed). Retry any
  # empty listing individually, after letting the ftpd breathe.
  i=0
  while IFS= read -r d; do
    if [ ! -s "$WORK/ls/$i" ]; then
      local url attempt
      if [ "$d" = "." ]; then url="${FTP_BASE}/mnt/"; else url="${FTP_BASE}/mnt/${d}/"; fi
      for attempt in 1 2 3; do
        sleep 3
        curl -s --max-time 120 "${CURL_AUTH[@]}" -o "$WORK/ls/$i" "$url" 2>/dev/null || true
        [ -s "$WORK/ls/$i" ] && break
      done
    fi
    if [ -s "$WORK/ls/$i" ]; then
      awk -v D="$d" 'NF>=9 && $1 !~ /^d/ { n=$9; if (D != ".") n=D"/"n; print $5 "|" n }' \
        "$WORK/ls/$i" >> "$WORK/remote_sizes"
    else
      warn "listing still empty for '$d' after retries — its files will look absent"
    fi
    i=$((i+1))
  done < "$WORK/ls/index"
  rm -rf "$WORK/ls"
}

remote_size_of() {
  awk -F'|' -v R="$1" '$2 == R { print $1; exit }' "$WORK/remote_sizes"
}

health_ok() {
  # health.cgi requires HTTP auth (lighttpd) — an anonymous probe reads the
  # 401 body and never matches, which made the old script "fail" healthy
  # deploys and roll them back.
  local body
  body="$(curl -sk --max-time 8 --user "${FTP_USER}:${CAM_PASS}" \
          "${HTTP_BASE}/cgi-bin/health.cgi" 2>/dev/null)"
  case "$body" in *'"ok":true'*) return 0 ;; *) return 1 ;; esac
}

# Batched upload of "src|dst" pairs from a file; retries stragglers singly.
# Success is judged by re-listing and comparing sizes, not by curl's exit code.
upload_pairs() {
  local pairs_file="$1" total=0 src dst
  local args=() n=0

  while IFS='|' read -r src dst; do
    [ -n "$src" ] || continue
    args+=(-T "$src" "${FTP_BASE}${dst}")
    total=$((total+1)); n=$((n+1))
    if [ "$n" -ge "$BATCH_SIZE" ]; then
      curl -s --max-time 600 --ftp-create-dirs "${CURL_AUTH[@]}" "${args[@]}" >/dev/null 2>&1 || true
      args=(); n=0
    fi
  done < "$pairs_file"
  [ "${#args[@]}" -gt 0 ] && curl -s --max-time 600 --ftp-create-dirs "${CURL_AUTH[@]}" "${args[@]}" >/dev/null 2>&1 || true

  # verification sweep
  verify_sweep() {
    cut -d'|' -f2 "$pairs_file" | sed 's#^/mnt/##' > "$WORK/relpaths"
    scan_remote
    : > "$WORK/failed_pairs"
    local v_src v_dst v_want v_got v_rel
    while IFS='|' read -r v_src v_dst; do
      [ -n "$v_src" ] || continue
      v_rel="${v_dst#/mnt/}"
      v_want="$(local_size "$v_src")"; v_got="$(remote_size_of "$v_rel")"
      [ "$v_got" = "$v_want" ] || printf '%s|%s\n' "$v_src" "$v_dst" >> "$WORK/failed_pairs"
    done < "$pairs_file"
  }
  verify_sweep

  # A mostly-failed sweep is the signature of a scan artifact (ftpd shedding
  # listings after the upload burst), not of mass upload failure — observed on
  # hardware: 133/136 healthy files flagged failed. Re-scan once before
  # believing it.
  local n_failed
  n_failed="$(wc -l < "$WORK/failed_pairs" | tr -d ' ')"
  if [ "$n_failed" -gt $((total / 2)) ] && [ "$total" -gt 4 ]; then
    warn "verification flagged ${n_failed}/${total} — likely a scan artifact, re-scanning in 10 s"
    sleep 10
    verify_sweep
  fi

  # retry stragglers individually (2 attempts); verification via the parent
  # directory listing — proven reliable on both cameras, unlike FTP SIZE/-I.
  if [ -s "$WORK/failed_pairs" ]; then
    warn "retrying $(wc -l < "$WORK/failed_pairs" | tr -d ' ') file(s) individually"
    local attempt want got rel
    while IFS='|' read -r src dst; do
      for attempt in 1 2; do
        curl -s --max-time 120 --ftp-create-dirs "${CURL_AUTH[@]}" -T "$src" "${FTP_BASE}${dst}" >/dev/null 2>&1
        rel="${dst#/mnt/}"
        want="$(local_size "$src")"
        printf '%s\n' "$rel" > "$WORK/relpaths"
        scan_remote
        got="$(remote_size_of "$rel")"
        [ "$got" = "$want" ] && break
        [ "$attempt" = "2" ] && { err "upload failed after retries: $dst"; return 1; }
      done
    done < "$WORK/failed_pairs"
  fi
  log "uploaded and size-verified ${total} file(s)."
  return 0
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
  # restore only what this run uploaded, batched
  : > "$WORK/restore_pairs"
  local src dst rel
  while IFS='|' read -r src dst; do
    rel="${dst#/mnt/}"
    [ -f "${BACKUP_DIR}/${rel}" ] && printf '%s|%s\n' "${BACKUP_DIR}/${rel}" "$dst" >> "$WORK/restore_pairs"
  done < "$WORK/upload_pairs"
  upload_pairs "$WORK/restore_pairs"
}

# ---- 0. preflight ----
log "Target camera: ${CAM_HOST} (FTP ${FTP_PORT}, HTTPS health)"
if ! curl -s --max-time 45 "${CURL_AUTH[@]}" "${FTP_BASE}/mnt/" >/dev/null 2>&1; then
  err "Cannot list ${FTP_BASE}/mnt/ — is the FTP server running on the camera?"
  err "Start it: curl -sk --user ${FTP_USER}:*** '${HTTP_BASE}/cgi-bin/scripts.cgi?cmd=start&script=ftp-server'"
  finish 1 "ftp unreachable"
fi
log "FTP reachable."

CUR_VERSION="$(curl -s --max-time 45 "${CURL_AUTH[@]}" "${FTP_BASE}/mnt/VERSION" 2>/dev/null | tr -d '\r\n ')"
NEW_VERSION="$(tr -d '\r\n ' < "${REPO_ROOT}/VERSION" 2>/dev/null)"
log "Camera version: ${CUR_VERSION:-unknown} -> repo version: ${NEW_VERSION:-unknown}"
if [ "$CHANGED_ONLY" = "1" ] && [ "$CUR_VERSION" != "$NEW_VERSION" ]; then
  warn "--changed-only but camera (${CUR_VERSION:-?}) != repo (${NEW_VERSION:-?})."
  warn "A partial deploy across versions can brick the UI. Prefer a full deploy."
  printf "Continue anyway? [y/N] "; read -r ans; [ "$ans" = "y" ] || finish 1 "aborted by user"
fi

# ---- 1. build the deploy plan (needs the remote inventory) ----
: > "$WORK/all_pairs"; : > "$WORK/relpaths"
while IFS= read -r f; do
  [ -n "$f" ] || continue
  dst="$(map_target "$f")"; [ -n "$dst" ] || continue
  printf '%s|%s\n' "$f" "$dst" >> "$WORK/all_pairs"
  printf '%s\n' "${dst#/mnt/}" >> "$WORK/relpaths"
done < <(collect_files)

log "Scanning camera tree (one FTP session)..."
scan_remote

: > "$WORK/upload_pairs"; : > "$WORK/skipped_bins"; : > "$WORK/blocked_bins"
while IFS='|' read -r src dst; do
  rel="${dst#/mnt/}"
  case "$src" in
    bin/*|lib/*)
      want="$(local_size "$src")"; got="$(remote_size_of "$rel")"
      if [ "$got" = "$want" ]; then
        # Same size for a binary ⇒ same build in practice; skipping avoids the
        # ETXTBSY write onto a running daemon's binary that killed lighttpd.
        printf '%s\n' "$rel" >> "$WORK/skipped_bins"
        continue
      fi
      if [ "$FORCE_BINARIES" != "1" ]; then
        printf '%s\n' "$rel" >> "$WORK/blocked_bins"
        continue
      fi
      warn "--force-binaries: uploading $rel over a possibly-running daemon"
      ;;
  esac
  printf '%s|%s\n' "$src" "$dst" >> "$WORK/upload_pairs"
done < "$WORK/all_pairs"

N_UP="$(wc -l < "$WORK/upload_pairs" | tr -d ' ')"
N_SKIP="$(wc -l < "$WORK/skipped_bins" | tr -d ' ')"
log "Plan: ${N_UP} file(s) to upload, ${N_SKIP} identical binaries skipped."
if [ -s "$WORK/blocked_bins" ]; then
  warn "These binaries DIFFER from the camera and are NOT deployed (ETXTBSY risk):"
  sed 's/^/  - /' "$WORK/blocked_bins"
  warn "Stop the owning daemons and rerun with --force-binaries, then reboot."
fi

if [ "$DRY_RUN" = "1" ]; then
  sed 's/^/  [dry-run] /' "$WORK/upload_pairs" | head -40
  [ "$N_UP" -gt 40 ] && log "[dry-run] ... and $((N_UP - 40)) more"
  finish 0 "dry-run"
fi

# ---- 2. backup: only files that exist remotely, batched ----
if [ "$DO_BACKUP" = "1" ]; then
  log "Backing up the files this deploy overwrites -> ${BACKUP_DIR}"
  if command -v lftp >/dev/null 2>&1; then
    lftp -e "set net:timeout 15; mirror --parallel=2 --only-newer=no /mnt '${BACKUP_DIR}'; bye" \
      -u "${FTP_USER},${CAM_PASS}" "ftp://${CAM_HOST}:${FTP_PORT}" \
      || { err "Backup (lftp) failed — aborting before any change."; finish 1 "backup failed"; }
  else
    args=(); count=0
    while IFS='|' read -r src dst; do
      rel="${dst#/mnt/}"
      # Only fetch what exists remotely: a RETR on a missing file breaks the
      # batched session and costs a full timeout (the old per-file loop burned
      # 20 s per missing file — an hour on a fresh camera).
      [ -n "$(remote_size_of "$rel")" ] || continue
      mkdir -p "${BACKUP_DIR}/$(dirname "$rel")"
      args+=(-o "${BACKUP_DIR}/${rel}" "${FTP_BASE}${dst}")
      count=$((count+1))
      if [ "${#args[@]}" -ge $((BATCH_SIZE * 2)) ]; then
        curl -s --max-time 600 "${CURL_AUTH[@]}" "${args[@]}" >/dev/null 2>&1 || true
        args=()
      fi
    done < "$WORK/upload_pairs"
    [ "${#args[@]}" -gt 0 ] && curl -s --max-time 600 "${CURL_AUTH[@]}" "${args[@]}" >/dev/null 2>&1 || true
    find "$BACKUP_DIR" -type f -size 0 -delete 2>/dev/null
    log "Backup: ${count} file(s) captured."
  fi
else
  warn "--skip-backup: no safety net for this run."
fi
cp "$WORK/upload_pairs" "$WORK/upload_pairs.plan" 2>/dev/null || true

# ---- 3. deploy ----
log "Deploying..."
if ! upload_pairs "$WORK/upload_pairs"; then
  err "One or more uploads failed."
  [ "$DO_ROLLBACK" = "1" ] && rollback "upload error"
  finish 2 "deploy error"
fi

# ---- 4. health check ----
log "Waiting for camera health (up to $((HEALTH_RETRIES*HEALTH_INTERVAL))s)..."
ok=0
for i in $(seq 1 "$HEALTH_RETRIES"); do
  if health_ok; then ok=1; break; fi
  sleep "$HEALTH_INTERVAL"
done

if [ "$ok" = "1" ]; then
  git rev-parse HEAD > "${REPO_ROOT}/.last-deploy-sha" 2>/dev/null || true
  log "Health check PASSED. Backup kept at ${BACKUP_DIR}"
  [ -s "$WORK/blocked_bins" ] && warn "Reminder: blocked binaries were NOT deployed (see above)."
  finish 0 "deploy succeeded"
fi

if rollback "health.cgi did not report ok"; then
  ok2=0
  for i in $(seq 1 "$HEALTH_RETRIES"); do health_ok && { ok2=1; break; }; sleep "$HEALTH_INTERVAL"; done
  if [ "$ok2" = "1" ]; then
    err "Deploy FAILED health check; camera ROLLED BACK to the pre-deploy state (now healthy)."
    finish 3 "rolled back"
  fi
  err "Deploy failed AND post-rollback health still failing. INSPECT THE CAMERA. Backup: ${BACKUP_DIR}"
  finish 4 "rollback did not restore health"
fi
err "Deploy failed and rollback failed. INSPECT THE CAMERA. Backup: ${BACKUP_DIR}"
finish 4 "rollback failed"
