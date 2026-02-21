#!/bin/sh

echo "Content-type: image/jpeg"
echo ""

tmp_input="/tmp/currentpic.$$"
tmp_output="/tmp/currentpicoptim.$$"

cleanup() {
  rm -f "$tmp_input" "$tmp_output"
}

trap cleanup EXIT INT TERM

if ! /mnt/bin/getimage > "$tmp_input" 2>/dev/null; then
  exit 0
fi

if [ ! -s "$tmp_input" ]; then
  exit 0
fi

if [ -x /mnt/bin/jpegtran ]; then
  if /mnt/bin/jpegtran -progressive -optimize < "$tmp_input" > "$tmp_output" 2>/dev/null && [ -s "$tmp_output" ]; then
    cat "$tmp_output"
    exit 0
  fi
fi

cat "$tmp_input"
