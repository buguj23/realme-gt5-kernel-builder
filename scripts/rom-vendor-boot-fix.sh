#!/usr/bin/env bash
# rom-vendor-boot-fix.sh — keep a built vendor_boot on the stock envelope.
#
# The GT5 ABL loads vendor_boot using the addresses baked into the image header.
# mkbootimg's defaults (pagesize 0x800, kernel 0x10008000, ramdisk 0x11000000,
# tags 0x10000100) differ from this device's 0x1000 / 0x8000 / 0x1000000 / 0x100
# and were one of the three faults in the 2026-11-13 delivery.
#
# usage:
#   rom-vendor-boot-fix.sh <vendor_boot.img> --stock <stock vendor_boot.img>
#                          [--out DIR] [--check-only]
#
# exit 0 = header + first-stage module list match stock (or image was rebuilt),
#      1 = mismatch found in --check-only mode,
#      2 = tooling/IO problem.
set -euo pipefail

TARGET=${1:?usage: rom-vendor-boot-fix.sh <vendor_boot.img> --stock <stock.img> [--out DIR] [--check-only]}
shift
STOCK=""
OUT=""
CHECK_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --stock) STOCK=${2:?--stock needs a path}; shift 2 ;;
    --out) OUT=${2:?--out needs a path}; shift 2 ;;
    --check-only) CHECK_ONLY=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ -n "$STOCK" ] || { echo "--stock is required" >&2; exit 2; }
[ -f "$TARGET" ] || { echo "missing $TARGET" >&2; exit 2; }
[ -f "$STOCK" ] || { echo "missing stock $STOCK" >&2; exit 2; }
command -v unpack_bootimg >/dev/null || { echo "unpack_bootimg not found" >&2; exit 2; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

unpack_bootimg --boot_img "$STOCK"  --out "$WORK/stock"  >/dev/null
unpack_bootimg --boot_img "$TARGET" --out "$WORK/target" >/dev/null

args_of() { unpack_bootimg --boot_img "$1" --format mkbootimg 2>/dev/null; }
STOCK_ARGS=$(args_of "$STOCK")
TARGET_ARGS=$(args_of "$TARGET")

# Only the fields ABL uses; --dtb/--vendor_bootconfig paths differ per directory.
envelope() {
  printf '%s\n' "$1" | tr ' ' '\n' | grep -A1 -E '^--(pagesize|base|kernel_offset|ramdisk_offset|tags_offset|dtb_offset|header_version)$' | paste - - | sort
}
S_ENV=$(envelope "$STOCK_ARGS")
T_ENV=$(envelope "$TARGET_ARGS")

fail=0
if [ "$S_ENV" != "$T_ENV" ]; then
  echo "HEADER MISMATCH (stock vs target):"
  diff <(printf '%s\n' "$S_ENV") <(printf '%s\n' "$T_ENV") || true
  fail=1
else
  echo "header envelope matches stock"
fi

# First-stage module list: stock ordering is what the kernel needs to boot.
extract_modules() { # $1 = unpacked dir, $2 = output file
  local d=$1 out=$2
  local frag="$d/vendor_ramdisk00"
  [ -f "$frag" ] || { : > "$out"; return; }
  local tmp="$WORK/rd_$(basename "$d")"
  mkdir -p "$tmp"
  if file -b "$frag" | grep -qi lz4; then lz4 -dc "$frag" > "$tmp/rd.cpio"
  elif file -b "$frag" | grep -qi gzip; then gzip -dc "$frag" > "$tmp/rd.cpio"
  else cat "$frag" > "$tmp/rd.cpio"; fi
  ( cd "$tmp" && cpio -idm --quiet < rd.cpio 2>/dev/null || true )
  if [ -f "$tmp/lib/modules/modules.load" ]; then
    sort "$tmp/lib/modules/modules.load" > "$out"
  else
    : > "$out"
  fi
}
extract_modules "$WORK/stock"  "$WORK/stock.load"
extract_modules "$WORK/target" "$WORK/target.load"

S_N=$(wc -l < "$WORK/stock.load"); T_N=$(wc -l < "$WORK/target.load")
echo "modules.load: stock $S_N lines, target $T_N lines"
if ! diff -q "$WORK/stock.load" "$WORK/target.load" >/dev/null; then
  echo "FIRST-STAGE LIST DIFFERS (missing from target):"
  comm -23 "$WORK/stock.load" "$WORK/target.load" | head -20
  fail=1
fi

if [ $fail -eq 0 ]; then
  echo "vendor_boot OK"
  exit 0
fi
if [ $CHECK_ONLY -eq 1 ]; then
  echo "check-only: refusing to rewrite" >&2
  exit 1
fi

OUT=${OUT:-$(dirname "$TARGET")}
mkdir -p "$OUT"
# Rebuild on the stock envelope: stock dtb/bootconfig, target vendor ramdisk.
# shellcheck disable=SC2086
mkbootimg $STOCK_ARGS \
  --vendor_ramdisk_fragment "$WORK/target/vendor_ramdisk00" \
  -o "$OUT/vendor_boot.fixed.img"
echo "wrote $OUT/vendor_boot.fixed.img"
unpack_bootimg --boot_img "$OUT/vendor_boot.fixed.img" | sed -n '1,8p'
