#!/usr/bin/env bash
# rom-build-local.sh — assemble and build one GT5 branch locally.
#
# Everything the build needs is an explicit input; nothing is guessed:
#   --blobs  materialized stock files for THIS branch (rom-select-blobs.py --materialize)
#   --pool   stock module pool + modules.load for THIS branch (stock-module-lists.sh)
#   --pkg    kernel package for THIS branch (kernel-package.sh output)
#
# usage:
#   rom-build-local.sh --src ~/rom16 --branch 5.15.180 \
#     --blobs ~/gt5_work/dumps/5.15.180 \
#     --pool  ~/gt5_work/pools/5.15.180 \
#     --pkg   ~/gt5_work/pkgs/5.15.180 \
#     --lunch infinity_ossi-userdebug --deps-branch lineage-23.2 \
#     [--jobs N] [--check-only]
#
# Disk: a full AOSP checkout plus out/ needs ~250 GB. The script refuses to start
# below --min-free-gb (default 120) so a build cannot die halfway on ENOSPC.
set -euo pipefail

SRC=""; BR=""; BLOBS=""; POOL=""; PKG=""; LUNCH=""; DEPS_BR="lineage-23.2"
JOBS=$(nproc); CHECK_ONLY=0; MIN_FREE=120

while [ $# -gt 0 ]; do
  case "$1" in
    --src) SRC=${2:?}; shift 2 ;;
    --branch) BR=${2:?}; shift 2 ;;
    --blobs) BLOBS=${2:?}; shift 2 ;;
    --pool) POOL=${2:?}; shift 2 ;;
    --pkg) PKG=${2:?}; shift 2 ;;
    --lunch) LUNCH=${2:?}; shift 2 ;;
    --deps-branch) DEPS_BR=${2:?}; shift 2 ;;
    --jobs) JOBS=${2:?}; shift 2 ;;
    --min-free-gb) MIN_FREE=${2:?}; shift 2 ;;
    --check-only) CHECK_ONLY=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/.." && pwd)

fail() { echo "FAIL: $*" >&2; exit 1; }

for v in SRC BR BLOBS POOL PKG LUNCH; do
  [ -n "${!v}" ] || fail "--$(echo "$v" | tr 'A-Z_' 'a-z-') is required"
done

echo "[preflight]"
for tool in git python3 repo make ccache java; do command -v "$tool" >/dev/null || fail "$tool not in PATH"; done
[ -d "$SRC/.repo" ] || fail "$SRC is not a repo tree (run rom-sync.sh first)"
[ -f "$SRC/build/envsetup.sh" ] || fail "$SRC/build/envsetup.sh missing (sync incomplete)"
[ -d "$BLOBS" ] || fail "blob dump $BLOBS missing"
[ -f "$POOL/stock-modules.load" ] || fail "$POOL/stock-modules.load missing"
[ -d "$POOL/stock-modules" ] || fail "$POOL/stock-modules missing"
[ -f "$PKG/Image" ] || fail "$PKG/Image missing"
[ -f "$PKG/Module.symvers" ] || fail "$PKG/Module.symvers missing"

FREE=$(df -BG --output=avail "$SRC" | tail -1 | tr -dc '0-9')
echo "  free ${FREE}G, require ${MIN_FREE}G"
[ "$FREE" -ge "$MIN_FREE" ] || fail "not enough space: ${FREE}G < ${MIN_FREE}G"
echo "  blobs $(find "$BLOBS" -type f | wc -l) files, pool $(ls "$POOL/stock-modules" | wc -l) modules"
[ "$CHECK_ONLY" -eq 1 ] && { echo "check-only: inputs OK"; exit 0; }

LOG="$SRC/build.log"
exec > >(tee -a "$LOG") 2>&1

echo "[1/6] device trees ($BR)"
mkdir -p "$SRC/device/realme"
rsync -a --delete "$REPO_ROOT/rom/device/realme/ossi/" "$SRC/device/realme/ossi/"
rsync -a --delete "$REPO_ROOT/rom/device/realme/sm8550-ogki/" "$SRC/device/realme/sm8550-ogki/"

echo "[2/6] vendor makefiles + blobs"
mkdir -p "$SRC/vendor/realme/ossi"
rsync -a --delete --exclude proprietary "$REPO_ROOT/rom/vendor/realme/ossi/" "$SRC/vendor/realme/ossi/"
rm -rf "$SRC/vendor/realme/ossi/proprietary"
mkdir -p "$SRC/vendor/realme/ossi/proprietary"
cp -a "$BLOBS/." "$SRC/vendor/realme/ossi/proprietary/"
echo "  blobs placed: $(find "$SRC/vendor/realme/ossi/proprietary" -type f | wc -l)"

echo "[3/6] dependency trees ($DEPS_BR)"
bash "$HERE/rom-provision-deps.sh" "$SRC" --branch "$DEPS_BR"

echo "[4/6] kernel package staging (per-symbol CRC gate)"
python3 "$HERE/rom-stage-kernel.py" --package "$PKG" \
  --device-tree "$SRC/device/realme/ossi" \
  --stock-modules-load "$POOL/stock-modules.load" \
  --stock-modules "$POOL/stock-modules"

echo "[5/6] lunch $LUNCH"
cd "$SRC"
set +u
source build/envsetup.sh
lunch "$LUNCH"
set -u

echo "[6/6] mka bacon -j$JOBS"
mka bacon -j"$JOBS"

OUT="$SRC/out/target/product/ossi"
ZIP=$(ls -1 "$OUT"/*.zip 2>/dev/null | tail -1 || true)
echo "built: ${ZIP:-<no zip>}"
if [ -f "$OUT/vendor_boot.img" ]; then
  echo "vendor_boot check (compare with the branch OTA):"
  echo "  $HERE/rom-vendor-boot-fix.sh $OUT/vendor_boot.img --stock <stock vendor_boot.img> --check-only"
fi
