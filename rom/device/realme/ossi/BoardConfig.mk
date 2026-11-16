#
# Realme GT5 (ossi / RMX3820 / RE5C33) — OEM OGKI kernel, not Google GKI.
#

DEVICE_PATH := device/realme/ossi

# Super: same kalama envelope as OnePlus 11 / Ace2 Pro
BOARD_SUPER_PARTITION_SIZE := 16940199936

include device/realme/sm8550-ogki/BoardConfigOgki.mk
-include $(DEVICE_PATH)/branch.mk

# Assert
TARGET_OTA_ASSERT_DEVICE := ossi,RMX3820,RE5C33,Ossi,RealmeGT5

# Display
TARGET_SCREEN_DENSITY := 480

# Recovery UI
TARGET_RECOVERY_UI_MARGIN_HEIGHT := 103

-include vendor/realme/ossi/BoardConfigVendor.mk
