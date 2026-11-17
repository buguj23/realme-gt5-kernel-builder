#!/usr/bin/env bash
# rom-provision-deps.sh — fetch the trees the GT5 device config needs but the
# Infinity-X/Lineage manifests do not carry.
#
#   device/oneplus/sm8550-common      platform HALs, init, vintf, overlays
#   hardware/oplus                    Oplus HALs + sepolicy/qti
#   hardware/pixelworks/interfaces    referenced by sm8550-common/common.mk
#
# usage: rom-provision-deps.sh <src-dir> [--branch lineage-23.2] [--mirror URL]
#   branch must match the manifest's Android version:
#     A16 -> lineage-23.2,  A15 -> lineage-22.2,  A14 -> lineage-21
set -euo pipefail

SRC=${1:?usage: rom-provision-deps.sh <src-dir> [--branch BR] [--mirror URL]}
shift || true
BRANCH=lineage-23.2
MIRROR=https://mirrors.tuna.tsinghua.edu.cn/git/lineageOS/LineageOS

while [ $# -gt 0 ]; do
  case "$1" in
    --branch) BRANCH=${2:?}; shift 2 ;;
    --mirror) MIRROR=${2:?}; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

ensure() { # <path> <repo>
  local path=$1 repo=$2
  if [ -d "$SRC/$path/.git" ]; then
    echo "  present $path"
    return 0
  fi
  mkdir -p "$(dirname "$SRC/$path")"
  echo "  clone   $path ($repo @ $BRANCH)"
  git clone --depth=1 -b "$BRANCH" -q "$MIRROR/$repo.git" "$SRC/$path" \
    || { echo "  FAILED  $repo @ $BRANCH" >&2; return 1; }
}

ensure device/oneplus/sm8550-common   android_device_oneplus_sm8550-common
ensure hardware/oplus                 android_hardware_oplus
ensure hardware/pixelworks/interfaces android_hardware_pixelworks_interfaces
echo "deps ready in $SRC"
