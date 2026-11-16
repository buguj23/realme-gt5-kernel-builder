LOCAL_PATH := $(call my-dir)
DEVICE_PATH := device/realme/ossi

PRODUCT_AAPT_CONFIG := normal
PRODUCT_AAPT_PREF_CONFIG := xxxhdpi

# GT5 panel 6.74" 2772x1240 @ 144Hz
TARGET_SCREEN_HEIGHT := 2772
TARGET_SCREEN_WIDTH := 1240

PRODUCT_SHIPPING_API_LEVEL := 36

# fstab: ext4 metadata (stock). Copied into vendor_ramdisk AND vendor.
PRODUCT_COPY_FILES += \
    $(DEVICE_PATH)/fstab.default:$(TARGET_COPY_OUT_VENDOR_RAMDISK)/first_stage_ramdisk/fstab.default \
    $(DEVICE_PATH)/fstab.default:$(TARGET_COPY_OUT_VENDOR)/etc/fstab.default \
    $(DEVICE_PATH)/fstab.default:$(TARGET_COPY_OUT_RECOVERY)/root/first_stage_ramdisk/fstab.default \
    $(DEVICE_PATH)/fstab.default:$(TARGET_COPY_OUT_VENDOR_RAMDISK)/fstab.default

PRODUCT_COPY_FILES += \
    $(DEVICE_PATH)/init.ossi.rc:$(TARGET_COPY_OUT_VENDOR)/etc/init/init.ossi.rc

# YukiSU LKM next to first-stage modules when present
ifneq ($(wildcard $(DEVICE_PATH)/prebuilt/kernelsu.ko),)
PRODUCT_COPY_FILES += \
    $(DEVICE_PATH)/prebuilt/kernelsu.ko:$(TARGET_COPY_OUT_VENDOR_DLKM)/lib/modules/kernelsu.ko
endif

DEVICE_PACKAGE_OVERLAYS += $(DEVICE_PATH)/overlay

PRODUCT_PACKAGES += \
    android.hardware.vibrator.service.oplus-richtap

PRODUCT_SOONG_NAMESPACES += \
    $(DEVICE_PATH) \
    device/realme/sm8550-ogki

# Do not inherit Lineage sm8550-common (GKI). Vendor blobs still come from extract.
$(call inherit-product-if-exists, vendor/realme/ossi/ossi-vendor.mk)
