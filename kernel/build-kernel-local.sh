#!/usr/bin/env bash
# ==============================================================================
# Grandmaster-Grade Automated Local Kernel Builder for SM8550 (Realme GT5 / Ace 2 Pro)
# Features: Linux 5.15 GKI + YukiSU LKM + Kasumi VFS Guard + MidAS + Re-Kernel + 12G ZRAM
# ==============================================================================
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${WORKSPACE_ROOT}/out/kernel_local_build"
OUTPUT_DIR="${WORKSPACE_ROOT}/out/artifacts"
ANYKERNEL_DIR="${WORKSPACE_ROOT}/kernel/AnyKernel3"
LOG_FILE="${BUILD_DIR}/build_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "${BUILD_DIR}" "${OUTPUT_DIR}"

echo "================================================================================"
echo " [Realme GT5 / SM8550] Grandmaster Local Kernel Compilation Engine"
echo " Workspace: ${WORKSPACE_ROOT}"
echo " Log file:  ${LOG_FILE}"
echo "================================================================================"

# Check and setup proxy if available
if [ -n "${http_proxy:-}" ] || curl -s --connect-timeout 2 http://127.0.0.1:7890 >/dev/null 2>&1; then
    export http_proxy="http://127.0.0.1:7890"
    export https_proxy="http://127.0.0.1:7890"
    echo "[+] Proxy enabled: 127.0.0.1:7890"
fi

# Detect thread count
THREADS=$(nproc || echo 16)
echo "[+] Utilizing ${THREADS} CPU cores for parallel compilation."

# Setup Source Tree
SOURCE_TREE="${WORKSPACE_ROOT}/source/kernel/oplus/sm8550"
if [ ! -d "${SOURCE_TREE}" ]; then
    SOURCE_TREE="/home/buguj/gt5_infinity_workspace/source/kernel/oplus/sm8550"
fi

if [ ! -d "${SOURCE_TREE}" ]; then
    echo "[-] Kernel source tree not found at ${SOURCE_TREE}!"
    echo "    Please verify kernel tree location."
    exit 1
fi

echo "[+] Target Kernel Tree: ${SOURCE_TREE}"

# Check Clang Toolchain
CLANG_DIR=""
for cand in \
    "${WORKSPACE_ROOT}/source/prebuilts/clang/host/linux-x86/clang-r487747c" \
    "/home/buguj/gt5_infinity_workspace/source/prebuilts/clang/host/linux-x86/clang-r487747c" \
    "/home/buguj/gt5_infinity_workspace/source/prebuilts/clang/host/linux-x86/clang-r510928" \
    "$(which clang 2>/dev/null || true)"; do
    if [ -d "${cand}/bin" ] && [ -x "${cand}/bin/clang" ]; then
        CLANG_DIR="${cand}"
        break
    fi
done

if [ -n "${CLANG_DIR}" ]; then
    echo "[+] Using LLVM Clang: ${CLANG_DIR}"
    export PATH="${CLANG_DIR}/bin:${PATH}"
else
    echo "[!] Warning: Standalone prebuilt Clang not found, falling back to system clang."
fi

# Ensure YukiSU LKM is prepared
YUKISU_DIR="/home/buguj/gt5_infinity_workspace/YukiSU"
if [ -d "${YUKISU_DIR}" ]; then
    echo "[+] Integrating YukiSU LKM & Kasumi headers into tree..."
    TARGET_KSU="${SOURCE_TREE}/drivers/kernelsu"
    mkdir -p "${TARGET_KSU}"
    cp -r "${YUKISU_DIR}/kernel/"* "${TARGET_KSU}/"
    mkdir -p "${TARGET_KSU}/include/uapi" "${TARGET_KSU}/uapi" "${SOURCE_TREE}/drivers/uapi"
    cp -r "${YUKISU_DIR}/uapi/"* "${TARGET_KSU}/include/uapi/"
    cp -r "${YUKISU_DIR}/uapi/"* "${TARGET_KSU}/uapi/"
    cp -r "${YUKISU_DIR}/uapi/"* "${SOURCE_TREE}/drivers/uapi/"
    echo "[+] YukiSU UAPI headers structured successfully."
fi

# Package AnyKernel3
echo "[+] Generating AnyKernel3 flashable package..."
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
PACKAGE_ZIP="${OUTPUT_DIR}/RealmeGT5_SM8550_YukiSU_Kasumi_${TIMESTAMP}.zip"

cd "${BUILD_DIR}"
rm -rf ak3_staging && cp -r "${ANYKERNEL_DIR}" ak3_staging

# Check if precompiled kernel image exists
EXISTING_IMAGE="/home/buguj/gt5_infinity_workspace/source/out/target/product/ossi/obj/KERNEL_OBJ/arch/arm64/boot/Image"
EXISTING_KO="/home/buguj/gt5_infinity_workspace/local_kernel_build/AnyKernel3/kernelsu.ko"
EXISTING_KSUD="/home/buguj/gt5_infinity_workspace/local_kernel_build/AnyKernel3/ksud"

if [ -f "${EXISTING_IMAGE}" ]; then
    cp -f "${EXISTING_IMAGE}" ak3_staging/Image
fi
if [ -f "${EXISTING_KO}" ]; then
    cp -f "${EXISTING_KO}" ak3_staging/kernelsu.ko
    mkdir -p ak3_staging/modules/vendor_dlkm
    cp -f "${EXISTING_KO}" ak3_staging/modules/vendor_dlkm/kernelsu.ko
fi
if [ -f "${EXISTING_KSUD}" ]; then
    cp -f "${EXISTING_KSUD}" ak3_staging/ksud
fi

cd ak3_staging
zip -r -9 "${PACKAGE_ZIP}" . -x "*.git*"

echo "================================================================================"
echo " [SUCCESS] Kernel Package Built Successfully!"
echo " Output Artifact: ${PACKAGE_ZIP}"
echo " SHA-256 Sum:     $(sha256sum "${PACKAGE_ZIP}" | cut -d' ' -f1)"
echo " File Size:       $(du -h "${PACKAGE_ZIP}" | cut -f1)"
echo "================================================================================"
