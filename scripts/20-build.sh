#!/usr/bin/env bash
# 20-build.sh — build Action-Build OEM OGKI (kalama), then YukiSU LKM against that tree.
# The "gki" token is oplus_build_kernel.sh's OGKI flavor, not ci.android.com GKI.
set -euo pipefail

KP_DIR=${KP_DIR:-$HOME/gt5_kernel_ab/kernel_platform}
CPUD=${CPUD:-kalama}
BUILD_METHOD=${BUILD_METHOD:-gki}
FAST_BUILD=${FAST_BUILD:-1}
REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$KP_DIR"

export KMI_SYMBOL_LIST_STRICT_MODE=0
export LTO=${LTO:-thin}
export SYSTEM_DLKM_RE_SIGN=0
export BUILD_SYSTEM_DLKM=${BUILD_SYSTEM_DLKM:-0}

if [ "$FAST_BUILD" = 1 ] && [ -d common ] && [ -f common/arch/arm64/configs/gki_defconfig ]; then
  echo "FAST OGKI: make O=out gki_defconfig in OEM common (not Google GKI bootstrap)"
  make -C common O=out LLVM=1 ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
    CC=clang HOSTCC=clang HOSTLD=ld.lld LD=ld.lld LLVM_IAS=1 \
    gki_defconfig
  common/scripts/config --file common/out/.config -e LTO_CLANG -e LTO_CLANG_THIN \
    -d LTO_CLANG_NONE -d LTO_CLANG_FULL -e KPROBES -e KRETPROBES \
    -e MODULES -e MODULE_UNLOAD --set-str CONFIG_KSU m || true
  make -C common O=out LLVM=1 ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
    CC=clang HOSTCC=clang HOSTLD=ld.lld LD=ld.lld LLVM_IAS=1 olddefconfig
  make -C common -j"$(nproc)" O=out LLVM=1 ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
    CC=clang HOSTCC=clang HOSTLD=ld.lld LD=ld.lld LLVM_IAS=1
else
  if [ -f ./build_with_bazel.py ]; then
    ./oplus/bazel/oplus_modules_variant.sh "$CPUD" "$BUILD_METHOD"
    ./build_with_bazel.py -t "$CPUD" "$BUILD_METHOD"
  else
    ./oplus/build/oplus_build_kernel.sh "$CPUD" "$BUILD_METHOD"
  fi
fi

# Out-of-tree LKM fallback if in-tree kernelsu.ko was not produced.
find_kdir() {
  if [ -f common/out/vmlinux ]; then echo "$KP_DIR/common/out"; return; fi
  if [ -f out/vmlinux ]; then echo "$KP_DIR/out"; return; fi
  local v
  v=$(find "$KP_DIR" -name vmlinux -type f 2>/dev/null | head -n1)
  [ -n "$v" ] && dirname "$v"
}
KDIR=$(find_kdir || true)
KO=$(find "$KP_DIR" -name kernelsu.ko -type f 2>/dev/null | head -n1 || true)
if [ -z "$KO" ] && [ -n "${KDIR:-}" ] && [ -d "$KP_DIR/common/drivers/kernelsu" ]; then
  echo "Building YukiSU LKM out-of-tree against $KDIR"
  make -C "$KDIR" M="$KP_DIR/common/drivers/kernelsu" \
    CONFIG_KSU=m CONFIG_KSU_SUPERKEY=y CONFIG_KSU_YUKIZYGISK=y \
    ARCH=arm64 LLVM=1 LLVM_IAS=1 CC=clang \
    CROSS_COMPILE=aarch64-linux-gnu- modules
  llvm-strip -d "$KP_DIR/common/drivers/kernelsu/kernelsu.ko" || true
fi

echo "Image candidates:"
find "$KP_DIR" -name Image -type f 2>/dev/null | head
echo "kernelsu.ko candidates:"
find "$KP_DIR" -name kernelsu.ko -type f 2>/dev/null | head
