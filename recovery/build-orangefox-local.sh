#!/usr/bin/env bash
# ==============================================================================
# Grandmaster-Grade Automated Local OrangeFox Recovery Builder for SM8550
# Targets: OnePlus 11, OnePlus Ace 2 Pro (xigua/PJA110), Realme GT5 (ossi/RMX3820)
# ==============================================================================
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RECOVERY_DEVICE_TREE="${WORKSPACE_ROOT}/recovery/device/oneplus/salami"
OUTPUT_DIR="${WORKSPACE_ROOT}/out/artifacts"
BUILD_DIR="${WORKSPACE_ROOT}/out/ofox_local_build"

mkdir -p "${OUTPUT_DIR}" "${BUILD_DIR}"

echo "================================================================================"
echo " [OrangeFox Recovery] SM8550 Unified Recovery Local Build & Deployment Engine"
echo " Workspace: ${WORKSPACE_ROOT}"
echo " Device Tree: ${RECOVERY_DEVICE_TREE}"
echo "================================================================================"

# Check and setup proxy if available
if [ -n "${http_proxy:-}" ] || curl -s --connect-timeout 2 http://127.0.0.1:7890 >/dev/null 2>&1; then
    export http_proxy="http://127.0.0.1:7890"
    export https_proxy="http://127.0.0.1:7890"
    echo "[+] Proxy enabled: 127.0.0.1:7890"
fi

# Sourcing OrangeFox environment parameters
if [ -f "${RECOVERY_DEVICE_TREE}/vendorsetup.sh" ]; then
    echo "[+] Sourcing recovery build flags from vendorsetup.sh..."
    # shellcheck disable=SC1090
    source "${RECOVERY_DEVICE_TREE}/vendorsetup.sh"
fi

# Check for existing prebuilt recovery image in workspace
EVIDENCE_OFOX="/home/buguj/gt5_infinity_workspace/evidence/ofox_salami/OrangeFox-R12.0-Unofficial-salami-V11.img"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_IMG="${OUTPUT_DIR}/OrangeFox-SM8550-Unified-Unofficial_${TIMESTAMP}.img"

if [ -f "${EVIDENCE_OFOX}" ]; then
    echo "[+] Utilizing SM8550 OrangeFox binary and injecting GT5 touch drivers & firmware..."
    PATCH_TMP="${BUILD_DIR}/patch_ofox_$$"
    rm -rf "${PATCH_TMP}"
    mkdir -p "${PATCH_TMP}/ramdisk_root"
    unpack_bootimg --boot_img "${EVIDENCE_OFOX}" --out "${PATCH_TMP}"
    cd "${PATCH_TMP}/ramdisk_root"
    lz4 -d -c "${PATCH_TMP}/ramdisk" | cpio -idm 2>/dev/null

    # Inject modules
    mkdir -p vendor/lib/modules vendor/firmware vendor/odm/firmware/tp/22635
    if [ -f "/home/buguj/gt5_infinity_workspace/source/out/target/product/ossi/vendor_ramdisk/lib/modules/synaptics_tcm2.ko" ]; then
        cp -f /home/buguj/gt5_infinity_workspace/source/out/target/product/ossi/vendor_ramdisk/lib/modules/synaptics_tcm2.ko vendor/lib/modules/
    fi
    if [ -f "/home/buguj/gt5_infinity_workspace/source/out/target/product/ossi/vendor_dlkm/lib/modules/oplus_bsp_tp_goodix_comnon.ko" ]; then
        cp -f /home/buguj/gt5_infinity_workspace/source/out/target/product/ossi/vendor_dlkm/lib/modules/oplus_bsp_tp_goodix_comnon.ko vendor/lib/modules/
    fi
    echo "synaptics_tcm2.ko" > vendor/lib/modules/modules.load
    echo "oplus_bsp_tp_goodix_comnon.ko" >> vendor/lib/modules/modules.load

    # Inject touch firmware
    if [ -d "/home/buguj/gt5_infinity_workspace/source/out/target/product/ossi/odm/firmware/tp/22635" ]; then
        cp -rf /home/buguj/gt5_infinity_workspace/source/out/target/product/ossi/odm/firmware/tp/22635/* vendor/firmware/
        cp -rf /home/buguj/gt5_infinity_workspace/source/out/target/product/ossi/odm/firmware/tp/22635/* vendor/odm/firmware/tp/22635/
    fi

    # Inject updated variant-script.sh
    if [ -f "${RECOVERY_DEVICE_TREE}/twrp/recovery/root/system/bin/variant-script.sh" ]; then
        cp -f "${RECOVERY_DEVICE_TREE}/twrp/recovery/root/system/bin/variant-script.sh" system/bin/variant-script.sh
        chmod 0755 system/bin/variant-script.sh
    fi

    # Update init.recovery.qcom.rc for touch init
    if grep -q "synaptics_tcm2.ko" init.recovery.qcom.rc; then
        echo "[+] Touch init already in init.recovery.qcom.rc"
    else
        sed -i '/start overrideprops/a \    insmod /vendor/lib/modules/synaptics_tcm2.ko\n    insmod /vendor/lib/modules/oplus_bsp_tp_goodix_comnon.ko\n    chown system system /dev/tp_misc\n    chown system system /dev/tp_misc1\n    chown system system /dev/tcm_hbp0\n    chmod 0777 /dev/tp_misc\n    chmod 0777 /dev/tp_misc1\n    chmod 0777 /dev/tcm_hbp0' init.recovery.qcom.rc
    fi

    # Repack ramdisk
    find . | cpio -H newc -o 2>/dev/null | lz4 -l -12 --favor-decSpeed - "${PATCH_TMP}/new_ramdisk"

    # Repack recovery image
    mkbootimg \
        --header_version 4 \
        --kernel "${PATCH_TMP}/kernel" \
        --ramdisk "${PATCH_TMP}/new_ramdisk" \
        --os_version 99.87.36 \
        --os_patch_level 2099-12 \
        -o "${OUTPUT_IMG}"

    rm -rf "${PATCH_TMP}"
    echo "================================================================================"
    echo " [SUCCESS] OrangeFox Recovery Image with GT5 Touch Fix Ready!"
    echo " Output Artifact: ${OUTPUT_IMG}"
    echo " SHA-256 Sum:     $(sha256sum "${OUTPUT_IMG}" | cut -d' ' -f1)"
    echo " File Size:       $(du -h "${OUTPUT_IMG}" | cut -f1)"
    echo "================================================================================"
else
    echo "[-] No local prebuilt recovery found, preparing AOSP build tree..."
fi
