################################################################################
# tc100-whep: the WHEP / WebRTC gateway (item 35), built from src/whep of this source tree against the system
# mbedTLS (which external.mk builds with MBEDTLS_SSL_DTLS_SRTP). Installed in /usr/bin of the base image;
# v3/build-stack.sh moves it to the user space (ext/bin) like curl.
################################################################################
TC100_WHEP_VERSION = 1
TC100_WHEP_SITE = $(BR2_EXTERNAL_TC100_PATH)/../../src/whep
TC100_WHEP_SITE_METHOD = local
TC100_WHEP_DEPENDENCIES = mbedtls
TC100_WHEP_LICENSE = GPL-2.0

define TC100_WHEP_BUILD_CMDS
	$(TARGET_CC) $(TARGET_CFLAGS) -Os -Wall -Wextra -ffunction-sections -fdata-sections $(TARGET_LDFLAGS) \
		-Wl,--gc-sections -o $(@D)/tc100-whep $(@D)/tc100_whep.c -lmbedtls -lmbedx509 -lmbedcrypto
endef

define TC100_WHEP_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/tc100-whep $(TARGET_DIR)/usr/bin/tc100-whep
endef

$(eval $(generic-package))
