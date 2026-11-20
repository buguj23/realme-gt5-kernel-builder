#!/usr/bin/env bash
# Fetch and SHA-256 verify RMX3820_15.0.0.320(CN01) stock partition images via multi-mirror aria2c.
set -euo pipefail

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
source "$REPO_DIR/scripts/lib-mirror.sh"

MODE="kernel"
DEST="$REPO_DIR/official/stock/15.0.0.320"
REPO_SLUG="${STOCK_RELEASE_REPO:-buguj23/realme-gt5-kernel-builder}"
TAG="${STOCK_RELEASE_TAG:-rmx3820-15.0.0.320-stock}"
LOCAL_DIR=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --mode) MODE="$2"; shift ;;
    --dest) DEST="$2"; shift ;;
    --repo) REPO_SLUG="$2"; shift ;;
    --tag) TAG="$2"; shift ;;
    --local-dir) LOCAL_DIR="$2"; shift ;;
    -h|--help)
      cat <<'EOF'
Usage: fetch-stock.sh [--mode kernel|full] [--dest DIR] [--local-dir DIR]
  --mode kernel   Fetch boot, init_boot, vendor_boot, dtbo, recovery, vbmeta*, vendor_dlkm, system_dlkm, payload_metadata (~97 MiB)
  --mode full     Fetch everything in 'kernel' plus vendor, odm, system, my_product archives (~3.9 GiB)
  --local-dir DIR Copy/link verified images from an existing local dump instead of downloading
EOF
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

mkdir -p "$DEST"

if [ -n "$LOCAL_DIR" ]; then
  [ -d "$LOCAL_DIR" ] || { echo "Missing local stock directory: $LOCAL_DIR" >&2; exit 1; }
  FILES=(boot.img dtbo.img init_boot.img recovery.img vbmeta.img vbmeta_system.img vbmeta_vendor.img vendor_boot.img vendor_dlkm.img system_dlkm.img payload_metadata.bin)
  if [ "$MODE" = "full" ]; then
    FILES+=(vendor.img product.img my_manifest.img odm.img system.img system_ext.img my_product.img)
  fi
  for f in "${FILES[@]}"; do
    [ -f "$LOCAL_DIR/$f" ] || { echo "Missing $LOCAL_DIR/$f" >&2; exit 1; }
    ln -sf "$(realpath "$LOCAL_DIR/$f")" "$DEST/$f"
  done
  if [ "$MODE" = "full" ]; then
    for f in super-layout.json my_bigball.img my_carrier.img my_company.img my_engineering.img my_heytap.img my_preload.img my_region.img my_stock.img; do
      [ -f "$LOCAL_DIR/$f" ] && ln -sf "$(realpath "$LOCAL_DIR/$f")" "$DEST/$f" || true
    done
  fi
  python3 "$REPO_DIR/scripts/rom-check-inputs.py" --branch 5.15.149 --stock "$DEST" \
    $([ "$MODE" = "full" ] && printf '%s' "--rom-partitions" || printf '%s' "--kernel-only") 2>/dev/null || \
    python3 -c "import sys; sys.path.insert(0, '$REPO_DIR/scripts'); import rom_inputs; rom_inputs.stock_payload('$DEST', '5.15.149'); print('Verified payload_metadata.bin')"
  exit 0
fi

BASE_URL="https://github.com/${REPO_SLUG}/releases/download/${TAG}"
CACHE_DIR="${STOCK_ARCHIVE_CACHE:-$DEST/.archives}"
mkdir -p "$CACHE_DIR"

download_multi_mirror "$CACHE_DIR/SHA256SUMS.txt" "" "${BASE_URL}/SHA256SUMS.txt"

sha_for() {
  awk -v f="$1" '$2 == f || $2 == ("*" f) {print $1; exit}' "$CACHE_DIR/SHA256SUMS.txt"
}

dest_has_all() {
  [ "${FORCE_STOCK_FETCH:-0}" != 1 ] || return 1
  local f
  for f in "$@"; do
    [ -s "$DEST/$f" ] || return 1
  done
  return 0
}

fetch_and_extract() {
  local archive="$1"
  shift
  if [ "$#" -gt 0 ] && dest_has_all "$@"; then
    echo "Already staged in $DEST: $*"
    return 0
  fi
  local sha
  sha=$(sha_for "$archive")
  if [ -n "$sha" ]; then
    echo "Fetching $archive (sha256=${sha:0:12}...)"
    download_multi_mirror "$CACHE_DIR/$archive" "$sha" "${BASE_URL}/${archive}"
    zstd -dc "$CACHE_DIR/$archive" | tar -xf - -C "$DEST"
    [ "${KEEP_STOCK_ARCHIVES:-0}" = 1 ] || rm -f "$CACHE_DIR/$archive"
    return 0
  fi
  local parts
  parts=$(awk -v p="${archive}.part-" '$2 ~ ("^\\*?" p) {gsub(/^\*/, "", $2); print $2}' "$CACHE_DIR/SHA256SUMS.txt" | LC_ALL=C sort)
  [ -n "$parts" ] || { echo "SHA256SUMS.txt missing entry for $archive" >&2; exit 1; }
  local part part_sha
  for part in $parts; do
    part_sha=$(sha_for "$part")
    echo "Fetching $part (sha256=${part_sha:0:12}...)"
    download_multi_mirror "$CACHE_DIR/$part" "$part_sha" "${BASE_URL}/${part}"
  done
  (for part in $parts; do cat "$CACHE_DIR/$part"; done) | zstd -dc | tar -xf - -C "$DEST"
  if [ "${KEEP_STOCK_ARCHIVES:-0}" != 1 ]; then
    for part in $parts; do rm -f "$CACHE_DIR/$part"; done
  fi
}

fetch_and_extract "RMX3820_15.0.0.320-stock-kernel-boot-dlkm.tar.zst" \
  boot.img dtbo.img init_boot.img recovery.img vbmeta.img vbmeta_system.img vbmeta_vendor.img vendor_boot.img vendor_dlkm.img system_dlkm.img payload_metadata.bin

if [ "$MODE" = "full" ]; then
  fetch_and_extract "RMX3820_15.0.0.320-stock-vendor.tar.zst" vendor.img
  fetch_and_extract "RMX3820_15.0.0.320-stock-odm.tar.zst" odm.img
  fetch_and_extract "RMX3820_15.0.0.320-stock-system.tar.zst" system.img system_ext.img product.img
  fetch_and_extract "RMX3820_15.0.0.320-stock-my_product.tar.zst" my_product.img my_manifest.img
  if grep -qs 'RMX3820_15\.0\.0\.320-stock-my_bigball\.tar\.zst' "$CACHE_DIR/SHA256SUMS.txt"; then
    fetch_and_extract "RMX3820_15.0.0.320-stock-my_bigball.tar.zst" \
      super-layout.json my_company.img my_bigball.img my_region.img my_carrier.img my_engineering.img my_heytap.img
  fi
  if grep -qs 'RMX3820_15\.0\.0\.320-stock-my_preload\.tar\.zst' "$CACHE_DIR/SHA256SUMS.txt"; then
    fetch_and_extract "RMX3820_15.0.0.320-stock-my_preload.tar.zst" my_preload.img
  fi
  if grep -qs 'RMX3820_15\.0\.0\.320-stock-my_stock\.tar\.zst' "$CACHE_DIR/SHA256SUMS.txt"; then
    fetch_and_extract "RMX3820_15.0.0.320-stock-my_stock.tar.zst" my_stock.img
  fi
fi

echo "Verified stock baseline staged at $DEST"
ls -lh "$DEST"/*.img "$DEST/payload_metadata.bin"
