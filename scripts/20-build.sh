#!/usr/bin/env bash
# 20-build.sh — Build Realme GT5 (5.15.149) OEM OGKI kernel, then optional YukiSU LKM against same Module.symvers.
set -euo pipefail

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=scripts/lib-kernel.sh
source "$REPO_DIR/scripts/lib-kernel.sh"
enable_local_proxy_if_up

KP_DIR=${KP_DIR:-$HOME/gt5_kernel_5_15_149/kernel_platform}
C=$KP_DIR/common
KBUILD_OUT=${KBUILD_OUT:-$C/out}
CPUD=${CPUD:-kalama}
BUILD_METHOD=${BUILD_METHOD:-gki}
FAST_BUILD=${FAST_BUILD:-1}
LTO=${LTO:-thin}
KSU_MODE=${KSU_MODE:-Pure-OGKI}   # Pure-OGKI | YukiSU-LKM

APPLY_TMPFS=${APPLY_TMPFS:-0}
APPLY_NETFILTER=${APPLY_NETFILTER:-0}
APPLY_BBRV3=${APPLY_BBRV3:-0}
APPLY_DROIDSPACES=${APPLY_DROIDSPACES:-0}
APPLY_REKERNEL=${APPLY_REKERNEL:-0}
APPLY_ZRAM=${APPLY_ZRAM:-0}
APPLY_BBG=${APPLY_BBG:-0}

[ -d "$C" ] || { echo "missing $C — run scripts/00-fetch.sh" >&2; exit 1; }
case "$KSU_MODE" in
  Pure-OGKI|YukiSU-LKM) ;;
  *) echo "ERROR: unsupported KSU_MODE=$KSU_MODE (allowed: Pure-OGKI, YukiSU-LKM)" >&2; exit 2 ;;
esac
case "$LTO" in
  thin|full|none) ;;
  *) echo "ERROR: unsupported LTO=$LTO (allowed: thin, full, none)" >&2; exit 2 ;;
esac

export KMI_SYMBOL_LIST_STRICT_MODE=0
export SYSTEM_DLKM_RE_SIGN=0
export BUILD_SYSTEM_DLKM=${BUILD_SYSTEM_DLKM:-0}

setup_kernel_toolchain "$KP_DIR" "$C" "$REPO_DIR"

if [ "$FAST_BUILD" = 1 ]; then
  echo "OGKI Kbuild (FAST_BUILD=1, KSU_MODE=$KSU_MODE, LTO=$LTO): $C -> $KBUILD_OUT"
  make -C "$C" O="$KBUILD_OUT" "${KERNEL_MAKE_ARGS[@]}" gki_defconfig

  apply_config_fragment "$C" "$KBUILD_OUT/.config" "$REPO_DIR/configs/features.config"
  [ "$APPLY_TMPFS" = 1 ] && apply_config_fragment "$C" "$KBUILD_OUT/.config" "$REPO_DIR/configs/fragments/tmpfs.config"
  [ "$APPLY_NETFILTER" = 1 ] && apply_config_fragment "$C" "$KBUILD_OUT/.config" "$REPO_DIR/configs/fragments/netfilter.config"
  [ "$APPLY_BBRV3" = 1 ] && apply_config_fragment "$C" "$KBUILD_OUT/.config" "$REPO_DIR/configs/fragments/bbrv3.config"
  [ "$APPLY_DROIDSPACES" = 1 ] && apply_config_fragment "$C" "$KBUILD_OUT/.config" "$REPO_DIR/configs/fragments/droidspaces.config"
  [ "$APPLY_REKERNEL" = 1 ] && apply_config_fragment "$C" "$KBUILD_OUT/.config" "$REPO_DIR/configs/fragments/rekern.config"
  [ "$APPLY_ZRAM" = 1 ] && apply_config_fragment "$C" "$KBUILD_OUT/.config" "$REPO_DIR/configs/fragments/zram_lz4kd.config"
  [ "$APPLY_BBG" = 1 ] && "$C/scripts/config" --file "$KBUILD_OUT/.config" -e BBG

  case "$LTO" in
    thin) "$C/scripts/config" --file "$KBUILD_OUT/.config" -e LTO_CLANG -e LTO_CLANG_THIN -d LTO_CLANG_NONE -d LTO_CLANG_FULL ;;
    full) "$C/scripts/config" --file "$KBUILD_OUT/.config" -e LTO_CLANG -e LTO_CLANG_FULL -d LTO_CLANG_NONE -d LTO_CLANG_THIN ;;
    none) "$C/scripts/config" --file "$KBUILD_OUT/.config" -d LTO_CLANG -e LTO_CLANG_NONE -d LTO_CLANG_THIN -d LTO_CLANG_FULL ;;
  esac

  make -C "$C" O="$KBUILD_OUT" "${KERNEL_MAKE_ARGS[@]}" olddefconfig
  make -C "$C" -j"$(nproc)" O="$KBUILD_OUT" "${KERNEL_MAKE_ARGS[@]}"
  make -C "$C" O="$KBUILD_OUT" "${KERNEL_MAKE_ARGS[@]}" headers_install
else
  cd "$KP_DIR/.."
  if [ -f ./kernel_platform/build_with_bazel.py ]; then
    ./kernel_platform/oplus/bazel/oplus_modules_variant.sh "$CPUD" "$BUILD_METHOD"
    ./kernel_platform/build_with_bazel.py -t "$CPUD" "$BUILD_METHOD"
  else
    ./kernel_platform/oplus/build/oplus_build_kernel.sh "$CPUD" "$BUILD_METHOD"
  fi
fi

# Locate actual KBUILD_OUT when vendor build script placed it under out/
if [ ! -f "$KBUILD_OUT/Module.symvers" ]; then
  sym=$(find "$KP_DIR" -name Module.symvers -type f 2>/dev/null | head -n1 || true)
  [ -n "$sym" ] && KBUILD_OUT=$(dirname "$sym")
fi
[ -f "$KBUILD_OUT/arch/arm64/boot/Image" ] && [ -f "$KBUILD_OUT/Module.symvers" ] || {
  echo "ERROR: Image or Module.symvers missing after build" >&2
  exit 1
}

if [ "$KSU_MODE" = "YukiSU-LKM" ]; then
  bash "$REPO_DIR/scripts/integrate-yukisu.sh" \
    --kp-dir "$KP_DIR" --src "$C" --kdir "$KBUILD_OUT" \
    --output "$KBUILD_OUT" --yukizygisk "${ENABLE_YUKIZYGISK:-1}" \
    ${KSU_SUPERKEY:+--superkey "$KSU_SUPERKEY"} \
    ${KSU_MANAGER_PACKAGE:+--manager-pkg "$KSU_MANAGER_PACKAGE"}
fi

if [ -n "${STOCK_MODULES_DIR:-}" ] && [ -d "$STOCK_MODULES_DIR" ]; then
  python3 "$REPO_DIR/scripts/40-verify-crc.py" "$KBUILD_OUT/Module.symvers" "$STOCK_MODULES_DIR"
fi

echo "Build complete:"
echo "  Image          : $KBUILD_OUT/arch/arm64/boot/Image"
echo "  Module.symvers : $KBUILD_OUT/Module.symvers"
echo "  Config         : $KBUILD_OUT/.config"
echo "  vmlinux        : $KBUILD_OUT/vmlinux"
if [ -f "$KBUILD_OUT/kernelsu.ko" ]; then
  echo "  kernelsu.ko    : $KBUILD_OUT/kernelsu.ko"
fi
