################################################################################
# tc100-httpsd: low-CPU native HTTPS reverse proxy, built from src/httpsd against
# system mbedTLS. Installed in /usr/bin of the base image; v3/build-stack.sh
# moves it to the user space (ext/bin) like tc100-whep.
################################################################################
TC100_HTTPSD_VERSION = 1
TC100_HTTPSD_SITE = $(BR2_EXTERNAL_TC100_PATH)/../../src/httpsd
TC100_HTTPSD_SITE_METHOD = local
TC100_HTTPSD_DEPENDENCIES = mbedtls
TC100_HTTPSD_LICENSE = GPL-2.0

define TC100_HTTPSD_BUILD_CMDS
	$(TARGET_CC) $(TARGET_CFLAGS) -Os -Wall -Wextra -ffunction-sections -fdata-sections $(TARGET_LDFLAGS) \
		-Wl,--gc-sections -o $(@D)/tc100-httpsd $(@D)/tc100_httpsd.c -lmbedtls -lmbedx509 -lmbedcrypto
endef

define TC100_HTTPSD_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/tc100-httpsd $(TARGET_DIR)/usr/bin/tc100-httpsd
endef

$(eval $(generic-package))
