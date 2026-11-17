#!/usr/bin/env bash
# kernel-package.sh — bundle one kernel build so a ROM tree can consume it intact.
#
# The ROM must never mix an Image with modules from another build: with
# CONFIG_MODVERSIONS=y every .ko is checked against the kernel's symbol CRCs.
# This package is the unit of alignment: Image + every .ko + Module.symvers.
#
# usage: kernel-package.sh <build-root> <out-dir> [--label NAME]
#   build-root  the tree the workflow built (e.g. kernel_workspace)
#   out-dir     where kernel-package.tar.zst + manifest.json are written
set -euo pipefail

ROOT=${1:?usage: kernel-package.sh <build-root> <out-dir> [--label NAME]}
OUT=${2:?usage: kernel-package.sh <build-root> <out-dir> [--label NAME]}
LABEL=${4:-kernel}
[ "${3:-}" = "--label" ] || LABEL=kernel

HERE=$(cd "$(dirname "$0")" && pwd)
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/modules" "$OUT"

echo "[1/5] Image"
# KP_IMAGE lets the caller pin the post-patch image (KPX replaces it in place).
IMAGE="${KP_IMAGE:-}"
[ -n "$IMAGE" ] && [ -f "$IMAGE" ] || IMAGE=""
[ -n "$IMAGE" ] || IMAGE=$(find "$ROOT" -type f -name Image -path '*/out/*' | head -n1 || true)
[ -n "$IMAGE" ] || IMAGE=$(find "$ROOT" -type f -name Image | head -n1 || true)
[ -n "$IMAGE" ] || { echo "FAIL: no Image under $ROOT" >&2; exit 1; }
cp "$IMAGE" "$STAGE/Image"
echo "      $IMAGE ($(stat -c%s "$IMAGE") B)"

echo "[2/5] dtbo"
DTBO=$(find "$ROOT" -type f -name 'dtbo.img' | head -n1 || true)
[ -n "$DTBO" ] && cp "$DTBO" "$STAGE/dtbo.img" && echo "      $DTBO" || echo "      none (stock dtbo stays)"

echo "[3/5] Module.symvers"
SYMVERS=$(find "$ROOT" -type f -name Module.symvers -size +1k | head -n1 || true)
[ -n "$SYMVERS" ] || { echo "FAIL: no Module.symvers — alignment would be unprovable" >&2; exit 1; }
cp "$SYMVERS" "$STAGE/Module.symvers"
echo "      $SYMVERS ($(wc -l < "$SYMVERS") symbols)"

echo "[4/5] modules"
# Build products live under out/; source trees also contain stale .ko on reruns.
find "$ROOT" -type f -name '*.ko' -path '*/out/*' -print0 2>/dev/null \
  | xargs -0 -r -I{} cp -n {} "$STAGE/modules/" 2>/dev/null || true
if [ -z "$(ls -A "$STAGE/modules" 2>/dev/null)" ]; then
  find "$ROOT" -type f -name '*.ko' -print0 2>/dev/null \
    | xargs -0 -r -I{} cp -n {} "$STAGE/modules/" 2>/dev/null || true
fi
COUNT=$(ls "$STAGE/modules" | wc -l)
[ "$COUNT" -gt 0 ] || { echo "FAIL: no .ko collected" >&2; exit 1; }
echo "      $COUNT modules"

echo "[5/5] manifest + archive"
python3 "$HERE/kmi.py" manifest --package "$STAGE" --out "$STAGE/manifest.json"
python3 - "$STAGE/manifest.json" "$LABEL" <<'PY'
import json, sys, datetime
p, label = sys.argv[1], sys.argv[2]
d = json.load(open(p))
d["label"] = label
d["built_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
json.dump(d, open(p, "w"), indent=1)
PY
python3 "$HERE/kmi.py" verify --symvers "$STAGE/Module.symvers" --modules "$STAGE/modules" \
  --image "$STAGE/Image"

mkdir -p "$OUT"
tar --zstd -cf "$OUT/kernel-package.tar.zst" -C "$STAGE" .
cp "$STAGE/manifest.json" "$OUT/manifest.json"
echo "package: $OUT/kernel-package.tar.zst ($(stat -c%s "$OUT/kernel-package.tar.zst") B)"
