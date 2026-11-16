#!/usr/bin/env bash
# 10-patch.sh — Action-Build 5.15 OGKI patches + YukiSU LKM.
# Does not overlay configs/reference/rom_ikconfig.defconfig (Google/ROM GKI dump).
set -euo pipefail

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
KP_DIR=${KP_DIR:-$HOME/gt5_kernel_ab/kernel_platform}
C=$KP_DIR/common
WORK=${WORK:-${TMPDIR:-/tmp}/kbuild_src}
FILE=${FILE:-oneplus_ace2_pro_b}
APPLY_SUSFS=${APPLY_SUSFS:-0}   # YukiSU uses Kasumi; SUSFS is SukiSU-only
APPLY_REKERNEL=${APPLY_REKERNEL:-0}
APPLY_ZRAM=${APPLY_ZRAM:-0}
APPLY_MIDAS=${APPLY_MIDAS:-1}

[ -d "$C" ] || { echo "missing $C — run scripts/00-fetch.sh" >&2; exit 1; }
mkdir -p "$WORK"

# 1. MidAS ghost-task (DroidSpaces), from Action-Build
if [ "$APPLY_MIDAS" = 1 ]; then
  patch -d "$C" -p1 -F3 --forward < "$REPO_DIR/patches/ghost-task-for-midas.patch" || true
fi

# 2. YukiSU LKM + Kasumi + YukiZygisk on OEM defconfig
bash "$REPO_DIR/scripts/integrate-yukisu.sh" "$C"

# 3. Re-Kernel (optional)
if [ "$APPLY_REKERNEL" = 1 ]; then
  [ -d "$WORK/Re-Kernel" ] || git clone --depth 1 https://github.com/Sakion-Team/Re-Kernel.git "$WORK/Re-Kernel"
  mkdir -p "$C/drivers/rekernel"
  cp -a "$WORK/Re-Kernel/LKM-Source/." "$C/drivers/rekernel/"
  grep -q 'drivers/rekernel/Kconfig' "$C/drivers/Kconfig" \
    || sed -i '/^endmenu/i source "drivers/rekernel/Kconfig"' "$C/drivers/Kconfig"
  grep -q 'rekernel/' "$C/drivers/Makefile" \
    || printf '\nobj-$(CONFIG_REKERNEL) += rekernel/\n' >> "$C/drivers/Makefile"
fi

# 4. ZRAM lz4kd from SukiSU_patch (compression only; not SukiSU root)
if [ "$APPLY_ZRAM" = 1 ]; then
  [ -d "$WORK/SukiSU_patch" ] || git clone --depth 1 https://github.com/ShirkNeko/SukiSU_patch.git "$WORK/SukiSU_patch"
  S=$WORK/SukiSU_patch/other/zram
  cp -r "$S"/lz4k/include/linux/* "$C/include/linux/"
  cp -r "$S"/lz4k/lib/* "$C/lib/"
  cp -r "$S"/lz4k/crypto/* "$C/crypto/"
  cp -r "$S"/lz4k_oplus "$C/lib/"
  patch -d "$C" -p1 -F3 --forward < "$S/zram_patch/5.15/lz4kd.patch" || true
  patch -d "$C" -p1 -F3 --forward < "$S/zram_patch/5.15/lz4k_oplus.patch" || true
fi

# 5. Action-Build 5.15.0–5.15.123 C library fix
SUBLEVEL=$(awk '/^SUBLEVEL =/ {print $3}' "$C/Makefile")
KMI=""
for f in "$C/build.config.constants" "$C/build.config.common"; do
  [ -f "$f" ] || continue
  KMI=$(grep -m1 '^BRANCH=' "$f" | cut -d= -f2 || true)
  [ -n "$KMI" ] && break
done
if [ "$KMI" = "android13-5.15" ] && [ "${SUBLEVEL:-999}" -lt 123 ]; then
  patch -d "$C" -p1 --forward < "$REPO_DIR/patches/fix_5.15.legacy" || true
fi

# 6. BBRv3 for android13-5.15 / android14-5.15
if [ -n "$KMI" ] && [ -f "$REPO_DIR/patches/bbrv3/0001-net-tcp-backport-BBRv3-to-${KMI}.patch" ]; then
  patch -d "$C" -p1 --forward < "$REPO_DIR/patches/bbrv3/0001-net-tcp-backport-BBRv3-to-${KMI}.patch" || true
fi

# 7. ntsync 5.15 compat (DroidSpaces)
if [ "${APPLY_NTSYNC:-0}" = 1 ]; then
  patch -d "$C" -p1 --forward < "$REPO_DIR/patches/ntsync/ntsync_base.patch" || true
  case "$KMI" in
    android13-5.15) patch -d "$C" -p1 --forward < "$REPO_DIR/patches/ntsync/ntsync_compat_android13-5.15.patch" || true ;;
    android14-5.15) patch -d "$C" -p1 --forward < "$REPO_DIR/patches/ntsync/ntsync_compat_android14-5.15.patch" || true ;;
  esac
fi

if [ "$APPLY_SUSFS" = 1 ]; then
  echo "WARNING: SUSFS rewrites task_struct and breaks YukiSU LKM ABI. Refusing." >&2
  exit 2
fi

echo "patched OGKI common=$C kmi=${KMI:-unknown} sublevel=$SUBLEVEL"
