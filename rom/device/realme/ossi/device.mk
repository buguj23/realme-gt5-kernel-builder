#
# Copyright (C) 2021-2026 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#

# AAPT
PRODUCT_AAPT_CONFIG := normal
PRODUCT_AAPT_PREF_CONFIG := xxxhdpi

# Audio
PRODUCT_COPY_FILES += \
    $(LOCAL_PATH)/configs/audio/audio_policy_volumes.xml:$(TARGET_COPY_OUT_VENDOR)/etc/audio_policy_volumes.xml

# Boot animation (Native: 1240 x 2772)
TARGET_SCREEN_HEIGHT := 2772
TARGET_SCREEN_WIDTH := 1240

# Display
PRODUCT_SYSTEM_PROPERTIES += \
    sys.brightness.disable_gamma_conversion=true

# Fingerprint (Realme GT5 UFF G_OPTICAL_G3S)
$(call soong_config_set,surfaceflinger,udfps_lib,//device/realme/ossi:libudfps_extension.ossi)

# IR
PRODUCT_COPY_FILES += \
    frameworks/native/data/etc/android.hardware.consumerir.xml:$(TARGET_COPY_OUT_ODM)/etc/permissions/android.hardware.consumerir.xml

PRODUCT_PACKAGES += \
    android.hardware.ir-service.oplus \
    consumerir.default

# Lights / Awakening Halo (艾为 AW210xx RGB LED)
PRODUCT_COPY_FILES += \
    $(LOCAL_PATH)/configs/misc/oplusLights.xml:$(TARGET_COPY_OUT_ODM)/etc/misc/oplusLights.xml

# Overlays
DEVICE_PACKAGE_OVERLAYS += \
    $(LOCAL_PATH)/overlay-lineage

PRODUCT_PACKAGES += \
    OPlusFrameworksResTarget \
    OPlusSettingsProviderResTarget \
    OPlusSettingsResTarget \
    OPlusSystemUIResTarget

# Regional properties (Prj: 22635)
PRODUCT_COPY_FILES += \
    $(LOCAL_PATH)/recovery/root/vendor/odm/etc/22635/flags.prop:$(TARGET_COPY_OUT_ODM)/etc/22635/flags.prop

# Soong namespaces
PRODUCT_SOONG_NAMESPACES += \
    $(LOCAL_PATH)

# Touch
$(call soong_config_set,OPLUS_LINEAGE_TOUCH_HAL,USE_OPLUSTOUCH,true)

# Vibrator
PRODUCT_PACKAGES += \
    vendor.qti.hardware.vibrator.service.oplus

$(call soong_config_set,OPLUS_LINEAGE_VIBRATOR_HAL,USE_EFFECT_STREAM,true)

# Inherit from the common OEM chipset makefile.
$(call inherit-product, device/oplus/sm8550-common/common.mk)

# Inherit from the proprietary files makefile.
$(call inherit-product, vendor/realme/ossi/ossi-vendor.mk)
