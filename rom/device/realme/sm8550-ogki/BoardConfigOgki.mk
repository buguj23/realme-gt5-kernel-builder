#
# SM8550 kalama OEM OGKI board fragment for Realme GT5.
# Intentionally NOT Lineage sm8550-common: that sets
#   BOARD_USES_GENERIC_KERNEL_IMAGE := true
# which pulls Google GKI. Forbidden.
#

# A/B
AB_OTA_UPDATER := true
AB_OTA_PARTITIONS += \
    boot \
    dtbo \
    init_boot \
    odm \
    product \
    recovery \
    system \
    system_dlkm \
    system_ext \
    vbmeta \
    vbmeta_system \
    vbmeta_vendor \
    vendor \
    vendor_boot \
    vendor_dlkm

# Architecture
TARGET_ARCH := arm64
TARGET_ARCH_VARIANT := armv8-2a-dotprod
TARGET_CPU_ABI := arm64-v8a
TARGET_CPU_VARIANT := generic
TARGET_CPU_VARIANT_RUNTIME := kryo300

# Bootloader / platform
TARGET_BOOTLOADER_BOARD_NAME := kalama
TARGET_BOARD_PLATFORM := kalama
BOARD_USES_QCOM_HARDWARE := true
BOARD_USES_QCOM_MERGE_DTBS_SCRIPT := true

# Audio HAL (kalama AGM/PAL), taken from the same-SoC common board config.
AUDIO_FEATURE_ENABLED_DLKM := true
AUDIO_FEATURE_ENABLED_EXTENDED_COMPRESS_FORMAT := true
AUDIO_FEATURE_ENABLED_GEF_SUPPORT := true
AUDIO_FEATURE_ENABLED_GKI := true
AUDIO_FEATURE_ENABLED_INSTANCE_ID := true
AUDIO_FEATURE_ENABLED_AGM_HIDL := true
AUDIO_FEATURE_ENABLED_PAL_HIDL := true
AUDIO_FEATURE_ENABLED_PROXY_DEVICE := true
AUDIO_FEATURE_ENABLED_SSR := true
AUDIO_FEATURE_ENABLED_SVA_MULTI_STAGE := true
BOARD_SUPPORTS_OPENSOURCE_STHAL := true
BOARD_SUPPORTS_SOUND_TRIGGER := true
BOARD_USES_ALSA_AUDIO := true
TARGET_PROVIDES_AUDIO_HAL := true
TARGET_PROVIDES_LIBAGM := true
TARGET_PROVIDES_LIBAR_PAL := true

# Boot images
BOARD_BOOT_HEADER_VERSION := 4
BOARD_MKBOOTIMG_ARGS += --header_version $(BOARD_BOOT_HEADER_VERSION) --os_version 13.0.0 --os_patch_level $(BOOT_SECURITY_PATCH)
BOARD_RAMDISK_USE_LZ4 := true
BOARD_INIT_BOOT_HEADER_VERSION := 4
BOARD_MKBOOTIMG_INIT_ARGS += --header_version $(BOARD_INIT_BOOT_HEADER_VERSION) --os_version 13.0.0 --os_patch_level $(BOOT_SECURITY_PATCH)

# ---- KERNEL: OEM OGKI, never Google GKI ----
BOARD_USES_GENERIC_KERNEL_IMAGE := false
BOARD_KERNEL_IMAGE_NAME := Image
BOARD_KERNEL_BASE := 0x00000000
BOARD_KERNEL_PAGESIZE := 4096
BOARD_INCLUDE_DTB_IN_BOOTIMG := true
TARGET_NEEDS_DTBOIMAGE := true
TARGET_NO_KERNEL := false

BOARD_BOOTCONFIG := \
    androidboot.hardware=qcom \
    androidboot.memcg=1 \
    androidboot.usbcontroller=a600000.dwc3

BOARD_KERNEL_CMDLINE := video=vfb:640x400,bpp=32,memsize=3072000 nosoftlockup

