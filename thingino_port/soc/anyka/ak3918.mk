# Anyka AK3918 family support for Thingino
# AK3918EV300, AK3918AV130, AK3918V200
ifneq ($(filter $(SOC_MODEL),ak3918ev300 ak3918av130 ak3918v200),)

SOC_FAMILY    := ak3918
SOC_ARCH      := arm926ejs
SOC_RAM_MB    := 64
SOC_UBOOT_BIN := uImage

ifeq ($(SOC_MODEL),ak3918ev300)
SOC_RAM_MB    := 64
else ifeq ($(SOC_MODEL),ak3918av130)
SOC_RAM_MB    := 64
else ifeq ($(SOC_MODEL),ak3918v200)
SOC_RAM_MB    := 64
endif

endif
