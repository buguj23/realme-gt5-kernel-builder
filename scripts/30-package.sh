#!/usr/bin/env bash
# 30-package.sh — AnyKernel3 from OEM OGKI Image + YukiSU kernelsu.ko.
set -euo pipefail

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
KP_DIR=${KP_DIR:-$HOME/gt5_kernel_ab/kernel_platform}
OUT=${OUT:-$HOME/gt5_infinity_workspace/kernel_deliver}
AK=$REPO_DIR/kernel/AnyKernel3

mkdir -p "$OUT"
IMAGE=$(find "$KP_DIR" -name Image -type f 2>/dev/null | head -n1 || true)
[ -n "$IMAGE" ] || { echo "no OGKI Image under $KP_DIR" >&2; exit 1; }
KO=$(find "$KP_DIR" -name kernelsu.ko -type f 2>/dev/null | head -n1 || true)

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
cp -a "$AK/." "$STAGE/"
cp "$IMAGE" "$STAGE/Image"
if [ -n "$KO" ]; then
  cp "$KO" "$STAGE/kernelsu.ko"
  llvm-strip -d "$STAGE/kernelsu.ko" 2>/dev/null || true
fi

ZIP=$OUT/AnyKernel3_YukiSU_OGKI_realme-gt5_$(date +%Y%m%d).zip
( cd "$STAGE" && zip -r9 "$ZIP" . -x '.git/*' )
ln -sfn "$ZIP" "$OUT/AnyKernel3_YukiSU_OGKI_realme-gt5.zip"
ls -lh "$ZIP"
echo "Flash via recovery. Device names: ossi / RMX3820 / salami / corot / xigua."
