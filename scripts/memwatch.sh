#!/bin/sh
# memwatch.sh: memory measurement over days, to tell a kernel leak from benign growth (RAM logs filling to their caps,
# dentries, slab warm-up). Measurement only: nothing here changes the system, except the optional daily drop_caches.
#
#   memwatch.sh sample   one row of memory.csv (called by health-snapshot.sh at every stability sample, 5 min); the first
#                        one after boot + 10 min is kind "boot", the first one after each hour of uptime is kind
#                        "hourly" (it also writes a row of memory-hourly.csv), the others "sample"
#   memwatch.sh flush    write the pending rows to the file (the stop of health-snapshot, and every hour)
#
# Files (MEMWATCH_DIR forces the directory): next to stability.csv, that is /mnt/sd/logs when a card is mounted
# read-write, else /mnt/log (RAM in flash mode, never the flash).
#   memory.csv          a row per sample, 26 columns, ~140 bytes; capped at 1008 rows in RAM (3.5 days, ~140 KB),
#                       2016 rows on the card (7 days)
#   memory-hourly.csv   a row per hour (sockets, df, open deleted files, threads, rtl8xxxu URBs, buddyinfo), ~250 bytes;
#                       capped at 168 rows in RAM (7 days, ~42 KB), 720 on the card
# Rows are collected in /tmp/log/memwatch.pending and written once an hour (no SD write per sample).
#
# boot.conf (single source): MEMWATCH=1 (default; 0 = nothing is read, written or counted),
#                            MEMWATCH_DROP_HOUR= (empty = off; 4 = the first sample of 04:xx writes a "drop" row, runs
#                            sync + drop_caches + sleep 5 and writes a second "drop" row: before, then after).
# Fork-free where it can be: /proc is read with `while read`; the forks are one `df`, one `ls | grep` and (drop hour set
# only) one `date`, once an hour, plus `sh` for the call itself.
# memory-hourly.csv also carries the failure totals of tc100_rtsp since boot (rtsp_starts, pic_fail, enc_reopen, cap_stall,
# dq_err, sub_off, exit3: one `read` of /tmp/tc100_rtsp.counters, MEMWATCH_COUNTERS in tests); empty when the file is absent.
# Test overrides: MEMWATCH_PROC, MEMWATCH_SYS, MEMWATCH_CONF, MEMWATCH_PENDING, MEMWATCH_STATE, MEMWATCH_HOUR_DAY, MEMWATCH_DF, MEMWATCH_HISTORY, MEMWATCH_DROP_WAIT.

MP="${MEMWATCH_PROC:-/proc}"
SYSR="${MEMWATCH_SYS:-/sys}"
CONF="${MEMWATCH_CONF:-/mnt/config/boot.conf}"
PENDING="${MEMWATCH_PENDING:-/tmp/log/memwatch.pending}"
STATE="${MEMWATCH_STATE:-/tmp/memwatch.state}"
HIST="${MEMWATCH_HISTORY:-/tmp/health_history}"
CTRS="${MEMWATCH_COUNTERS:-/tmp/tc100_rtsp.counters}"
HDR='timestamp,uptime_s,kind,MemTotal,MemFree,MemAvailable,Active_file,Inactive_file,Active_anon,Inactive_anon,Unevictable,Shmem,SReclaimable,SUnreclaim,KernelStack,PageTables,Percpu,VmallocUsed,CmaFree,AnonPages,nr_free_pages,nr_free_cma,compact_stall,compact_fail,cma_alloc_success,cma_alloc_fail'
HHDR='timestamp,uptime_s,tcp_inuse,tcp_orphan,tcp_tw,tcp_mem,tmp_used_kb,mnt_used_kb,var_used_kb,open_deleted,threads,rx_urb_alive,tx_urb_free,rtsp_restarts,buddyinfo,rtsp_starts,pic_fail,enc_reopen,cap_stall,dq_err,sub_off,exit3'

mw_num() { case "$1" in ''|*[!0-9]*) _mwn= ;; *) _mwn="$1" ;; esac; }

