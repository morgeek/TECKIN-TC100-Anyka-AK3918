# Slim hostapd / wpa_supplicant (2026-10-30 audit).  Buildroot's own lists (package/*/*.mk) are extended here.
# The camera uses WPA2-PSK (client: wifi-txt.sh, key_mgmt WPA-PSK or NONE; rescue AP: wifi-rescue.sh, wpa=2, CCMP),
# so no Hotspot 2.0 / Interworking, 802.11ax / 802.11be, pre-authentication, ERP, fast BSS transition or TDLS (the radio is
# an 802.11n 1T1R RTL8188FU). 2025.02 (wpa_supplicant / hostapd 2.12) turned 802.11be on in hostapd and 802.11ax, 802.11be
# and IPv6 on in wpa_supplicant (+330 KB together): switched off again (the kernel has no IPv6).
HOSTAPD_CONFIG_DISABLE += CONFIG_INTERWORKING CONFIG_HS20 CONFIG_IEEE80211AX CONFIG_IEEE80211BE CONFIG_RSN_PREAUTH CONFIG_ERP CONFIG_IEEE80211R
WPA_SUPPLICANT_CONFIG_DISABLE += CONFIG_TDLS CONFIG_IEEE80211R CONFIG_IEEE80211AX CONFIG_IEEE80211BE CONFIG_IPV6
# hostapd.mk enables HS20/AX/BE/INTERWORKING/11R again for every build with a Wi-Fi driver (and appends them to .config
# when the DISABLE sed has commented them out): take them out of the enable list too.
HOSTAPD_CONFIG_ENABLE := $(filter-out CONFIG_HS20 CONFIG_IEEE80211AX CONFIG_IEEE80211BE CONFIG_INTERWORKING CONFIG_IEEE80211R,$(HOSTAPD_CONFIG_ENABLE))

# Item 35 (WHEP / WebRTC): tc100-whep needs DTLS-SRTP (use_srtp, RFC 5764). Mbed TLS 3.6 has it off by default; since
# Buildroot 2025.02 the package switches it on itself (BR2_PACKAGE_MBEDTLS_DTLS_SRTP=y in tc100_defconfig), which
# replaces the sed of the 2.28 era (include/mbedtls/config.h is mbedtls_config.h now; MBEDTLS_SSL_EXPORT_KEYS no longer
# exists, the key export is always built). The build stops here if an option the daemon needs is not on after the
# configuration (another Mbed TLS version, a changed Buildroot hook). Everything else the daemon needs (DTLS, ECDSA /
# P-256, X.509 and PEM writing) is on in the default configuration and is only checked; curl is not affected.
# The package itself: package/tc100-whep.
define MBEDTLS_CHECK_DTLS_SRTP
	for o in MBEDTLS_SSL_DTLS_SRTP MBEDTLS_SSL_PROTO_DTLS MBEDTLS_SSL_DTLS_HELLO_VERIFY \
		MBEDTLS_ECDSA_C MBEDTLS_ECP_DP_SECP256R1_ENABLED MBEDTLS_X509_CRT_WRITE_C MBEDTLS_PK_WRITE_C \
		MBEDTLS_PEM_WRITE_C MBEDTLS_KEY_EXCHANGE_ECDHE_ECDSA_ENABLED; do \
		grep -q "^#define $$o" $(@D)/include/mbedtls/mbedtls_config.h || { echo "mbedtls: $$o is off"; exit 1; }; \
	done
endef
MBEDTLS_POST_CONFIGURE_HOOKS += MBEDTLS_CHECK_DTLS_SRTP

include $(sort $(wildcard $(BR2_EXTERNAL_TC100_PATH)/package/*/*.mk))
