# Slim hostapd / wpa_supplicant (2026-10-30 audit).  Buildroot's own lists (package/*/*.mk) are extended here.
# The camera uses WPA2-PSK (client: wifi-txt.sh, key_mgmt WPA-PSK or NONE; rescue AP: wifi-rescue.sh, wpa=2, CCMP),
# so no Hotspot 2.0 / Interworking, 802.11ax, pre-authentication, ERP, fast BSS transition or TDLS.
HOSTAPD_CONFIG_DISABLE += CONFIG_INTERWORKING CONFIG_HS20 CONFIG_IEEE80211AX CONFIG_RSN_PREAUTH CONFIG_ERP CONFIG_IEEE80211R
WPA_SUPPLICANT_CONFIG_DISABLE += CONFIG_TDLS CONFIG_IEEE80211R
# hostapd.mk enables HS20/AX/INTERWORKING/11R again for every build with a Wi-Fi driver (and appends them to .config
# when the DISABLE sed has commented them out): take them out of the enable list too.
HOSTAPD_CONFIG_ENABLE := $(filter-out CONFIG_HS20 CONFIG_IEEE80211AX CONFIG_INTERWORKING CONFIG_IEEE80211R,$(HOSTAPD_CONFIG_ENABLE))
