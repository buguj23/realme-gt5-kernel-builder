#!/usr/bin/env bash
# rom-adapt.sh — pack OEM OGKI Image into the ROM boot/vendor_boot without Google GKI.
#
# Rules:
#   1. Kernel Image MUST come from Action-Build OGKI (oplus_build kalama gki analogue).
#   2. Do not mix Google GKI boot.img or generic android13-5.15 Image.
#   3. vendor_dlkm / first-stage modules must be from the SAME OGKI build, or leave ROM modules
#      and only replace boot.img if vermagic+CRC match (they will not if SUSFS is in the ROM kernel).
#   4. YukiSU is LKM: inject kernelsu.ko via ksud boot-patch when ksud is available, else AnyKernel3.
set -euo pipefail

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
KP_DIR=${KP_DIR:-$HOME/gt5_kernel_ab/kernel_platform}
ROM=${ROM:-$HOME/gt5_infinity_workspace/rom_check}
OUT=${OUT:-$HOME/gt5_infinity_workspace/kernel_deliver}
MKBOOTIMG=${MKBOOTIMG:-python3 $KP_DIR/tools/mkbootimg/mkbootimg.py}

IMAGE=$(find "$KP_DIR" -name Image -type f 2>/dev/null | head -n1 || true)
KO=$(find "$KP_DIR" -name kernelsu.ko -type f 2>/dev/null | head -n1 || true)
[ -n "$IMAGE" ] || { echo "OGKI Image missing" >&2; exit 1; }
mkdir -p "$OUT"

OS_VERSION=${OS_VERSION:-16.0.0}
OS_PATCH=${OS_PATCH:-2026-09}

if [ -x "$(command -v unpack_bootimg || true)" ] && [ -f "${ROM:-/dev/null}/boot.img" ]; then
  tmp=$(mktemp -d)
  unpack_bootimg --boot_img "$ROM/boot.img" --out "$tmp" >/dev/null
  # Keep ROM header; replace kernel only.
  $MKBOOTIMG --header_version 4 --kernel "$IMAGE" \
    --os_version "$OS_VERSION" --os_patch_level "$OS_PATCH" \
    -o "$OUT/boot.img"
  rm -rf "$tmp"
else
  $MKBOOTIMG --header_version 4 --kernel "$IMAGE" \
    --os_version "$OS_VERSION" --os_patch_level "$OS_PATCH" \
    -o "$OUT/boot.img"
fi

if [ -n "$KO" ] && command -v ksud >/dev/null; then
  echo "ksud boot-patch LKM into boot.img"
  ksud boot-patch -b "$OUT/boot.img" --kmi android13-5.15 --module "$KO" -o "$OUT/boot_yukisu.img" \
    || ksud boot-patch -b "$OUT/boot.img" --module "$KO" -o "$OUT/boot_yukisu.img" || true
fi

# Do not rewrite vendor_boot fstab (ext4 vs f2fs). That boot-looped this device before.
if [ -f "${ROM:-}/vendor_boot.img" ]; then
  echo "Keeping ROM vendor_boot.img (fstab). Copying as reference only."
  cp "$ROM/vendor_boot.img" "$OUT/vendor_boot.rom.img"
fi

cat > "$OUT/FLASH.txt" <<EOF
Realme GT5 (ossi / RMX3820) — OGKI + YukiSU

fastboot getvar current-slot
fastboot --set-active=a
fastboot flash boot_a boot.img          # this OGKI Image (or boot_yukisu.img)
# Do NOT flash Google GKI boot.img
# Do NOT flash vendor_boot unless it was built from the same OGKI tree
fastboot reboot

Recovery alternative: AnyKernel3_YukiSU_OGKI_realme-gt5.zip
EOF
ls -lh "$OUT"
echo "ROM adapt staged in $OUT"
