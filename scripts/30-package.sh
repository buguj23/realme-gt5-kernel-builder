#!/usr/bin/env bash
# 30-package.sh — Package AnyKernel3 ZIP, KMI SDK (Module.symvers + .config + vmlinux),
# and ROM kernel-package (schema 2) from a built Realme GT5 5.15.149 Kbuild output.
set -euo pipefail

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
KP_DIR=${KP_DIR:-$HOME/gt5_kernel_5_15_149/kernel_platform}
KBUILD_OUT=${KBUILD_OUT:-$KP_DIR/common/out}
OUT=${OUT:-$REPO_DIR/out/artifacts}
KSU_MODE=${KSU_MODE:-Pure-OGKI}
TAG_SUFFIX=${TAG_SUFFIX:-}
AK=$REPO_DIR/kernel/AnyKernel3

if [ ! -f "$KBUILD_OUT/arch/arm64/boot/Image" ]; then
  img=$(find "$KP_DIR" -name Image -type f 2>/dev/null | head -n1 || true)
  [ -n "$img" ] || { echo "no OGKI Image under $KBUILD_OUT or $KP_DIR" >&2; exit 1; }
  KBUILD_OUT=$(cd "$(dirname "$img")/../../.." && pwd)
fi
IMAGE="$KBUILD_OUT/arch/arm64/boot/Image"
KO="${KSU_KO:-$KBUILD_OUT/kernelsu.ko}"

mkdir -p "$OUT" "$OUT/kmi-sdk" "$OUT/kernel-package"

# 1. AnyKernel3 flashable ZIP
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
cp -a "$AK/." "$STAGE/"
cp "$IMAGE" "$STAGE/Image"
if [ "$KSU_MODE" = "YukiSU-LKM" ] && [ -f "$KO" ]; then
  cp "$KO" "$STAGE/kernelsu.ko"
  llvm-strip -d "$STAGE/kernelsu.ko" 2>/dev/null || true
else
  rm -f "$STAGE/kernelsu.ko" "$STAGE/ksud"
fi

STAMP=$(date +%Y%m%d_%H%M)
ZIP="$OUT/AnyKernel3_${KSU_MODE}_GT5_5.15.149${TAG_SUFFIX}_${STAMP}.zip"
( cd "$STAGE" && zip -qr9 "$ZIP" . -x '.git/*' )
ln -sfn "$ZIP" "$OUT/AnyKernel3_GT5_5.15.149_latest.zip"

# 2. KMI SDK for YukiSU out-of-tree LKM or ROM verification (ogki_yukisu.html requirement)
cp -f "$IMAGE" "$OUT/kmi-sdk/Image"
[ -f "$KBUILD_OUT/Module.symvers" ] && cp -f "$KBUILD_OUT/Module.symvers" "$OUT/kmi-sdk/Module.symvers"
[ -f "$KBUILD_OUT/.config" ] && cp -f "$KBUILD_OUT/.config" "$OUT/kmi-sdk/.config"
if [ -f "$KBUILD_OUT/vmlinux" ]; then
  if command -v zstd >/dev/null 2>&1; then
    tar --zstd -cf "$OUT/kmi-sdk/vmlinux.tar.zst" -C "$KBUILD_OUT" vmlinux
  else
    gzip -c "$KBUILD_OUT/vmlinux" > "$OUT/kmi-sdk/vmlinux.gz"
  fi
fi
[ "$KSU_MODE" = "YukiSU-LKM" ] && [ -f "$KO" ] && cp -f "$KO" "$OUT/kmi-sdk/kernelsu.ko"
rm -f "$OUT/kmi-sdk/SHA256SUMS"
( cd "$OUT/kmi-sdk" && sha256sum * > SHA256SUMS )

# 3. Schema 2 ROM kernel-package
if [ -f "$KBUILD_OUT/Module.symvers" ] && [ -f "$KBUILD_OUT/modules.order" ]; then
  COMMIT=$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || printf '%040x' 0)
  bash "$REPO_DIR/scripts/kernel-package.sh" "$KBUILD_OUT" "$OUT/kernel-package" \
    --branch 5.15.149 --variant "$KSU_MODE" --commit "$COMMIT"
fi

ls -lh "$ZIP" "$OUT/kmi-sdk/"
echo "Packaged $KSU_MODE deliverables into $OUT"