# Source = Action-Build OGKI common (scripts/00-fetch.sh)
TARGET_KERNEL_SOURCE := kernel/oneplus/sm8550
TARGET_KERNEL_CONFIG := gki_defconfig
TARGET_KERNEL_CLANG_COMPILE := true
TARGET_KERNEL_ADDITIONAL_FLAGS := CONFIG_OPLUS_DEVICE_DTBS=y CONFIG_KSU=m

# Platform properties and filesystem labels come with the same-SoC common tree.
OGKI_COMMON_PATH := device/oneplus/sm8550-common
TARGET_ODM_PROP += $(OGKI_COMMON_PATH)/properties/odm.prop
TARGET_PRODUCT_PROP += $(OGKI_COMMON_PATH)/properties/product.prop
TARGET_SYSTEM_EXT_PROP += $(OGKI_COMMON_PATH)/properties/system_ext.prop
TARGET_VENDOR_PROP += $(OGKI_COMMON_PATH)/properties/vendor.prop
TARGET_FS_CONFIG_GEN := $(OGKI_COMMON_PATH)/config.fs
BOARD_PRODUCTIMAGE_MINIMAL_PARTITION_RESERVED_SIZE := false
-include vendor/lineage/config/BoardConfigReservedSize.mk

# Prebuilt kernel + modules, staged by scripts/rom-stage-kernel.py from one
# kernel package (Image + every .ko + Module.symvers of the same build).
# The generated file also sets BOARD_VENDOR_RAMDISK_KERNEL_MODULES[_LOAD],
# BOARD_VENDOR_KERNEL_MODULES[_LOAD] and BOARD_SYSTEM_KERNEL_MODULES[_LOAD].
$(foreach f,Image dtb/ossi.dtb dtbo.img kernel-modules.mk,$(if $(wildcard $(DEVICE_PATH)/prebuilt/$(f)),,$(error Incomplete OGKI staging, missing $(f))))
include $(DEVICE_PATH)/prebuilt/kernel-modules.mk

TARGET_KERNEL_EXT_MODULE_ROOT := kernel/oneplus/sm8550-modules
TARGET_KERNEL_EXT_MODULES := \
    qcom/opensource/mmrm-driver \
    qcom/opensource/mm-drivers/hw_fence \
    qcom/opensource/mm-drivers/msm_ext_display \
    qcom/opensource/mm-drivers/sync_fence \
    qcom/opensource/audio-kernel \
    qcom/opensource/camera-kernel \
    qcom/opensource/dataipa/drivers/platform/msm \
    qcom/opensource/datarmnet/core \
    qcom/opensource/datarmnet-ext/aps \
    qcom/opensource/datarmnet-ext/offload \
    qcom/opensource/datarmnet-ext/shs \
    qcom/opensource/datarmnet-ext/perf \
    qcom/opensource/datarmnet-ext/perf_tether \
    qcom/opensource/datarmnet-ext/sch \
    qcom/opensource/datarmnet-ext/wlan \
    qcom/opensource/securemsm-kernel \
    qcom/opensource/display-drivers/msm \
    qcom/opensource/eva-kernel \
    qcom/opensource/video-driver \
    qcom/opensource/graphics-kernel \
    qcom/opensource/wlan/platform \
    qcom/opensource/wlan/qcacld-3.0/.kiwi_v2 \
    qcom/opensource/bt-kernel \
    nxp/opensource/driver \
    oplus/kernel/explorer

# Metadata: stock 16.0.3.500 vendor_boot fstab mounts /metadata as f2fs
# (verified with unpack_bootimg on stock_firmware_1603500/vendor_boot.img).
BOARD_USES_METADATA_PARTITION := true
BOARD_USES_QCOM_FBE_DECRYPTION := true
BOARD_USES_SYSTEM_DLKMIMAGE := true
BOARD_USES_VENDOR_DLKMIMAGE := true

