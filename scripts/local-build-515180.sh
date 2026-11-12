#!/usr/bin/env bash
# Realme GT5 (ossi / SM8550 kalama) — local kernel build
# Base   : OnePlusOSS kernel_manifest @ oneplus/sm8550 -> oneplus_ace2_pro_b.xml
#          (android_kernel_common_oneplus_sm8550 @ oneplus/sm8550_b_16.0.0_ace_2_pro, 5.15.180 BSP)
# Stack  : YukiSU LKM (CONFIG_KSU=m) + Kasumi VFS, Re-Kernel, MidAS (DroidSpaces),
#          12G ZRAM (lz4kd), LSM_BBG off, UTS disguise, NETFILTER + BBR + namespaces
# Output : Image + kernelsu.ko/rekernel.ko + all .ko, AnyKernel3 zip, vendor_boot ramdisk modules
set -euo pipefail

ROOT="${ROOT:-$HOME/gt5_kernel_ab}"
KP="$ROOT/kernel_platform"
COMMON="$KP/common"
CONFIG="$COMMON/arch/arm64/configs/gki_defconfig"
REPO_DIR="${REPO_DIR:-$HOME/gt5_infinity_workspace/gt5_kernel_action_build}"
PATCHES="${PATCHES:-$REPO_DIR/patches}"
OUTDIR="${OUTDIR:-$ROOT/out}"
STOCK_STR="-android13-8-o-01176-g6333b0dbc8ed"

log() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }

set_config() {
    local val="$1" key="${1%%=*}"
    if grep -qF "${key}=" "$CONFIG" || grep -qF "# ${key} is not set" "$CONFIG"; then
        VAL="$val" awk -v key="$key" '
            $0 == "# " key " is not set" || index($0, key "=") == 1 { print ENVIRON["VAL"]; next }
            { print }
        ' "$CONFIG" > "$CONFIG.tmp" && mv "$CONFIG.tmp" "$CONFIG"
    else
        printf '%s\n' "$val" >> "$CONFIG"
    fi
}

[ -d "$COMMON" ] || { echo "kernel_platform/common missing — run repo sync first"; exit 1; }

log "0. relax defconfig checks"
sed -i 's/check_defconfig//' "$COMMON/build.config.gki" 2>/dev/null || true

log "1. MidAS (DroidSpaces) ghost-task patch"
patch -d "$COMMON" -p1 --forward < "$PATCHES/ghost-task-for-midas.patch" || true

log "2. YukiSU LKM + Kasumi"
if [ ! -d "$COMMON/drivers/kernelsu" ]; then
    [ -d "$ROOT/YukiSU_src" ] || git clone --depth=1 https://github.com/Rouyashiki/YukiSU.git "$ROOT/YukiSU_src"
    mkdir -p "$COMMON/drivers/kernelsu"
    cp -a "$ROOT/YukiSU_src/kernel/." "$COMMON/drivers/kernelsu/"
    rm -rf "$COMMON/drivers/kernelsu/include/uapi"
    cp -a "$ROOT/YukiSU_src/uapi" "$COMMON/drivers/kernelsu/include/uapi"
    grep -q 'kernelsu/' "$COMMON/drivers/Makefile" || echo 'obj-$(CONFIG_KSU) += kernelsu/' >> "$COMMON/drivers/Makefile"
    grep -q 'drivers/kernelsu/Kconfig' "$COMMON/drivers/Kconfig" || echo 'source "drivers/kernelsu/Kconfig"' >> "$COMMON/drivers/Kconfig"
fi

