# anyka-wifi.awk: the Wi-Fi network of the stock firmware (/etc/jffs2/anyka_cfg.ini, [wireless] ssid / password)
# as a wpa_supplicant.conf. Exit 1 when there is none or it cannot be written safely. Same decoding as
# scripts/wifi-txt.sh (the vendor file escapes =, ;, " and space as \001, \002, \003, \005).
function val(s) {
	sub(/^[^=]*=[ \t]*/, "", s); sub(/[ \t]*;.*$/, "", s); gsub(/"/, "", s)
	gsub(/\001/, "=", s); gsub(/\002/, ";", s); gsub(/\003/, "\"", s); gsub(/\005/, " ", s)
	return s
}
/^\[/ { w = ($0 ~ /^\[wireless\]/) }
w && /^ssid[ \t]*=/ { ss = val($0) }
w && /^password[ \t]*=/ { pw = val($0) }
END {
	if (ss == "" || ss ~ /["\\]/ || pw ~ /["\\]/) exit 1
	printf "ctrl_interface=/var/run/wpa_supplicant\nap_scan=1\nnetwork={\n\tssid=\"%s\"\n\tscan_ssid=1\n", ss
	if (length(pw) >= 8) printf "\tkey_mgmt=WPA-PSK\n\tpsk=\"%s\"\n", pw
	else printf "\tkey_mgmt=NONE\n"
	printf "}\n"
}
