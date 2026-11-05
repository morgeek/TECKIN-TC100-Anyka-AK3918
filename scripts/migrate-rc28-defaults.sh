#!/bin/sh
# migrate-rc28-defaults.sh: once per camera (config/.migrated-rc28-defaults), the features of 2026-11-05 become the
# defaults (owner, 2026-11-05: "active tous les items codés que nous incluront dans la prochaine RC"). A camera keeps
# its config files over an update (install_config copies a .dist only when the file is missing), so the new defaults of
# the .dist files never reach it: here each key is set to its new value when it is missing or still holds the value the
# firmware shipped before. Anything else (a value chosen by someone) is left alone, and after this run the user's
# choices stand: the marker makes it run once. Each key keeps its own switch (Settings, the file, test-queue).
#   FILE KEY OLD NEW
# MR_CONF_DIR changes /mnt/config (tests).
C=${MR_CONF_DIR:-/mnt/config}
[ -d "$C" ] || exit 0
[ -f "$C/.migrated-rc28-defaults" ] && exit 0
while read -r f k old new; do
  [ -n "$f" ] || continue
  p=$C/$f
  [ -f "$p" ] || { [ -f "$p.dist" ] && cp "$p.dist" "$p"; } || continue
  cur=$(sed -n "s/^$k=\"\{0,1\}\([^\"]*\)\"\{0,1\}\$/\1/p" "$p" | tail -n 1)
  if ! grep -q "^$k=" "$p"; then
    printf '%s=%s\n' "$k" "$new" >> "$p"
  elif [ "$cur" = "$old" ]; then
    sed "s|^$k=.*|$k=$new|" "$p" > "$p.tmp.$$" && mv -f "$p.tmp.$$" "$p"
  fi
done <<EOF
boot.conf SUPERVISOR_IMPL sh c
boot.conf WHEP 0 1
boot.conf HTTPFRONT_NATIVE 0 1
boot.conf NET_GUARD_SOFT 0 1
boot.conf WEB_LOCKOUT 0 1
boot.conf MDNS_SERVICES 0 1
boot.conf MDNS_INFO 0 1
boot.conf REC_KEEP_EVENTS 0 1
boot.conf SD_AUTO_REPAIR 0 1
boot.conf WIFI_QUALITY 0 1
boot.conf WIFI_ROAM 0 1
mqtt.conf MQTT_BRIDGE_IMPL shell c
mqtt.conf MQTT_DISCOVERY_IMPL sh c
onvif.conf ONVIF_IMPL monvifd c
EOF
: > "$C/.migrated-rc28-defaults"
