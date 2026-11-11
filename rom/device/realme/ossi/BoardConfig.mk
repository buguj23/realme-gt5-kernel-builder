#
# Copyright (C) 2021-2026 The LineageOS Project
#
# SPDX-License-Identifier: Apache-2.0
#

# Include the common OEM chipset BoardConfig.
include device/oplus/sm8550-common/BoardConfigCommon.mk

DEVICE_PATH := device/realme/ossi

# Assert
TARGET_OTA_ASSERT_DEVICE := RMX3820,RE5C33,ossi

# Display
TARGET_SCREEN_DENSITY := 450

# Partitions (Super: 14495514624 bytes)
BOARD_ONEPLUS_DYNAMIC_PARTITIONS_SIZE := 14491320320
BOARD_SUPER_PARTITION_SIZE := 14495514624

# Power
TARGET_POWERHAL_MODE_EXT := $(DEVICE_PATH)/power/power-mode.cpp
BOARD_POWER_CUSTOM_BOARD_LIB += \
    vendor.oplus.hardware.touch-V1-ndk

# Properties
TARGET_ODM_PROP += $(DEVICE_PATH)/odm.prop
TARGET_VENDOR_PROP += $(DEVICE_PATH)/vendor.prop

# Recovery
TARGET_RECOVERY_UI_MARGIN_HEIGHT := 138

# Include the proprietary files BoardConfig.
include vendor/realme/ossi/BoardConfigVendor.mk
