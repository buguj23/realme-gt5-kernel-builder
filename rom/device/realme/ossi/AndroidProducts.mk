#
# Copyright (C) 2024-2026 The LineageOS Project
# Copyright (C) 2026 Project Infinity-X
#
# SPDX-License-Identifier: Apache-2.0
#

PRODUCT_MAKEFILES := \
    $(LOCAL_DIR)/infinity_ossi.mk \
    $(LOCAL_DIR)/lineage_ossi.mk

COMMON_LUNCH_CHOICES := \
    infinity_ossi-user \
    infinity_ossi-userdebug \
    infinity_ossi-eng \
    lineage_ossi-user \
    lineage_ossi-userdebug \
    lineage_ossi-eng
