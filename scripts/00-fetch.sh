#!/usr/bin/env bash
# 00-fetch.sh — fetch the exact kernel sources matching the ROM's 5.15.200 kernel.
#   * common kernel : himanshusaini010/kernel_oneplus_sm8550 @ a1403aca1412 (branch 16.0)
#   * vendor modules: himanshusaini010/android_kernel_oneplus_sm8550-modules @ 16.0
# The kernel_platform build system (build/, prebuilts/) is reused from an existing
# OnePlusOSS sync; pass KP_DIR to point at it.
set -euo pipefail

KP_DIR=${KP_DIR:-$HOME/gt5_kernel_ab/kernel_platform}
COMMON_COMMIT=${COMMON_COMMIT:-a1403aca1412a58085fa438eb386a111efe90e29}
COMMON_REPO=${COMMON_REPO:-https://github.com/himanshusaini010/kernel_oneplus_sm8550.git}
COMMON_BRANCH=${COMMON_BRANCH:-16.0}
MODULES_REPO=${MODULES_REPO:-https://github.com/himanshusaini010/android_kernel_oneplus_sm8550-modules.git}
MODULES_BRANCH=${MODULES_BRANCH:-16.0}
WORK=${WORK:-$HOME/gt5_kernel_ab_200}

[ -d "$KP_DIR/build" ] || { echo "kernel_platform build system not found at $KP_DIR"; exit 1; }

mkdir -p "$WORK"
if [ ! -d "$WORK/common/.git" ]; then
    git clone --depth 1 --branch "$COMMON_BRANCH" "$COMMON_REPO" "$WORK/common"
fi
( cd "$WORK/common"
  git fetch --depth 1 origin "$COMMON_COMMIT"
  git checkout -q "$COMMON_COMMIT"
  printf '%s' '-ga1403aca1412-dirty' > .scmversion )   # exact vermagic of the ROM kernel

if [ ! -d "$KP_DIR/sm8550-modules" ]; then
    git clone --depth 1 --branch "$MODULES_BRANCH" "$MODULES_REPO" "$KP_DIR/sm8550-modules"
fi

# swap the common tree into the kernel_platform (keep the old one as backup)
if [ -d "$KP_DIR/common" ] && [ ! -L "$KP_DIR/common" ]; then
    [ -d "$KP_DIR/common_515180" ] || mv "$KP_DIR/common" "$KP_DIR/common_515180"
fi
rm -rf "$KP_DIR/common"
mv "$WORK/common" "$KP_DIR/common"

echo "common: $(grep -E '^SUBLEVEL' "$KP_DIR/common/Makefile") commit=$(git -C "$KP_DIR/common" rev-parse --short=12 HEAD)"
echo "modules: $(du -sh "$KP_DIR/sm8550-modules" | cut -f1)"
