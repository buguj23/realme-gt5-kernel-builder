#!/usr/bin/env bash
# build-kernel-local.sh — Unified local build wrapper for Realme GT5 (5.15.149).
# Delegates to scripts/{00-fetch,10-patch,20-build,30-package}.sh with zero hardcoded user paths.
set -euo pipefail

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
KP_DIR=${KP_DIR:-$HOME/gt5_kernel_5_15_149/kernel_platform}
OUT=${OUT:-$REPO_DIR/out/artifacts}
KSU_MODE=${KSU_MODE:-Pure-OGKI}
DO_FETCH=0
DO_PATCH=0
STOCK_MODULES_DIR=${STOCK_MODULES_DIR:-}

usage() {
  cat <<'EOF'
build-kernel-local.sh [--fetch] [--patch] [--kp-dir DIR] [--out DIR]
  [--mode Pure-OGKI|YukiSU-LKM] [--stock-modules DIR]
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fetch) DO_FETCH=1; shift ;;
    --patch) DO_PATCH=1; shift ;;
    --kp-dir) KP_DIR=$2; shift 2 ;;
    --out) OUT=$2; shift 2 ;;
    --mode) KSU_MODE=$2; shift 2 ;;
    --stock-modules) STOCK_MODULES_DIR=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

export KP_DIR OUT KSU_MODE STOCK_MODULES_DIR
export WORK=${WORK:-$(dirname "$KP_DIR")}

echo "============================================================"
echo " Realme GT5 (RMX3820 / 5.15.149) Local OGKI Builder"
echo " Mode=$KSU_MODE  KP_DIR=$KP_DIR"
echo "============================================================"

[ "$DO_FETCH" = 1 ] && bash "$REPO_DIR/scripts/00-fetch.sh"
[ "$DO_PATCH" = 1 ] && bash "$REPO_DIR/scripts/10-patch.sh"
bash "$REPO_DIR/scripts/20-build.sh"
bash "$REPO_DIR/scripts/30-package.sh"
