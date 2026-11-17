#!/usr/bin/env bash
# stock-module-lists.sh — turn official images into the inputs the stager needs.
#
#   stock-modules.load   first-stage order, taken from vendor_boot
#   stock-modules/       flat pool of every .ko the stock firmware ships
#
# usage: stock-module-lists.sh <stock-dir> <out-dir>
#   <stock-dir> must contain vendor_boot.img, vendor_dlkm.img, system_dlkm.img
set -euo pipefail

SRC=${1:?usage: stock-module-lists.sh <stock-dir> <out-dir>}
OUT=${2:?usage: stock-module-lists.sh <stock-dir> <out-dir>}
mkdir -p "$OUT/stock-modules" "$OUT/_work"

need() { [ -f "$SRC/$1" ] || { echo "missing $SRC/$1" >&2; exit 2; }; }
need vendor_boot.img

echo "[1/4] vendor_boot first-stage list"
rm -rf "$OUT/_work/vb"; mkdir -p "$OUT/_work/vb"
unpack_bootimg --boot_img "$SRC/vendor_boot.img" --out "$OUT/_work/vb" >/dev/null
frag="$OUT/_work/vb/vendor_ramdisk00"
mkdir -p "$OUT/_work/vb/rd"
if file -b "$frag" | grep -qi lz4; then lz4 -dc "$frag" > "$OUT/_work/vb/rd.cpio"
elif file -b "$frag" | grep -qi gzip; then gzip -dc "$frag" > "$OUT/_work/vb/rd.cpio"
else cat "$frag" > "$OUT/_work/vb/rd.cpio"; fi
( cd "$OUT/_work/vb/rd" && cpio -idm --quiet < ../rd.cpio 2>/dev/null || true )
cp "$OUT/_work/vb/rd/lib/modules/modules.load" "$OUT/stock-modules.load"
cp "$OUT/_work/vb/rd/lib/modules/"*.ko "$OUT/stock-modules/" 2>/dev/null || true
echo "      $(wc -l < "$OUT/stock-modules.load") entries"

extract_fs() { # <image> <name>
  local img="$1" name="$2" dir="$OUT/_work/$2"
  [ -f "$img" ] || { echo "      $name absent, skipped"; return; }
  mkdir -p "$dir"
  if file -b "$img" | grep -qi erofs; then
    fsck.erofs --extract="$dir" "$img" >/dev/null 2>&1 || true
  else
    debugfs -R "rdump / $dir" "$img" >/dev/null 2>&1 || true
  fi
  find "$dir" -name '*.ko' -exec cp -n {} "$OUT/stock-modules/" \;
}

echo "[2/4] vendor_dlkm"
extract_fs "$SRC/vendor_dlkm.img" vdlkm
echo "[3/4] system_dlkm"
extract_fs "$SRC/system_dlkm.img" sdlkm

echo "[4/4] pool"
echo "      $(ls "$OUT/stock-modules"/*.ko 2>/dev/null | wc -l) modules in $OUT/stock-modules"
[ "$(ls "$OUT/stock-modules"/*.ko 2>/dev/null | wc -l)" -gt 100 ] || {
  echo "pool too small — check the stock images" >&2; exit 1; }
