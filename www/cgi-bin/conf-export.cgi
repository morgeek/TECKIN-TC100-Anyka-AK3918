#!/bin/sh
# conf-export.cgi — serve boot.conf + mqtt.conf as a single downloadable text file.
# GET only; no CSRF required (read-only, served over authenticated lighttpd session).

BOOT_CONF="/mnt/config/boot.conf"
MQTT_CONF="/mnt/config/mqtt.conf"
NOW="$(date '+%Y%m%d-%H%M%S' 2>/dev/null || echo 'export')"
FILENAME="tc100-config-${NOW}.conf"

printf 'Content-Type: text/plain; charset=utf-8\r\n'
printf 'Content-Disposition: attachment; filename="%s"\r\n' "$FILENAME"
printf 'Cache-Control: no-cache, no-store\r\n'
printf '\r\n'

printf '## tc100-boot-mqtt-export v1\n'
printf '## Camera config export — boot.conf + mqtt.conf\n'
printf '## Generated: %s\n' "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo 'unknown')"
printf '## Import via: System tab > Export / Import de configuration\n'
printf '##\n'
printf '##[SECTION:boot.conf]##\n'
if [ -f "$BOOT_CONF" ]; then
    cat "$BOOT_CONF"
else
    printf '# (boot.conf not found)\n'
fi
printf '\n'
printf '##[SECTION:mqtt.conf]##\n'
if [ -f "$MQTT_CONF" ]; then
    cat "$MQTT_CONF"
else
    printf '# (mqtt.conf not found)\n'
fi
