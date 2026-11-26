#!/usr/bin/env bash
# Build and verify Project Infinity-X 3.12 (Android 16 QPR2 / bp4a) Treble GSI (infinity_gsi_arm64)
# for Realme GT5 (RMX3820_15.0.0.320 / 5.15.149 OGKI kernel baseline) via DSU-Sideloader-Plus.
#
# Includes:
#   - Upstream Infinity-X 16 GSI makefile & Soong fixes (infinity_gsi_arm64-bp4a-user/userdebug)
#   - ColorOS property_contexts vendor/odm collision strip + TrieBuilder verification
#   - OPLUS Phoenix 250s boot watchdog disarm + Enforcing proc_phoenix SELinux rules
#   - Realme GT5 factory auto-brightness lux->nits overlay + android.hardware.fingerprint.xml
#   - OPLUS/OPPO optical UDFPS SurfaceFlinger Z-order fix (0x41000005 / 0x41000033)
#   - yokeshiq custom-ROM / LineageOS anti-detection patches rebased for Android 16
#   - Unified Simplified Chinese (zh-rCN) localization (20 packages, ~9,000 entries)
#   - Mainland China captive-portal default URLs (NetworkStack)
set -euo pipefail

if [ "${OSSI_SIGPIPE_RESET:-0}" != 1 ] && command -v python3 >/dev/null 2>&1; then
  export OSSI_SIGPIPE_RESET=1
  exec python3 -c 'import os, signal, sys; signal.signal(signal.SIGPIPE, signal.SIG_DFL); os.execvp("bash", ["bash", sys.argv[1], *sys.argv[2:]])' "$0" "$@"
fi

usage() {
  cat <<'EOF'
rom-build-gsi.sh --src DIR --output DIR [OPTIONS]

Options:
  --src DIR                      Infinity-X 16 (3.12) Android source checkout
  --output DIR                   Output directory for verified .img, .img.gz, SHA256SUMS.txt
  --out-dir PATH                 Build OUT_DIR relative to --src (default: out/gsi)
  --variant user|userdebug       Build variant (default: user)
  --release NAME                 Android trunk release config (default: bp4a)
  --gapps true|false             Set WITH_GAPPS for Infinity-X build (default: false)
  --lineage-hide true|false      Apply yokeshiq anti-detection patches (default: true)
  --jobs N                       Parallel make/ninja jobs (default: auto-tuned to host RAM)
  --vendor-property-contexts F   Optional stock vendor_property_contexts to cross-check
EOF
}

HERE=$(cd "$(dirname "$0")" && pwd)
SRC=""
OUT=""
GSI_OUT_DIR="out/gsi"
VARIANT="user"
TARGET_RELEASE="bp4a"
WITH_GAPPS="false"
LINEAGE_HIDE="true"
JOBS=""
VENDOR_PC=""

while (( $# > 0 )); do
  case "$1" in
    --src) SRC=$2; shift 2 ;;
    --output) OUT=$2; shift 2 ;;
    --out-dir) GSI_OUT_DIR=$2; shift 2 ;;
    --variant) VARIANT=$2; shift 2 ;;
    --release) TARGET_RELEASE=$2; shift 2 ;;
    --gapps) WITH_GAPPS=$2; shift 2 ;;
    --lineage-hide) LINEAGE_HIDE=$2; shift 2 ;;
    --jobs) JOBS=$2; shift 2 ;;
    --vendor-property-contexts) VENDOR_PC=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

fail() { echo "FAIL: $*" >&2; exit 1; }
[ -n "$SRC" ] && [ -n "$OUT" ] || { usage >&2; exit 2; }
case "$VARIANT" in user|userdebug) ;; *) fail "invalid --variant: $VARIANT (use user or userdebug)" ;; esac
case "$WITH_GAPPS" in true|false) ;; *) fail "invalid --gapps: $WITH_GAPPS (use true or false)" ;; esac
case "$LINEAGE_HIDE" in true|false) ;; *) fail "invalid --lineage-hide: $LINEAGE_HIDE (use true or false)" ;; esac

