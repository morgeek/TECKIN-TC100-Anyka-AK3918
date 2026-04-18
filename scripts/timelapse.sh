#!/bin/sh

# Takes a snapshot every N seconds interval configured
# in /mnt/config/timelapse.conf

PIDFILE='/var/run/timelapse.pid'
TIMELAPSE_CONF='/mnt/config/timelapse.conf'
BASE_SAVE_DIR='/mnt/DCIM/timelapse'

if [ -f "$TIMELAPSE_CONF" ]; then
    . "$TIMELAPSE_CONF" 2>/dev/null
fi

if [ -z "$TIMELAPSE_INTERVAL" ]; then TIMELAPSE_INTERVAL=2.0; fi
if [ -z "$TIMELAPSE_DURATION" ]; then TIMELAPSE_DURATION=0; fi
if [ -z "$SAVE_DIR_PER_DAY" ]; then SAVE_DIR_PER_DAY=0; fi

case "$TIMELAPSE_DURATION" in
    ''|*[!0-9]*)
        TIMELAPSE_DURATION=0
        ;;
esac
[ "$TIMELAPSE_DURATION" -lt 0 ] && TIMELAPSE_DURATION=0
[ "$TIMELAPSE_DURATION" -gt 1440 ] && TIMELAPSE_DURATION=1440

case "$SAVE_DIR_PER_DAY" in
    1) ;;
    *) SAVE_DIR_PER_DAY=0 ;;
esac

_BTIME=0
_read_btime() {
  while read -r _k _v _; do
    [ "$_k" = "btime" ] && _BTIME="$_v" && break
  done < /proc/stat
}
_read_ts() {
  [ "$_BTIME" -gt 0 ] || _read_btime
  read -r _up _ < /proc/uptime
  now_ts=$((_BTIME + ${_up%.*}))
}
_format_date_ymd() {
  _epoch="$1"
  _days=$(((_epoch / 86400) + 719468))
  _z=$((_days - _days % 146097 + (_days % 146097 >= 109573 ? 146097 : 0)))
  _era=$((_z / 146097))
  _doe=$((_days - _z))
  _yoe=$(((_doe + 1) * 400 / 146097))
  _y=$((_era * 400 + _yoe))
  _doy=$((_doe - _yoe * 365 - _yoe / 4 + _yoe / 100))
  _mp=$(((5 * _doy + 2) * 153 / 5))
  _d=$((_mp % 153 + 1))
  _m=$((_mp / 153 + ([ $_mp -lt 306 ] && echo 3 || echo -9)))
  _y=$((_m <= 2 ? _y + 1 : _y))
  printf '%04d-%02d-%02d' "$_y" "$_m" "$_d"
}
_format_datetime() {
  _epoch="$1"
  _days=$(((_epoch / 86400) + 719468))
  _secs=$((_epoch % 86400))
  _z=$((_days - _days % 146097 + (_days % 146097 >= 109573 ? 146097 : 0)))
  _era=$((_z / 146097))
  _doe=$((_days - _z))
  _yoe=$(((_doe + 1) * 400 / 146097))
  _y=$((_era * 400 + _yoe))
  _doy=$((_doe - _yoe * 365 - _yoe / 4 + _yoe / 100))
  _mp=$(((5 * _doy + 2) * 153 / 5))
  _d=$((_mp % 153 + 1))
  _m=$((_mp / 153 + ([ $_mp -lt 306 ] && echo 3 || echo -9)))
  _y=$((_m <= 2 ? _y + 1 : _y))
  _hr=$((_secs / 3600))
  _min=$(((_secs % 3600) / 60))
  _sec=$((_secs % 60))
  printf '%04d-%02d-%02d_%02d%02d%02d' "$_y" "$_m" "$_d" "$_hr" "$_min" "$_sec"
}

case "$TIMELAPSE_INTERVAL" in
    ''|*[!0-9.]*|*.*.*)
        TIMELAPSE_INTERVAL=2
        ;;
esac
TIMELAPSE_INTERVAL="$(awk -v v="$TIMELAPSE_INTERVAL" 'BEGIN { if (v+0 < 1) print 1; else if (v+0 > 300) print 300; else print v+0 }')"

cleanup()
{
    rm -f "$PIDFILE"
}

trap cleanup EXIT INT TERM


# because``date`` doesn't support milliseconds +%N
# we have to use a running counter to generate filenames
counter=0
last_prefix=''
_read_ts
ts_started=$now_ts

while true; do
    _read_ts
    SAVE_DIR=$BASE_SAVE_DIR
    if [ $SAVE_DIR_PER_DAY -eq 1 ]; then
        SAVE_DIR="$BASE_SAVE_DIR/$(_format_date_ymd "$now_ts")"
    fi
    if [ ! -d "$SAVE_DIR" ]; then
        mkdir -p "$SAVE_DIR"
    fi
    filename_prefix="$(_format_datetime "$now_ts")"
    if [ "$filename_prefix" = "$last_prefix" ]; then
        counter=$(($counter + 1))
    else
        counter=1
        last_prefix="$filename_prefix"
    fi
    counter_formatted=$(printf '%03d' $counter)
    filename="${filename_prefix}_${counter_formatted}.jpg"

    # Capture synchronously to avoid stacking multiple getimage processes
    # when storage is slow or getimage blocks.
    /mnt/bin/getimage > "$SAVE_DIR/$filename" 2>/dev/null

    sleep $TIMELAPSE_INTERVAL

    if [ $TIMELAPSE_DURATION -gt 0 ]; then
        _read_ts
        ts_now=$now_ts
        elapsed=$(($ts_now - $ts_started))
        if [ $(($TIMELAPSE_DURATION * 60)) -le $elapsed ]; then
            break
        fi
    fi
done

# loop completed so let's purge pid file
rm -f "$PIDFILE"