# boot.conf keys, fork-free, the last one wins (the file is sourced by the boot script)
mw_conf() {
  MEMWATCH=1; MEMWATCH_DROP_HOUR=
  [ -r "$CONF" ] || return 0
  while IFS== read -r _k _v; do
    case "$_k" in MEMWATCH|MEMWATCH_DROP_HOUR) ;; *) continue ;; esac
    _v="${_v#\"}"; _v="${_v%\"}"; _v="${_v#\'}"; _v="${_v%\'}"
    case "$_k" in MEMWATCH) MEMWATCH="$_v" ;; *) MEMWATCH_DROP_HOUR="$_v" ;; esac
  done < "$CONF"
}

# where the files go (same rule as stability_default_path in health-snapshot.sh)
mw_dir() {
  if [ -n "${MEMWATCH_DIR:-}" ]; then _dir="$MEMWATCH_DIR"
  elif [ -n "${STABILITY_FILE:-}" ]; then _dir="${STABILITY_FILE%/*}"
  else
    _dir=/mnt/log
    while read -r _d _mp _fs _opt _rest; do
      case "$_mp $_fs" in
        "/mnt/sd vfat"|"/mnt/sd exfat") case ",$_opt," in *,ro,*) ;; *) _dir=/mnt/sd/logs ;; esac ;;
      esac
    done < "$MP/mounts"
  fi
  case "$_dir" in /mnt/sd/*) _sdcard=1 ;; *) _sdcard=0 ;; esac
}

# append the pending rows to FILE (header once), keep its last CAP rows
mw_append() { # file header cap pendingfile
  [ -s "$4" ] || return 0
  mkdir -p "${1%/*}" 2>/dev/null || true
  [ -s "$1" ] || printf '%s\n' "$2" > "$1" 2>/dev/null || return 0
  # a file from an older version has a shorter header: put the current one on top (the old rows keep their fewer columns);
  # only an old header is replaced, never a data row (a file whose header was lost keeps all its rows)
  _h1=; read -r _h1 < "$1" 2>/dev/null
  if [ "$_h1" != "$2" ] && [ "${_h1%%,*}" = timestamp ]; then
    _t="$1.$$"
    { printf '%s\n' "$2"; tail -n +2 "$1"; } > "$_t" && mv "$_t" "$1" || rm -f "$_t"
  fi
  cat "$4" >> "$1" 2>/dev/null || return 0
  : > "$4"
  _n="$(wc -l < "$1" 2>/dev/null)"; mw_num "$_n"; _n="${_mwn:-0}"
  if [ "$_n" -gt $(($3 + 25)) ]; then
    _t="$1.$$"
    { printf '%s\n' "$2"; tail -n "$3" "$1"; } > "$_t" && mv "$_t" "$1" || rm -f "$_t"
  fi
}

mw_flush() {
  mw_dir
  _cap="${MEMWATCH_MAX_ROWS:-}"; mw_num "$_cap"; _cap="${_mwn:-}"
  [ -n "$_cap" ] || { [ "$_sdcard" = 1 ] && _cap=2016 || _cap=1008; }
  [ "$_cap" -ge 24 ] || _cap=24
  mw_append "$_dir/memory.csv" "$HDR" "$_cap" "$PENDING"
}

# one memory.csv row of the given kind goes to the pending file
mw_row() {
  _mt=; _mf=; _ma=; _af=; _if=; _aa=; _ia=; _ue=; _sh=; _sr=; _su=; _ks=; _pt=; _pc=; _vu=; _cf=; _an=
  while read -r _k _v _; do
    case "$_k" in
      MemTotal:) _mt=$_v ;; MemFree:) _mf=$_v ;; MemAvailable:) _ma=$_v ;;
      'Active(file):') _af=$_v ;; 'Inactive(file):') _if=$_v ;;
      'Active(anon):') _aa=$_v ;; 'Inactive(anon):') _ia=$_v ;;
      Unevictable:) _ue=$_v ;; Shmem:) _sh=$_v ;; SReclaimable:) _sr=$_v ;; SUnreclaim:) _su=$_v ;;
      KernelStack:) _ks=$_v ;; PageTables:) _pt=$_v ;; Percpu:) _pc=$_v ;; VmallocUsed:) _vu=$_v ;;
      CmaFree:) _cf=$_v ;; AnonPages:) _an=$_v ;;
    esac
  done < "$MP/meminfo" 2>/dev/null
  _fp=; _fc=; _cs=; _cl=; _as=; _al=
  while read -r _k _v; do
    case "$_k" in
      nr_free_pages) _fp=$_v ;; nr_free_cma) _fc=$_v ;; compact_stall) _cs=$_v ;; compact_fail) _cl=$_v ;;
      cma_alloc_success) _as=$_v ;; cma_alloc_fail) _al=$_v ;;
    esac
  done < "$MP/vmstat" 2>/dev/null
  mkdir -p "${PENDING%/*}" 2>/dev/null || true
  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
    "$_ts" "$_up_s" "$1" "$_mt" "$_mf" "$_ma" "$_af" "$_if" "$_aa" "$_ia" "$_ue" "$_sh" "$_sr" "$_su" "$_ks" "$_pt" "$_pc" \
    "$_vu" "$_cf" "$_an" "$_fp" "$_fc" "$_cs" "$_cl" "$_as" "$_al" >> "$PENDING" 2>/dev/null
}

# one memory-hourly.csv row, written at once (once an hour)
mw_hourly() {
  _ti=; _to=; _tw=; _tm=
  while read -r _k _rest; do
    [ "$_k" = "TCP:" ] || continue
    set -- $_rest
    while [ $# -ge 2 ]; do
      case "$1" in inuse) _ti=$2 ;; orphan) _to=$2 ;; tw) _tw=$2 ;; mem) _tm=$2 ;; esac
      shift 2
    done
  done < "$MP/net/sockstat" 2>/dev/null
  _du1=; _du2=; _du3=; _i=0
  while read -r _fs _bl _used _rest; do
    _i=$((_i + 1))
    case "$_i" in 2) _du1=$_used ;; 3) _du2=$_used ;; 4) _du3=$_used ;; esac
  done <<EOF
$("${MEMWATCH_DF:-df}" -k /tmp /mnt /var 2>/dev/null)
EOF
  _del="$(ls -l "$MP"/[0-9]*/fd/ 2>/dev/null | grep -c '(deleted)')"
  _thr=; read -r _l1 _l2 _l3 _l4 _ < "$MP/loadavg" 2>/dev/null; _thr="${_l4#*/}"
  _rx=; _tx=
  [ -r "$SYSR/module/rtl8xxxu/parameters/rx_urb_alive" ] && read -r _rx < "$SYSR/module/rtl8xxxu/parameters/rx_urb_alive"
  [ -r "$SYSR/module/rtl8xxxu/parameters/tx_urb_free" ] && read -r _tx < "$SYSR/module/rtl8xxxu/parameters/tx_urb_free"
  # restarts the health snapshot counted for the video service (tc100_rtsp has no cheap connect counter)
  _rr=; [ -r "$HIST/rtsp-h26x" ] && read -r _rr _ < "$HIST/rtsp-h26x"
  _bd=; _sp=
  while read -r _b1 _b2 _b3 _bz _bc; do
    [ "$_b3" = "zone" ] || continue
    set -- $_bc; _j="$1"; shift
    for _x in "$@"; do _j="$_j/$_x"; done
    _bd="${_bd}${_sp}${_bz}:${_j}"; _sp=';'
  done < "$MP/buddyinfo" 2>/dev/null
  # failure totals of tc100_rtsp since boot (/tmp/tc100_rtsp.counters: one line "name=value ...", written by the server)
  _c_st=; _c_pf=; _c_er=; _c_cs=; _c_dq=; _c_so=; _c_e3=
  if [ -r "$CTRS" ]; then
    read -r _cl < "$CTRS"
    set -f	# no file name expansion of a damaged line; only plain numbers reach the CSV
    for _w in $_cl; do
      mw_num "${_w#*=}"
      case "$_w" in
        starts=*) _c_st="$_mwn" ;; pic_fail=*) _c_pf="$_mwn" ;; enc_reopen=*) _c_er="$_mwn" ;;
        cap_stall=*) _c_cs="$_mwn" ;; dq_err=*) _c_dq="$_mwn" ;; sub_off=*) _c_so="$_mwn" ;; exit3=*) _c_e3="$_mwn" ;;
      esac
    done
    set +f
  fi
  mw_dir
  _hcap="${MEMWATCH_MAX_HOURLY:-}"; mw_num "$_hcap"; _hcap="${_mwn:-}"
  [ -n "$_hcap" ] || { [ "$_sdcard" = 1 ] && _hcap=720 || _hcap=168; }
  [ "$_hcap" -ge 24 ] || _hcap=24
  _hp="$PENDING.hourly"
  mkdir -p "${PENDING%/*}" 2>/dev/null || true
  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' "$_ts" "$_up_s" "$_ti" "$_to" "$_tw" "$_tm" "$_du1" "$_du2" "$_du3" \
    "$_del" "$_thr" "$_rx" "$_tx" "$_rr" "$_bd" "$_c_st" "$_c_pf" "$_c_er" "$_c_cs" "$_c_dq" "$_c_so" "$_c_e3" > "$_hp" 2>/dev/null
  mw_append "$_dir/memory-hourly.csv" "$HHDR" "$_hcap" "$_hp"
}