# Auto-tune parallelism and Go/JVM memory on constrained hosts (<24 GiB RAM) to avoid R8 OOM kills.
HOST_RAM_GIB=$(awk '/MemTotal:/ {printf "%d", $2/1048576}' /proc/meminfo 2>/dev/null || echo 32)
if [ -z "$JOBS" ]; then
  if [ "$HOST_RAM_GIB" -le 20 ]; then
    JOBS=4
  else
    JOBS=$(nproc)
  fi
fi
[[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || fail "invalid --jobs: $JOBS"

if [ "$HOST_RAM_GIB" -le 20 ]; then
  export SOONG_GOGC="${SOONG_GOGC:-40}"
  export SOONG_GOMEMLIMIT="${SOONG_GOMEMLIMIT:-7GiB}"
  export SOONG_GOMAXPROCS="${SOONG_GOMAXPROCS:-8}"
  export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:--Xmx2560M}"
fi

SRC=$(realpath -e -- "$SRC")
OUT=$(realpath -m -- "$OUT")
if [ -n "$VENDOR_PC" ]; then VENDOR_PC=$(realpath -e -- "$VENDOR_PC"); fi
[ -f "$SRC/build/envsetup.sh" ] || fail "missing $SRC/build/envsetup.sh"

# Reversible staging: back up modified source files and restore on EXIT so rom-src stays clean.
BACKUP_DIR=$(mktemp -d -p "${TMPDIR:-/tmp}" gt5-gsi312-backup.XXXXXXXX)
PATCHED_FILES=(
  "build/soong/ui/build/soong.go"
  "build/blueprint/bootstrap/command.go"
  "build/make/target/board/BoardConfigGsiCommon.mk"
  "build/make/target/product/gsi_release.mk"
  "build/make/target/product/gsi/Android.bp"
  "build/make/target/product/gsi/init.gsi.rc"
  "device/generic/common/gsi_product.mk"
  "device/generic/common/gsi_arm64.mk"
  "device/generic/common/gsi_system_ext.mk"
  "vendor/infinity/build/target/product/AndroidProducts.mk"
  "vendor/infinity/build/target/product/infinity_gsi_arm64.mk"
  "vendor/infinity/config/version.mk"
  "device/lineage/sepolicy/common/private/property_contexts"
  "device/lineage/sepolicy/common/private/adbd.te"
  "device/lineage/sepolicy/common/private/backuptool.te"
  "device/lineage/sepolicy/common/private/file.te"
  "device/lineage/sepolicy/common/private/genfs_contexts"
  "device/lineage/sepolicy/common/private/init.te"
  "frameworks/native/services/surfaceflinger/CompositionEngine/src/UdfpsExtension.cpp"
  "packages/modules/NetworkStack/res/values/config.xml"
  "packages/modules/NetworkStack/res/values-mcc460/config.xml"
  "packages/apps/Updater/app/src/main/java/com/infinity/updater/misc/Constants.java"
  "bionic/libc/bionic/custom_rom_hide.h"
  "bionic/libc/bionic/custom_rom_hide.cpp"
  "bionic/libc/bionic/open.cpp"
  "frameworks/base/core/java/android/content/res/ApkAssets.java"
  "frameworks/base/core/java/android/content/res/AssetManager.java"
  "frameworks/base/core/java/android/content/res/Resources.java"
  "frameworks/base/core/java/android/os/ServiceManager.java"
  "frameworks/base/core/java/android/os/SystemProperties.java"
  "frameworks/base/packages/SettingsProvider/src/com/android/providers/settings/SettingsProvider.java"
  "frameworks/base/services/core/java/com/android/server/am/BroadcastController.java"
  "frameworks/base/services/core/java/com/android/server/pm/ComputerEngine.java"
  "frameworks/base/services/core/java/com/android/server/pm/PackageManagerService.java"
  "frameworks/base/services/core/java/com/android/server/pm/ResolveIntentHelper.java"
  "frameworks/base/services/core/java/com/android/server/pm/parsing/PackageInfoUtils.java"
  "frameworks/base/services/core/java/com/android/server/pm/permission/PermissionManagerService.java"
)

INIT_TE_CREATED=0
restore_tree() {
  for rel in "${PATCHED_FILES[@]}"; do
    if [ -f "$BACKUP_DIR/files/$rel" ]; then
      cp -a "$BACKUP_DIR/files/$rel" "$SRC/$rel" || true
    fi
  done
  if [ "$INIT_TE_CREATED" = 1 ]; then
    rm -f "$SRC/device/lineage/sepolicy/common/private/init.te"
  fi
  if [ -d "$HERE/../gsi/translations/zh-rCN" ]; then
    while IFS= read -r rel_xml; do
      rm -f "$SRC/$rel_xml"
    done < <(cd "$HERE/../gsi/translations/zh-rCN" && find . -type f -name 'infinity_zh_cn_extra.xml' | sed 's|^\./||')
  fi
  rm -rf "$SRC/device/generic/common/overlay_gt5_brightness" "$BACKUP_DIR"
}
trap restore_tree EXIT

for rel in "${PATCHED_FILES[@]}"; do
  if [ -f "$SRC/$rel" ]; then
    mkdir -p "$(dirname "$BACKUP_DIR/files/$rel")"
    cp -a "$SRC/$rel" "$BACKUP_DIR/files/$rel"
  fi
done

for required in \
  "build/make/target/product/gsi/init.gsi.rc" \
  "device/generic/common/gsi_product.mk" \
  "device/lineage/sepolicy/common/private/property_contexts" \
  "device/lineage/sepolicy/common/private/file.te" \
  "device/lineage/sepolicy/common/private/genfs_contexts"; do
  [ -f "$SRC/$required" ] || fail "missing expected source file: $SRC/$required"
done

# 1) Apply Python source patches (Infinity-X 3.12 GSI fixes, UDFPS, user sepolicy, yokeshiq stealth, zh-rCN, CN captive portal)
PATCH_ARGS=(--gapps "$WITH_GAPPS")
if [ "$LINEAGE_HIDE" != "true" ]; then
  PATCH_ARGS+=(--no-lineage-hide)
fi
python3 "$HERE/rom-patch-source.py" "$SRC" "${PATCH_ARGS[@]}"

# 2) Expose android.hardware.fingerprint feature on ColorOS/OPLUS devices (OEM puts it in /my_product)
#    and apply Realme GT5 factory auto-brightness lux-to-nits curve overlay.
mkdir -p "$SRC/device/generic/common/overlay_gt5_brightness/frameworks/base/core/res/res/values"
cp -f "$HERE/../gsi/overlay/gt5/frameworks/base/core/res/res/values/config.xml" \
      "$SRC/device/generic/common/overlay_gt5_brightness/frameworks/base/core/res/res/values/config.xml"
cat >> "$SRC/device/generic/common/gsi_product.mk" <<'EOF'

PRODUCT_PACKAGE_OVERLAYS += \
    device/generic/common/overlay_gt5_brightness

PRODUCT_COPY_FILES += \
    frameworks/native/data/etc/android.hardware.fingerprint.xml:$(TARGET_COPY_OUT_SYSTEM_EXT)/etc/permissions/android.hardware.fingerprint.xml
EOF

# 3) Disarm OPLUS Phoenix 250s boot watchdog on Realme/OnePlus/OPPO stock kernels
cat >> "$SRC/build/make/target/product/gsi/init.gsi.rc" <<'EOF'

# Disarm OPLUS Phoenix boot watchdog on Realme/OnePlus/OPPO stock kernels
on post-fs
    write /proc/phoenix "SET_BOOTSTAGE@NATIVE_INIT_POST_FS"

on property:sys.boot_completed=1
    write /proc/phoenix "SET_BOOTSTAGE@ANDROID_BOOT_COMPLETED"
    write /proc/phoenix "SET_BOOTSTAGE@PHOENIX_BOOT_COMPLETED"
EOF

# 4) Label /proc/phoenix and grant init write access under Enforcing SELinux
#    (device/lineage/sepolicy/common/private/init.te is absent on Infinity-X 16; create cleanly if missing)
if [ ! -f "$SRC/device/lineage/sepolicy/common/private/init.te" ]; then
  INIT_TE_CREATED=1
fi
printf '\ntype proc_phoenix, fs_type, proc_type;\n' >> "$SRC/device/lineage/sepolicy/common/private/file.te"
printf '\ngenfscon proc /phoenix u:object_r:proc_phoenix:s0\n' >> "$SRC/device/lineage/sepolicy/common/private/genfs_contexts"
printf '\nallow init proc_phoenix:file w_file_perms;\n' >> "$SRC/device/lineage/sepolicy/common/private/init.te"

mkdir -p "$OUT"
FLAVOR="vanilla"
[ "$WITH_GAPPS" = "true" ] && FLAVOR="gapps"
# Infinity-X 16 build/envsetup.sh parses single-arg hyphenated targets as `<product>-<variant>`
# and auto-selects `TARGET_RELEASE=bp4a` from `build/make/core/build_id.mk` + sets `INFINITY_BUILD=gsi_arm64`.
LUNCH_TARGET="infinity_gsi_arm64-${VARIANT}"

echo "=== Building Project Infinity-X 3.12 GSI: ${LUNCH_TARGET} (release=${TARGET_RELEASE}, WITH_GAPPS=${WITH_GAPPS}, LINEAGE_HIDE=${LINEAGE_HIDE}, JOBS=${JOBS}) ==="
(
  cd "$SRC"
  export OUT_DIR="$GSI_OUT_DIR"
  export DIST_DIR="$OUT_DIR/dist"
  export WITH_GAPPS="$WITH_GAPPS"
  unset INLINE_KERNEL_BUILDING || true
  set +euo pipefail
  if [ "${USE_CCACHE:-0}" != 1 ]; then
    export CCACHE_EXEC="${CCACHE_EXEC:-disabled}" USE_CCACHE=0
  fi
  source build/envsetup.sh
  if [ "${USE_CCACHE:-0}" != 1 ]; then
    unset CCACHE_EXEC || true
    export USE_CCACHE=0
  fi
  lunch "$LUNCH_TARGET" || fail "lunch $LUNCH_TARGET failed"
  m -j"$JOBS" systemimage || fail "m systemimage failed"
  set -euo pipefail

  PRODUCT_OUT="$(get_abs_build_var PRODUCT_OUT)"
  HOST_BIN="$(get_abs_build_var HOST_OUT_EXECUTABLES)"
  SYS_IMG="$PRODUCT_OUT/system.img"
  [ -s "$SYS_IMG" ] || fail "missing built $SYS_IMG"

  # Verify zero TrieBuilder property_contexts collisions (optionally against stock vendor_property_contexts)
  python3 "$HERE/gsi_verify.py" property-contexts \
    "$PRODUCT_OUT/system/etc/selinux/plat_property_contexts" \
    "$PRODUCT_OUT/system/system_ext/etc/selinux/system_ext_property_contexts" \
    "$PRODUCT_OUT/system/product/etc/selinux/product_property_contexts" \
    ${VENDOR_PC:+"$VENDOR_PC"}

  IMG_BASE="Infinity-X-3.12-gsi_arm64-${FLAVOR}-${VARIANT}-ab"
  RAW_IMG="$OUT/${IMG_BASE}.img"
  if file "$SYS_IMG" | grep -qi "Android sparse image"; then
    "$HOST_BIN/simg2img" "$SYS_IMG" "$RAW_IMG"
  else
    cp -f "$SYS_IMG" "$RAW_IMG"
  fi
  e2fsck -fn "$RAW_IMG" || true
  "$HOST_BIN/avbtool" info_image --image "$RAW_IMG" >/dev/null

  VERIFY_ARGS=(--img "$RAW_IMG" --variant "$VARIANT" --report "$OUT/gsi-verify.txt")
  [ "$LINEAGE_HIDE" = "true" ] || VERIFY_ARGS+=(--no-lineage-hide)
  python3 "$HERE/gsi_verify.py" image "${VERIFY_ARGS[@]}"

  if command -v pigz >/dev/null 2>&1; then
    pigz -p "$JOBS" -c -6 "$RAW_IMG" > "$RAW_IMG.gz"
  else
    gzip -c -6 "$RAW_IMG" > "$RAW_IMG.gz"
  fi
  (
    cd "$OUT"
    sha256sum "${IMG_BASE}.img" "${IMG_BASE}.img.gz" gsi-verify.txt > SHA256SUMS.txt
    sha256sum -c SHA256SUMS.txt
  )
)