# Partitions
BOARD_FLASH_BLOCK_SIZE := 262144
BOARD_BOOTIMAGE_PARTITION_SIZE := 201326592
BOARD_DTBOIMG_PARTITION_SIZE := 25165824
BOARD_INIT_BOOT_IMAGE_PARTITION_SIZE := 8388608
BOARD_VENDOR_BOOTIMAGE_PARTITION_SIZE := 201326592
BOARD_RECOVERYIMAGE_PARTITION_SIZE := 104857600
BOARD_USERDATAIMAGE_PARTITION_SIZE := 233871900672

# DLKM filesystem types come from the actual stock images in kernel-modules.mk.
BOARD_ODMIMAGE_FILE_SYSTEM_TYPE := erofs
BOARD_PRODUCTIMAGE_FILE_SYSTEM_TYPE := ext4
BOARD_SYSTEM_EXTIMAGE_FILE_SYSTEM_TYPE := ext4
BOARD_SYSTEMIMAGE_FILE_SYSTEM_TYPE := ext4
BOARD_VENDORIMAGE_FILE_SYSTEM_TYPE := erofs

# Populate the group, physical super capacity, and all confirmed OEM mounts.
$(foreach f,oem-partitions.mk fstab.ossi oem-avb-keys/*.avbpubkey,$(if $(wildcard $(DEVICE_PATH)/prebuilt/$(f)),,$(error Incomplete OEM staging, missing $(f))))
include $(DEVICE_PATH)/prebuilt/oem-partitions.mk
ifeq ($(strip $(OGKI_STAGED_OEM_PARTITIONS)),)
$(error OEM partition manifest is empty)
endif
$(foreach partition,$(OGKI_STAGED_OEM_PARTITIONS),$(if $(wildcard $(DEVICE_PATH)/prebuilt/oem_partitions/$(partition).img),,$(error Missing OEM image $(partition).img)))

TARGET_COPY_OUT_ODM := odm
TARGET_COPY_OUT_PRODUCT := product
TARGET_COPY_OUT_SYSTEM_DLKM := system_dlkm
TARGET_COPY_OUT_SYSTEM_EXT := system_ext
TARGET_COPY_OUT_VENDOR := vendor
TARGET_COPY_OUT_VENDOR_DLKM := vendor_dlkm

# Recovery
BOARD_EXCLUDE_KERNEL_FROM_RECOVERY_IMAGE := true
TARGET_RECOVERY_FSTAB := $(DEVICE_PATH)/prebuilt/fstab.ossi
TARGET_RECOVERY_PIXEL_FORMAT := RGBX_8888
TARGET_USERIMAGES_USE_EXT4 := true
TARGET_USERIMAGES_USE_F2FS := true

# AVB verification remains enabled. The local builder's default certificate is
# for userdebug. Production signing is a separate release configuration.
ifeq ($(TARGET_BUILD_VARIANT),user)
$(error The ossi overlay is configured for userdebug builds)
endif
BOARD_AVB_ENABLE := true
BOARD_MOVE_GSI_AVB_KEYS_TO_VENDOR_BOOT := true
OSSI_AVB_KEY ?= external/avb/test/data/testkey_rsa4096.pem
BOARD_AVB_KEY_PATH := $(OSSI_AVB_KEY)
BOARD_AVB_ALGORITHM := SHA256_RSA4096
OSSI_BOOT_ROLLBACK_INDEX := $(shell date -u -d '$(BOOT_SECURITY_PATCH)' +%s)

BOARD_AVB_BOOT_KEY_PATH := $(OSSI_AVB_KEY)
BOARD_AVB_BOOT_ALGORITHM := SHA256_RSA4096
BOARD_AVB_BOOT_ROLLBACK_INDEX := $(OSSI_BOOT_ROLLBACK_INDEX)
BOARD_AVB_BOOT_ROLLBACK_INDEX_LOCATION := 4

BOARD_AVB_DTBO_KEY_PATH := $(OSSI_AVB_KEY)
BOARD_AVB_DTBO_ALGORITHM := SHA256_RSA4096
BOARD_AVB_DTBO_ROLLBACK_INDEX := $(OSSI_BOOT_ROLLBACK_INDEX)
BOARD_AVB_DTBO_ROLLBACK_INDEX_LOCATION := 3

BOARD_AVB_RECOVERY_KEY_PATH := $(OSSI_AVB_KEY)
BOARD_AVB_RECOVERY_ALGORITHM := SHA256_RSA4096
BOARD_AVB_RECOVERY_ROLLBACK_INDEX := $(OSSI_BOOT_ROLLBACK_INDEX)
BOARD_AVB_RECOVERY_ROLLBACK_INDEX_LOCATION := 1

BOARD_AVB_VBMETA_SYSTEM := system system_dlkm system_ext product
BOARD_AVB_VBMETA_SYSTEM_KEY_PATH := $(OSSI_AVB_KEY)
BOARD_AVB_VBMETA_SYSTEM_ALGORITHM := SHA256_RSA4096
BOARD_AVB_VBMETA_SYSTEM_ROLLBACK_INDEX := $(PLATFORM_SECURITY_PATCH_TIMESTAMP)
BOARD_AVB_VBMETA_SYSTEM_ROLLBACK_INDEX_LOCATION := 2

BOARD_AVB_VBMETA_VENDOR := odm vendor vendor_dlkm
BOARD_AVB_VBMETA_VENDOR_KEY_PATH := $(OSSI_AVB_KEY)
BOARD_AVB_VBMETA_VENDOR_ALGORITHM := SHA256_RSA4096
BOARD_AVB_VBMETA_VENDOR_ROLLBACK_INDEX := $(OSSI_BOOT_ROLLBACK_INDEX)
BOARD_AVB_VBMETA_VENDOR_ROLLBACK_INDEX_LOCATION := 5

BOARD_AVB_VENDOR_BOOT_KEY_PATH := $(OSSI_AVB_KEY)
BOARD_AVB_VENDOR_BOOT_ALGORITHM := SHA256_RSA4096
BOARD_AVB_VENDOR_BOOT_ROLLBACK_INDEX := $(OSSI_BOOT_ROLLBACK_INDEX)
BOARD_AVB_VENDOR_BOOT_ROLLBACK_INDEX_LOCATION := 6

# WiFi
BOARD_WLAN_DEVICE := qcwcn
BOARD_HOSTAPD_DRIVER := NL80211
BOARD_HOSTAPD_PRIVATE_LIB := lib_driver_cmd_$(BOARD_WLAN_DEVICE)
BOARD_WPA_SUPPLICANT_DRIVER := $(BOARD_HOSTAPD_DRIVER)
BOARD_WPA_SUPPLICANT_PRIVATE_LIB := lib_driver_cmd_$(BOARD_WLAN_DEVICE)
BOARD_WPA_SUPPLICANT_PRIVATE_LIB_EVENT := "ON"
WIFI_FEATURE_HOSTAPD_11AX := true
WIFI_HIDL_FEATURE_AWARE := true
WIFI_HIDL_FEATURE_DUAL_INTERFACE := true
WIFI_HIDL_UNIFIED_SUPPLICANT_SERVICE_RC_ENTRY := true
WIFI_DRIVER_STATE_CTRL_PARAM := "/dev/wlan"
WIFI_DRIVER_STATE_OFF := "OFF"
WIFI_DRIVER_STATE_ON := "ON"
WPA_SUPPLICANT_VERSION := VER_0_8_X

# RIL
ENABLE_VENDOR_RIL_SERVICE := true

# SEPolicy
include device/qcom/sepolicy_vndr/SEPolicy.mk
include hardware/oplus/sepolicy/qti/SEPolicy.mk
BOARD_VENDOR_SEPOLICY_DIRS += $(DEVICE_PATH)/sepolicy/vendor
