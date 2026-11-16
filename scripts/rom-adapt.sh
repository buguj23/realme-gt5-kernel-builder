#!/usr/bin/env bash
# rom-adapt.sh — replace only the kernel in a GT5 150W official boot.img.
#
# Official dump facts (see official/catalog.json):
#   * header v4, ramdisk_size=0, os_version always 13.0.0 (KMI ABI)
#   * KMI android13-5.15 on ColorOS 13/14/15/16
#   * dtbo + init_boot stay STOCK for that ColorOS
#   * vbmeta flags=0 stock; custom Image needs flags=3
set -euo pipefail
REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
KP_DIR=${KP_DIR:-$HOME/gt5_kernel_ab/kernel_platform}
OUT=${OUT:-$HOME/gt5_infinity_workspace/kernel_deliver}
COLOROS=${COLOROS:-}
if [ -z "$COLOROS" ] && [ -f "$REPO_DIR/kernel.json" ]; then
  COLOROS=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("coloros",""))' "$REPO_DIR/kernel.json")
fi
COLOROS=${COLOROS:-16.0.3.500}

read_cat() {
  python3 - "$REPO_DIR/official/catalog.json" "$COLOROS" "$1" <<'PY'
import json,sys
cat=json.load(open(sys.argv[1]))
want=sys.argv[2]; key=sys.argv[3]
for r in cat:
    if r["coloros"]==want:
        v=r
        for part in key.split("."):
            v=v[part] if not part.isdigit() else v[int(part)]
        print(v)
        break
else:
    sys.exit(1)
PY
}

OS_VERSION=${OS_VERSION:-$(read_cat os_version)}
OS_PATCH=${OS_PATCH:-$(read_cat os_patch_level)}
STOCK=$REPO_DIR/official/stock/$COLOROS
STOCK_BOOT=${STOCK_BOOT:-$STOCK/boot.img}

IMAGE=$(find "$KP_DIR" -name Image -type f 2>/dev/null | head -n1 || true)
KO=$(find "$KP_DIR" -name kernelsu.ko -type f 2>/dev/null | head -n1 || true)
[ -n "$IMAGE" ] || { echo "OGKI Image missing — run 20-build.sh" >&2; exit 1; }

if command -v mkbootimg >/dev/null; then
  MKBOOTIMG=mkbootimg
else
  MKBOOTIMG=${MKBOOTIMG:-python3 ${KP_DIR}/tools/mkbootimg/mkbootimg.py}
fi

mkdir -p "$OUT"

# Prefer official boot as the template: kernel-only v4, os 13.0.0.
$MKBOOTIMG --header_version 4 --kernel "$IMAGE" \
  --os_version "$OS_VERSION" --os_patch_level "$OS_PATCH" \
  -o "$OUT/boot.img"

if [ -n "$KO" ] && command -v ksud >/dev/null; then
  ksud boot-patch -b "$OUT/boot.img" --kmi android13-5.15 --module "$KO" \
    -o "$OUT/boot_yukisu.img" || true
fi

# Stock DTBO / init_boot / recovery — do not substitute OnePlus analogue images.
for f in dtbo.img init_boot.img recovery.img; do
  if [ -f "$STOCK/$f" ]; then
    cp "$STOCK/$f" "$OUT/$f"
  fi
done

# Custom kernel: disable AVB (stock flags=0 would reject our Image).
if [ -f "$STOCK/vbmeta.img" ]; then
  python3 - "$STOCK/vbmeta.img" "$OUT/vbmeta.img" <<'PY'
import struct, sys
from pathlib import Path
data=bytearray(Path(sys.argv[1]).read_bytes())
# AvbVBMetaImageHeader.flags at offset 120, big-endian
# 1=HASH_TREE disable? AVB_VBMETA_IMAGE_FLAGS_HASHTREE_DISABLED=1
# AVB_VBMETA_IMAGE_FLAGS_VERIFICATION_DISABLED=2 → flags=3
struct.pack_into('>I', data, 120, 3)
Path(sys.argv[2]).write_bytes(data)
print('vbmeta flags -> 3 (verification disabled for custom OGKI Image)')
PY
fi

cat > "$OUT/FLASH.txt" <<EOF
Realme GT5 150W (ossi / RMX3820) ColorOS ${COLOROS}
Official linux: $(read_cat linux)
boot header: v4 os_version=${OS_VERSION} os_patch=${OS_PATCH} (kernel ABI, not userspace)

fastboot getvar current-slot
fastboot --set-active=a
fastboot flash boot_a     boot.img          # our OGKI Image, official header
fastboot flash dtbo_a     dtbo.img          # STOCK this ColorOS
fastboot flash init_boot_a init_boot.img    # STOCK this ColorOS
fastboot flash vbmeta_a   vbmeta.img        # flags=3
# Do NOT flash Google GKI. Do NOT flash analogue OnePlus dtbo.
fastboot reboot
EOF
ls -lh "$OUT"
echo "COLOROS=$COLOROS os=$OS_VERSION/$OS_PATCH"
