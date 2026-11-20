#!/usr/bin/env bash
# 10-patch.sh — Optional, KMI-safe OGKI patches for Realme GT5 (5.15.149).
# Enforces hard bans from ogki_yukisu.html: NO CONFIG_KSU=y, NO SUSFS, NO KPM, NO FakeConfig.
set -euo pipefail

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=scripts/lib-kernel.sh
source "$REPO_DIR/scripts/lib-kernel.sh"
enable_local_proxy_if_up

KP_DIR=${KP_DIR:-$HOME/gt5_kernel_5_15_149/kernel_platform}
C=$KP_DIR/common
WORK=${WORK:-${TMPDIR:-/tmp}/kbuild_src}

APPLY_UNICODE=${APPLY_UNICODE:-0}
APPLY_MIDAS=${APPLY_MIDAS:-0}
APPLY_NTSYNC=${APPLY_NTSYNC:-0}
APPLY_BBRV3=${APPLY_BBRV3:-0}
APPLY_REKERNEL=${APPLY_REKERNEL:-0}
APPLY_ZRAM=${APPLY_ZRAM:-0}
APPLY_BBG=${APPLY_BBG:-0}
APPLY_SUSFS=${APPLY_SUSFS:-0}
APPLY_KPM=${APPLY_KPM:-0}

[ -d "$C" ] || { echo "missing $C — run scripts/00-fetch.sh" >&2; exit 1; }
mkdir -p "$WORK"

if [ "$APPLY_SUSFS" = 1 ]; then
  echo "ERROR: SUSFS mutates core kernel structs and breaks KMI/YukiSU ABI. Refusing." >&2
  exit 2
fi
if [ "$APPLY_KPM" = 1 ]; then
  echo "ERROR: KPM/KPN binary patching is unsupported with Pure-OGKI/YukiSU. Refusing." >&2
  exit 2
fi

SUBLEVEL=$(awk '/^SUBLEVEL =/ {print $3}' "$C/Makefile")
KMI=""
for f in "$C/build.config.constants" "$C/build.config.common"; do
  [ -f "$f" ] || continue
  KMI=$(grep -m1 '^BRANCH=' "$f" | cut -d= -f2 || true)
  [ -n "$KMI" ] && break
done

apply_patch_once() {
  local patch_file=$1
  [ -f "$patch_file" ] || { echo "missing patch $patch_file" >&2; exit 1; }
  if patch -d "$C" -p1 -R --dry-run -s < "$patch_file" >/dev/null 2>&1; then
    echo "already applied: $(basename "$patch_file")"
    return 0
  fi
  patch -d "$C" -p1 -F3 --forward < "$patch_file"
}

if [ "$APPLY_MIDAS" = 1 ] || [ "$APPLY_NTSYNC" = 1 ]; then
  apply_patch_once "$REPO_DIR/patches/ghost-task-for-midas.patch"
fi

if [ "$APPLY_UNICODE" = 1 ]; then
  apply_patch_once "$REPO_DIR/patches/unicode_bypass_fix_6.1-.patch"
fi

if [ "$APPLY_BBRV3" = 1 ]; then
  if [ -f "$REPO_DIR/patches/bbrv3/0001-net-tcp-backport-BBRv3-to-${KMI}.patch" ]; then
    apply_patch_once "$REPO_DIR/patches/bbrv3/0001-net-tcp-backport-BBRv3-to-${KMI}.patch"
    apply_patch_once "$REPO_DIR/patches/bbrv3/sysctl_add_proc_dou8vec_minmax.patch" || true
    apply_patch_once "$REPO_DIR/patches/bbrv3/sysctl_fix_data-races_in_proc_dou8vec_minmax.patch" || true
  fi
fi

if [ "$APPLY_NTSYNC" = 1 ]; then
  apply_patch_once "$REPO_DIR/patches/ntsync/ntsync_base.patch"
  if [ -f "$REPO_DIR/patches/ntsync/ntsync_compat_${KMI}.patch" ]; then
    apply_patch_once "$REPO_DIR/patches/ntsync/ntsync_compat_${KMI}.patch"
  fi
fi

if [ "$APPLY_REKERNEL" = 1 ]; then
  if [ ! -d "$WORK/Re-Kernel/.git" ]; then
    git_clone_resilient https://github.com/Sakion-Team/Re-Kernel.git "$WORK/Re-Kernel" --depth 1
  fi
  mkdir -p "$C/drivers/rekernel"
  cp -a "$WORK/Re-Kernel/LKM-Source/." "$C/drivers/rekernel/"
  grep -q 'drivers/rekernel/Kconfig' "$C/drivers/Kconfig" \
    || sed -i '/^endmenu/i source "drivers/rekernel/Kconfig"' "$C/drivers/Kconfig"
  grep -q 'rekernel/' "$C/drivers/Makefile" \
    || printf '\nobj-$(CONFIG_REKERNEL) += rekernel/\n' >> "$C/drivers/Makefile"
fi

if [ "$APPLY_ZRAM" = 1 ]; then
  if [ ! -d "$WORK/SukiSU_patch/.git" ]; then
    git_clone_resilient https://github.com/ShirkNeko/SukiSU_patch.git "$WORK/SukiSU_patch" --depth 1
  fi
  S=$WORK/SukiSU_patch/other/zram
  cp -r "$S"/lz4k/include/linux/* "$C/include/linux/"
  cp -r "$S"/lz4k/lib/* "$C/lib/"
  cp -r "$S"/lz4k/crypto/* "$C/crypto/"
  cp -r "$S"/lz4k_oplus "$C/lib/"
  apply_patch_once "$S/zram_patch/5.15/lz4kd.patch"
  apply_patch_once "$S/zram_patch/5.15/lz4k_oplus.patch"
fi

if [ "$APPLY_BBG" = 1 ]; then
  if [ ! -d "$WORK/Baseband-guard/.git" ]; then
    git_clone_resilient https://github.com/vc-teahouse/Baseband-guard.git "$WORK/Baseband-guard" --depth 1
  fi
  if ! grep -q 'Baseband-guard' "$C/security/Makefile" 2>/dev/null; then
    (cd "$C" && bash "$WORK/Baseband-guard/setup.sh")
  fi
fi

# Deterministic strip of -dirty suffix without mangling the KMI vermagic prefix.
for f in "$C/scripts/setlocalversion" "$KP_DIR/msm-kernel/scripts/setlocalversion"; do
  [ -f "$f" ] || continue
  sed -i 's/ -dirty//g' "$f"
done

echo "patched OGKI common=$C kmi=${KMI:-unknown} sublevel=$SUBLEVEL"
