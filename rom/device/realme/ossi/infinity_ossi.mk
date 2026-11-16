$(call inherit-product, $(SRC_TARGET_DIR)/product/core_64_bit_only.mk)
$(call inherit-product, $(SRC_TARGET_DIR)/product/full_base_telephony.mk)
$(call inherit-product, device/realme/ossi/device.mk)
$(call inherit-product-if-exists, vendor/infinity/config/common_full_phone.mk)
$(call inherit-product-if-exists, vendor/lineage/config/common_full_phone.mk)

PRODUCT_NAME := infinity_ossi
PRODUCT_DEVICE := ossi
PRODUCT_BRAND := realme
PRODUCT_MODEL := RMX3820
PRODUCT_MANUFACTURER := realme

PRODUCT_GMS_CLIENTID_BASE := android-oppo

PRODUCT_BUILD_PROP_OVERRIDES += \
    DeviceName=RE5C33 \
    DeviceProduct=RMX3820 \
    SystemDevice=RE5C33 \
    SystemName=RMX3820 \
    BuildDesc="RMX3820-user 16" \
    BuildFingerprint=realme/RMX3820/RE5C33:16/UKQ1.230924.001/user/release-keys
