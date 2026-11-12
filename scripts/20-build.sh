#!/usr/bin/env bash
# 20-build.sh — build the GKI kernel (common) with the unified config.
# Outputs: out200/dist/{Image,Image.gz,Image.lz4,System.map,*.ko,kernelsu.ko,rekernel.ko}
set -euo pipefail
KP_DIR=${KP_DIR:-$HOME/gt5_kernel_ab/kernel_platform}
cd "$KP_DIR"

export KMI_SYMBOL_LIST_STRICT_MODE=0
export OUT_DIR=$KP_DIR/out200
export DIST_DIR=$KP_DIR/out200/dist
export BUILD_CONFIG=common/build.config.gki.aarch64

build() { ./build/build.sh; }

# First pass may stop on the GKI modules-list check after adding kernelsu/rekernel.
set +e
build
rc=$?
set -e
if [ $rc -ne 0 ] && [ -f "$OUT_DIR/common/modules.order" ]; then
    cp "$OUT_DIR/common/modules.order" common/android/gki_aarch64_modules
    build
fi

ls -lh "$DIST_DIR"/Image "$DIST_DIR"/*.ko 2>/dev/null | tail -5
