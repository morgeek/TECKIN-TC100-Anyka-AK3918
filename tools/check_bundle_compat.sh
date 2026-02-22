#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE_BIN="$REPO_ROOT/bin"
BASE_LIB="$REPO_ROOT/lib"

usage() {
  cat <<'EOF'
Usage: tools/check_bundle_compat.sh <bundle_dir>

Checks whether a candidate package bundle is likely compatible with this camera:
- ELF payloads must be ARM 32-bit EABI5
- Dynamic binaries must use /lib/ld-uClibc.so.0
- New runtime dependencies vs baseline are rejected
- Only known baseline file names are accepted by default
- Non-ELF files are allowed only when the baseline file is also non-ELF

Expected bundle layout:
  <bundle_dir>/bin/<files...>
  <bundle_dir>/lib/<files...>
EOF
}

require_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "ERROR: missing required command: $cmd" >&2
    exit 2
  }
}

is_arm_eabi5_elf() {
  local f="$1"
  local out
  out="$(file "$f")"
  [[ "$out" == *"ELF 32-bit LSB"* && "$out" == *"ARM"* && "$out" == *"EABI5"* ]]
}

is_elf() {
  local f="$1"
  file "$f" | grep -q "ELF"
}

get_needed_sorted() {
  local f="$1"
  objdump -p "$f" 2>/dev/null | awk '/NEEDED/{print $2}' | sort -u
}

check_dynamic_interp() {
  local f="$1"
  local out
  out="$(file "$f")"
  [[ "$out" == *"interpreter /lib/ld-uClibc.so.0"* ]]
}

check_no_new_needed() {
  local base="$1"
  local cand="$2"
  local base_needed cand_needed new_needed

  base_needed="$(get_needed_sorted "$base")"
  cand_needed="$(get_needed_sorted "$cand")"
  new_needed="$(comm -13 <(printf '%s\n' "$base_needed") <(printf '%s\n' "$cand_needed") || true)"

  if [[ -n "$new_needed" ]]; then
    echo "    adds new runtime deps:"
    printf '      - %s\n' $new_needed
    return 1
  fi
  return 0
}

check_busybox_applets() {
  local cand="$1"
  # Applets required by this project runtime/control scripts.
  local required="tcpsvd ftpd telnetd httpd watchdog ntpd flock gzip strings nohup date run-parts crond sendmail"
  local missing=""
  local s_file
  s_file="$(mktemp)"
  LC_ALL=C strings "$cand" > "$s_file" 2>/dev/null || true

  for applet in $required; do
    if ! grep -qx "$applet" "$s_file"; then
      missing="$missing $applet"
    fi
  done
  rm -f "$s_file"

  if [[ -n "$missing" ]]; then
    echo "    missing required BusyBox applets:${missing}"
    return 1
  fi
  return 0
}

if [[ $# -ne 1 ]]; then
  usage
  exit 1
fi

require_cmd file
require_cmd objdump
require_cmd awk
require_cmd grep
require_cmd mktemp
require_cmd sort
require_cmd comm
require_cmd strings

BUNDLE_DIR="$1"
if [[ ! -d "$BUNDLE_DIR" ]]; then
  echo "ERROR: bundle dir not found: $BUNDLE_DIR" >&2
  exit 1
fi

if [[ ! -d "$BUNDLE_DIR/bin" && ! -d "$BUNDLE_DIR/lib" ]]; then
  echo "ERROR: bundle must include bin/ and/or lib/: $BUNDLE_DIR" >&2
  exit 1
fi

fail_count=0
warn_count=0

echo "Checking bundle: $BUNDLE_DIR"
echo "Baseline: $REPO_ROOT"

if [[ -d "$BUNDLE_DIR/bin" ]]; then
  while IFS= read -r -d '' cand; do
    name="$(basename "$cand")"
    base="$BASE_BIN/$name"
    echo
    echo "[BIN] $name"

    if [[ ! -f "$base" ]]; then
      echo "  ERROR: not in baseline bin/: $name"
      fail_count=$((fail_count + 1))
      continue
    fi

    if is_elf "$base"; then
      if ! is_arm_eabi5_elf "$cand"; then
        echo "  ERROR: expected ARM EABI5 ELF"
        fail_count=$((fail_count + 1))
        continue
      fi

      if file "$cand" | grep -q "dynamically linked"; then
        if ! check_dynamic_interp "$cand"; then
          echo "  ERROR: dynamic loader is not /lib/ld-uClibc.so.0"
          fail_count=$((fail_count + 1))
        fi
      fi

      if ! check_no_new_needed "$base" "$cand"; then
        echo "  ERROR: dependency profile differs from baseline"
        fail_count=$((fail_count + 1))
      fi
    else
      if is_elf "$cand"; then
        echo "  ERROR: baseline is non-ELF but candidate is ELF"
        fail_count=$((fail_count + 1))
        continue
      fi
    fi

    if [[ "$name" == "busybox" ]]; then
      if ! check_busybox_applets "$cand"; then
        echo "  ERROR: busybox candidate is missing required applets"
        fail_count=$((fail_count + 1))
      fi
    fi
  done < <(find "$BUNDLE_DIR/bin" -maxdepth 1 -type f -print0 | sort -z)
fi

if [[ -d "$BUNDLE_DIR/lib" ]]; then
  while IFS= read -r -d '' cand; do
    name="$(basename "$cand")"
    base="$BASE_LIB/$name"
    echo
    echo "[LIB] $name"

    if [[ ! -f "$base" ]]; then
      echo "  ERROR: not in baseline lib/: $name"
      fail_count=$((fail_count + 1))
      continue
    fi

    if ! is_arm_eabi5_elf "$cand"; then
      echo "  ERROR: expected ARM EABI5 ELF shared object"
      fail_count=$((fail_count + 1))
      continue
    fi

    if ! check_no_new_needed "$base" "$cand"; then
      echo "  ERROR: dependency profile differs from baseline"
      fail_count=$((fail_count + 1))
    fi
  done < <(find "$BUNDLE_DIR/lib" -maxdepth 1 -type f -print0 | sort -z)
fi

echo
echo "Summary: $fail_count error(s), $warn_count warning(s)"
if [[ $fail_count -ne 0 ]]; then
  echo "Result: FAIL"
  exit 1
fi
echo "Result: PASS"