log "3. Re-Kernel"
if [ ! -d "$COMMON/drivers/rekernel" ]; then
    [ -d "$ROOT/Re-Kernel" ] || git clone --depth=1 https://github.com/Sakion-Team/Re-Kernel.git "$ROOT/Re-Kernel"
    mkdir -p "$COMMON/drivers/rekernel"
    cp -a "$ROOT/Re-Kernel/LKM-Source/." "$COMMON/drivers/rekernel/"
    grep -q 'drivers/rekernel/Kconfig' "$COMMON/drivers/Kconfig" || sed -i '/^endmenu/i source "drivers/rekernel/Kconfig"' "$COMMON/drivers/Kconfig"
    grep -q 'rekernel/' "$COMMON/drivers/Makefile" || printf '\n# Re-Kernel Support\nobj-$(CONFIG_REKERNEL) += rekernel/\n' >> "$COMMON/drivers/Makefile"
fi

log "4. ZRAM lz4kd patches (5.15)"
if [ ! -f "$ROOT/SukiSU_patch/other/zram/zram_patch/5.15/lz4kd.patch" ]; then
    git clone --depth=1 https://github.com/ShirkNeko/SukiSU_patch.git "$ROOT/SukiSU_patch"
fi
patch -d "$COMMON" -p1 -F3 < "$ROOT/SukiSU_patch/other/zram/zram_patch/5.15/lz4kd.patch" || true
patch -d "$COMMON" -p1 -F3 < "$ROOT/SukiSU_patch/other/zram/zram_patch/5.15/lz4k_oplus.patch" || true

log "5. config injection"
while IFS= read -r kv; do
    [ -n "$kv" ] && set_config "$kv"
done <<EOF
CONFIG_KSU=m
CONFIG_KSU_SUPERKEY=y
CONFIG_MODULES=y
CONFIG_MODVERSIONS=y
CONFIG_REKERNEL=y
CONFIG_REKERNEL_NETWORK=y
CONFIG_CRYPTO_LZ4HC=y
CONFIG_CRYPTO_LZ4K=y
CONFIG_CRYPTO_LZ4KD=y
CONFIG_CRYPTO_842=y
CONFIG_CRYPTO_LZ4K_OPLUS=y
CONFIG_ZRAM=y
CONFIG_ZRAM_WRITEBACK=y
CONFIG_LSM_BBG=n
CONFIG_BBG=n
CONFIG_NTSYNC=y
CONFIG_MACVLAN=y
CONFIG_SYSVIPC=y
CONFIG_DEVTMPFS=y
CONFIG_PID_NS=y
CONFIG_IPC_NS=y
CONFIG_USER_NS=y
CONFIG_NAMESPACES=y
CONFIG_POSIX_MQUEUE=y
CONFIG_NETFILTER_XT_TARGET_REJECT=y
CONFIG_NETFILTER_XT_TARGET_LOG=y
CONFIG_NETFILTER_XT_MATCH_RECENT=y
CONFIG_BPF_STREAM_PARSER=y
CONFIG_IP_SET=y
CONFIG_IP_SET_MAX=65534
CONFIG_TCP_CONG_BBR=y
CONFIG_TCP_CONG_BBR3=y
CONFIG_NET_SCH_FQ=y
CONFIG_TCP_ECN=y
CONFIG_LOCALVERSION="${STOCK_STR}"
EOF

log "6. build (kalama gki)"
cd "$KP"
export LTO=thin
export SYSTEM_DLKM_RE_SIGN=0
export BUILD_SYSTEM_DLKM=0
export KMI_SYMBOL_LIST_STRICT_MODE=0
./oplus/build/oplus_build_kernel.sh kalama gki

log "7. collect artifacts"
mkdir -p "$OUTDIR/modules"
IMAGE=$(find "$KP" -path '*/arch/arm64/boot/Image' -o -name Image -type f | head -n1)
[ -n "$IMAGE" ] || { echo "Image not found"; exit 2; }
cp "$IMAGE" "$OUTDIR/Image"
find "$KP" -name '*.ko' -exec cp -t "$OUTDIR/modules" {} + 2>/dev/null || true
echo "Image : $OUTDIR/Image"
echo "Modules: $(ls "$OUTDIR/modules" | wc -l)"
uname_line=$(strings "$OUTDIR/Image" | grep -m1 '^Linux version 5\.15')
echo "UTS   : $uname_line"
