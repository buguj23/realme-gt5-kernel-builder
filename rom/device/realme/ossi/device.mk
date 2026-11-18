LOCAL_PATH := $(call my-dir)
DEVICE_PATH := device/realme/ossi

PRODUCT_AAPT_CONFIG := normal
PRODUCT_AAPT_PREF_CONFIG := xxxhdpi

# GT5 panel 6.74" 2772x1240 @ 144Hz
TARGET_SCREEN_HEIGHT := 2772
TARGET_SCREEN_WIDTH := 1240

PRODUCT_SHIPPING_API_LEVEL := 33

# Official first-stage init (IDA ReadDefaultFstab): hardware=qcom → fstab.qcom.
OSSI_FSTAB := $(DEVICE_PATH)/prebuilt/fstab.ossi
PRODUCT_COPY_FILES += \
    $(OSSI_FSTAB):$(TARGET_COPY_OUT_VENDOR_RAMDISK)/first_stage_ramdisk/fstab.qcom \
    $(OSSI_FSTAB):$(TARGET_COPY_OUT_VENDOR)/etc/fstab.qcom \
    $(OSSI_FSTAB):$(TARGET_COPY_OUT_RECOVERY)/root/first_stage_ramdisk/fstab.qcom
PRODUCT_COPY_FILES += $(foreach key,$(wildcard $(DEVICE_PATH)/prebuilt/oem-avb-keys/*.avbpubkey),\
    $(key):$(TARGET_COPY_OUT_VENDOR_RAMDISK)/avb/ossi-oem/$(notdir $(key)) \
    $(key):$(TARGET_COPY_OUT_VENDOR_RAMDISK)/first_stage_ramdisk/avb/ossi-oem/$(notdir $(key)))

PRODUCT_COPY_FILES += \
    $(DEVICE_PATH)/init.ossi.rc:$(TARGET_COPY_OUT_VENDOR)/etc/init/init.ossi.rc

DEVICE_PACKAGE_OVERLAYS += $(DEVICE_PATH)/overlay

PRODUCT_PACKAGES += \
    android.hardware.vibrator.service.oplus-richtap

PRODUCT_SOONG_NAMESPACES += \
    $(DEVICE_PATH) \
    device/realme/sm8550-ogki

# Platform common (same SoC): HAL packages, init scripts, vintf manifests, overlays
# and the firmware mountpoints. Its BoardConfigCommon is deliberately NOT inherited —
# BoardConfigOgki.mk keeps BOARD_USES_GENERIC_KERNEL_IMAGE=false.
$(call inherit-product, device/oneplus/sm8550-common/common.mk)

$(call inherit-product, vendor/realme/ossi/ossi-vendor.mk)
