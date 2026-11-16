$(call inherit-product, $(SRC_TARGET_DIR)/product/core_64_bit_only.mk)
$(call inherit-product, $(SRC_TARGET_DIR)/product/full_base_telephony.mk)
$(call inherit-product, device/realme/ossi/device.mk)
$(call inherit-product-if-exists, vendor/lineage/config/common_full_phone.mk)

PRODUCT_NAME := lineage_ossi
PRODUCT_DEVICE := ossi
PRODUCT_BRAND := realme
PRODUCT_MODEL := RMX3820
PRODUCT_MANUFACTURER := realme

PRODUCT_GMS_CLIENTID_BASE := android-oppo
