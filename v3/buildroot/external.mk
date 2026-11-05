# Slim hostapd / wpa_supplicant (2026-10-30 audit).  Buildroot's own lists (package/*/*.mk) are extended here.
# The camera uses WPA2-PSK (client: wifi-txt.sh, key_mgmt WPA-PSK or NONE; rescue AP: wifi-rescue.sh, wpa=2, CCMP),
# so no Hotspot 2.0 / Interworking, 802.11ax, pre-authentication, ERP, fast BSS transition or TDLS.
HOSTAPD_CONFIG_DISABLE += CONFIG_INTERWORKING CONFIG_HS20 CONFIG_IEEE80211AX CONFIG_RSN_PREAUTH CONFIG_ERP CONFIG_IEEE80211R
WPA_SUPPLICANT_CONFIG_DISABLE += CONFIG_TDLS CONFIG_IEEE80211R
# hostapd.mk enables HS20/AX/INTERWORKING/11R again for every build with a Wi-Fi driver (and appends them to .config
# when the DISABLE sed has commented them out): take them out of the enable list too.
HOSTAPD_CONFIG_ENABLE := $(filter-out CONFIG_HS20 CONFIG_IEEE80211AX CONFIG_INTERWORKING CONFIG_IEEE80211R,$(HOSTAPD_CONFIG_ENABLE))

# Item 35 (WHEP / WebRTC): mbedTLS 2.28 is built without DTLS-SRTP (use_srtp, RFC 5764), which tc100-whep needs. The
# switch is in include/mbedtls/config.h; a sed is used instead of a patch so that it does not depend on the lines
# around it, and the build stops if the option is not there afterwards (another mbedTLS version). Everything else
# the daemon needs (DTLS, ECDSA / P-256, X.509 and PEM writing, key export) is on in the default configuration and is
# only checked here; curl is not affected. The package itself: package/tc100-whep.
define MBEDTLS_ENABLE_DTLS_SRTP
	$(SED) 's|^//#define MBEDTLS_SSL_DTLS_SRTP|#define MBEDTLS_SSL_DTLS_SRTP|' $(@D)/include/mbedtls/config.h
	$(SED) 's|^//#define MBEDTLS_SSL_EXPORT_KEYS|#define MBEDTLS_SSL_EXPORT_KEYS|' $(@D)/include/mbedtls/config.h
	for o in MBEDTLS_SSL_DTLS_SRTP MBEDTLS_SSL_EXPORT_KEYS MBEDTLS_SSL_PROTO_DTLS MBEDTLS_SSL_DTLS_HELLO_VERIFY \
		MBEDTLS_ECDSA_C MBEDTLS_ECP_DP_SECP256R1_ENABLED MBEDTLS_X509_CRT_WRITE_C MBEDTLS_PK_WRITE_C \
		MBEDTLS_PEM_WRITE_C MBEDTLS_KEY_EXCHANGE_ECDHE_ECDSA_ENABLED; do \
		grep -q "^#define $$o" $(@D)/include/mbedtls/config.h || { echo "mbedtls: $$o is off"; exit 1; }; \
	done
endef
MBEDTLS_POST_PATCH_HOOKS += MBEDTLS_ENABLE_DTLS_SRTP

include $(sort $(wildcard $(BR2_EXTERNAL_TC100_PATH)/package/*/*.mk))