mw_sample() {
  mw_conf
  [ "$MEMWATCH" = 0 ] && return 0
  # wall clock without a fork: boot time + uptime
  _bt=0
  while read -r _k _v _; do [ "$_k" = btime ] && { _bt="$_v"; break; }; done < "$MP/stat" 2>/dev/null
  read -r _up _ < "$MP/uptime" 2>/dev/null; _up_s="${_up%.*}"
  mw_num "$_up_s"; _up_s="${_mwn:-0}"; mw_num "$_bt"; _bt="${_mwn:-0}"
  _ts=$((_bt + _up_s))
  _sb=0; _sh_=0; _sd=
  [ -r "$STATE" ] && read -r _sb _sh_ _sd < "$STATE"
  mw_num "$_sb"; _sb="${_mwn:-0}"; mw_num "$_sh_"; _sh_="${_mwn:-0}"
  [ "$_sh_" -gt "$_up_s" ] && _sh_=0        # uptime went back: a new boot, the state file is old
  _kind=sample
  if [ "$_sb" = 0 ] && [ "$_up_s" -ge 600 ]; then _kind=boot; _sb=1; _sh_=$_up_s
  elif [ $((_up_s - _sh_)) -ge 3600 ]; then _kind=hourly; _sh_=$_up_s; fi
  mw_row "$_kind"
  if [ "$_kind" = hourly ]; then mw_hourly; fi
  # the daily pair around drop_caches: the first sample of the chosen hour, once a day
  case "$MEMWATCH_DROP_HOUR" in ''|*[!0-9]*) ;; *)
    if [ -n "${MEMWATCH_HOUR_DAY:-}" ]; then _hd="$MEMWATCH_HOUR_DAY"; else _hd="$(date '+%H %j' 2>/dev/null)"; fi
    set -- $_hd; _h="$1"; _day="$2"
    case "$_h" in 0?) _h="${_h#0}" ;; esac
    _w="$MEMWATCH_DROP_HOUR"; case "$_w" in 0?) _w="${_w#0}" ;; esac
    if [ "$_h" = "$_w" ] && [ -n "$_day" ] && [ "$_sd" != "$_day" ]; then
      _sd="$_day"
      printf '%s %s %s\n' "$_sb" "$_sh_" "$_sd" > "$STATE" 2>/dev/null     # first: a crash here must not repeat it
      mw_row drop
      sync
      echo 3 > "$MP/sys/vm/drop_caches" 2>/dev/null
      sleep "${MEMWATCH_DROP_WAIT:-5}"
      read -r _up _ < "$MP/uptime" 2>/dev/null; _up_s="${_up%.*}"; mw_num "$_up_s"; _up_s="${_mwn:-0}"
      _ts=$((_bt + _up_s))
      mw_row drop
      _kind=drop
    fi ;;
  esac
  printf '%s %s %s\n' "$_sb" "$_sh_" "$_sd" > "$STATE" 2>/dev/null
  [ "$_kind" = sample ] || mw_flush
}

case "$1" in
  sample) mw_sample ;;
  flush) mw_flush ;;
  *) echo "usage: memwatch.sh sample|flush" >&2; exit 2 ;;
esac
exit 0
