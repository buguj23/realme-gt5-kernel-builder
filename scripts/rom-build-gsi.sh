#!/usr/bin/env bash
# Build and verify Project Infinity-X 2.9 official Treble GSI (infinity_gsi_arm64-userdebug)
# for non-destructive DSU-Sideloader-Plus testing against stock ColorOS 15.0.0.320 vendor.
set -euo pipefail

if [ "${OSSI_SIGPIPE_RESET:-0}" != 1 ] && command -v python3 >/dev/null 2>&1; then
  export OSSI_SIGPIPE_RESET=1
  exec python3 -c 'import os, signal, sys; signal.signal(signal.SIGPIPE, signal.SIG_DFL); os.execvp("bash", ["bash", sys.argv[1], *sys.argv[2:]])' "$0" "$@"
fi

usage() {
  cat <<'EOF'
rom-build-gsi.sh --src DIR --output DIR [--out-dir out/gsi] [--jobs N] [--vendor-property-contexts FILE]
EOF
}

HERE=$(cd "$(dirname "$0")" && pwd)
SRC=""
OUT=""
GSI_OUT_DIR="out/gsi"
JOBS="$(nproc)"
VENDOR_PC=""
while (( $# > 0 )); do
  case "$1" in
    --src) SRC=$2; shift 2 ;;
    --output) OUT=$2; shift 2 ;;
    --out-dir) GSI_OUT_DIR=$2; shift 2 ;;
    --jobs) JOBS=$2; shift 2 ;;
    --vendor-property-contexts) VENDOR_PC=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

fail() { echo "FAIL: $*" >&2; exit 1; }
[ -n "$SRC" ] && [ -n "$OUT" ] || { usage >&2; exit 2; }
[[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || fail "invalid --jobs: $JOBS"
SRC=$(realpath -e -- "$SRC")
OUT=$(realpath -m -- "$OUT")
if [ -n "$VENDOR_PC" ]; then VENDOR_PC=$(realpath -e -- "$VENDOR_PC"); fi
[ -f "$SRC/build/envsetup.sh" ] || fail "missing $SRC/build/envsetup.sh"

# Reversible staging: back up any patched files and restore on EXIT so rom-src stays clean.
BACKUP_DIR=$(mktemp -d -p "${TMPDIR:-/tmp}" ossi-gsi-backup.XXXXXXXX)
HIDDEN_DIR="$BACKUP_DIR/hidden"
mkdir -p "$HIDDEN_DIR"

PATCHED_FILES=(
  "build/make/target/product/gsi/Android.bp"
  "build/make/target/product/gsi/init.gsi.rc"
  "device/generic/common/gsi_product.mk"
  "device/generic/common/gsi_arm64.mk"
  "vendor/infinity/config/version.mk"
  "device/lineage/sepolicy/common/private/property_contexts"
  "device/lineage/sepolicy/common/private/file.te"
  "device/lineage/sepolicy/common/private/genfs_contexts"
  "device/lineage/sepolicy/common/private/init.te"
)
HIDE_TREES=(
  "vendor/realme"
  "device/realme"
  "device/oneplus"
  "hardware/oplus"
)

restore_tree() {
  for rel in "${PATCHED_FILES[@]}"; do
    if [ -f "$BACKUP_DIR/files/$rel" ]; then
      cp -a "$BACKUP_DIR/files/$rel" "$SRC/$rel" || true
    fi
  done
  for rel in "${HIDE_TREES[@]}"; do
    if [ -e "$HIDDEN_DIR/$rel" ] && [ ! -e "$SRC/$rel" ]; then
      mkdir -p "$(dirname "$SRC/$rel")"
      mv "$HIDDEN_DIR/$rel" "$SRC/$rel" || true
    fi
  done
  rm -rf "$BACKUP_DIR"
}
trap restore_tree EXIT

for rel in "${PATCHED_FILES[@]}"; do
  [ -f "$SRC/$rel" ] || fail "missing expected source file: $SRC/$rel"
  mkdir -p "$(dirname "$BACKUP_DIR/files/$rel")"
  cp -a "$SRC/$rel" "$BACKUP_DIR/files/$rel"
done

# Hide 64-bit-only device/vendor trees temporarily while Soong evaluates generic 64+32 GSI.
for rel in "${HIDE_TREES[@]}"; do
  if [ -d "$SRC/$rel" ]; then
    mkdir -p "$(dirname "$HIDDEN_DIR/$rel")"
    mv "$SRC/$rel" "$HIDDEN_DIR/$rel"
  fi
done

# 1) GSI build compatibility patches
sed -n '1,64p' "$BACKUP_DIR/files/build/make/target/product/gsi/Android.bp" \
  > "$SRC/build/make/target/product/gsi/Android.bp"
grep -v 'device/sample/etc/apns-full-conf.xml' "$BACKUP_DIR/files/device/generic/common/gsi_product.mk" \
  | sed '/^PRODUCT_COPY_FILES += \\$/d' > "$SRC/device/generic/common/gsi_product.mk"
# Expose android.hardware.fingerprint feature on ColorOS/OPLUS devices where OEM puts it in /my_product
cat >> "$SRC/device/generic/common/gsi_product.mk" <<'EOF'

PRODUCT_COPY_FILES += \
    frameworks/native/data/etc/android.hardware.fingerprint.xml:$(TARGET_COPY_OUT_SYSTEM_EXT)/etc/permissions/android.hardware.fingerprint.xml
EOF
sed 's/^PRODUCT_ENFORCE_ARTIFACT_PATH_REQUIREMENTS := true$/PRODUCT_ENFORCE_ARTIFACT_PATH_REQUIREMENTS := false/' \
  "$BACKUP_DIR/files/device/generic/common/gsi_arm64.mk" > "$SRC/device/generic/common/gsi_arm64.mk"
grep -v 'ro\.infinity\.device=\$(INFINITY_BUILD)' \
  "$BACKUP_DIR/files/vendor/infinity/config/version.mk" > "$SRC/vendor/infinity/config/version.mk"

# 2) Strip vendor/odm property_contexts entries from system_ext to prevent ColorOS
#    ro.vendor.dolby.dax.version TrieBuilder duplicate-prefix LOG(FATAL) -> recovery!
grep -Ev '^(ro\.vendor\.|vendor\.|persist\.vendor\.|ro\.odm\.)' \
  "$BACKUP_DIR/files/device/lineage/sepolicy/common/private/property_contexts" \
  > "$SRC/device/lineage/sepolicy/common/private/property_contexts"

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
printf '\ntype proc_phoenix, fs_type, proc_type;\n' >> "$SRC/device/lineage/sepolicy/common/private/file.te"
printf '\ngenfscon proc /phoenix u:object_r:proc_phoenix:s0\n' >> "$SRC/device/lineage/sepolicy/common/private/genfs_contexts"
printf '\nallow init proc_phoenix:file w_file_perms;\n' >> "$SRC/device/lineage/sepolicy/common/private/init.te"

# 5) Merge Simplified Chinese (zh-rCN) supplement translations for InfinitySuite/Settings/SystemUI/Launcher3/framework-res
python3 - "$HERE/rom-patch-source.py" "$SRC" <<'PY'
import pathlib, runpy, sys
mod = runpy.run_path(sys.argv[1])
count = mod["patch_infinity_zh_cn_translations"](pathlib.Path(sys.argv[2]))
print(f"Merged {count} Simplified Chinese (zh-rCN) supplement entries into GSI source tree")
PY

mkdir -p "$OUT"
(
  cd "$SRC"
  export OUT_DIR="$GSI_OUT_DIR"
  export DIST_DIR="$OUT_DIR/dist"
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
  lunch infinity_gsi_arm64-userdebug || fail "lunch infinity_gsi_arm64-userdebug failed"
  m -j"$JOBS" systemimage || fail "m systemimage failed"
  set -euo pipefail

  PRODUCT_OUT="$(get_abs_build_var PRODUCT_OUT)"
  HOST_BIN="$(get_abs_build_var HOST_OUT_EXECUTABLES)"
  SYS_IMG="$PRODUCT_OUT/system.img"
  [ -s "$SYS_IMG" ] || fail "missing built $SYS_IMG"

  # Verify zero TrieBuilder property_contexts collisions (optionally against stock vendor_property_contexts)
  python3 - "$HERE/rom-verify-delivery.py" \
    "$PRODUCT_OUT/system/etc/selinux/plat_property_contexts" \
    "$PRODUCT_OUT/system/system_ext/etc/selinux/system_ext_property_contexts" \
    "$PRODUCT_OUT/system/product/etc/selinux/product_property_contexts" \
    ${VENDOR_PC:+"$VENDOR_PC"} <<'PY'
import pathlib, runpy, sys
sys.path.insert(0, str(pathlib.Path(sys.argv[1]).parent))
mod = runpy.run_path(sys.argv[1])
ctxs = [(pathlib.Path(p).name, pathlib.Path(p).read_text(encoding="utf-8")) for p in sys.argv[2:] if p]
mod["check_property_contexts"](ctxs)
print(f"TrieBuilder property_contexts check passed ({len(ctxs)} files, 0 duplicates)")
PY

  RAW_IMG="$OUT/Infinity-X-2.9-gsi_arm64-ab.img"
  if file "$SYS_IMG" | grep -qi "Android sparse image"; then
    "$HOST_BIN/simg2img" "$SYS_IMG" "$RAW_IMG"
  else
    cp -f "$SYS_IMG" "$RAW_IMG"
  fi
  e2fsck -fn "$RAW_IMG" || true
  "$HOST_BIN/avbtool" info_image --image "$RAW_IMG" >/dev/null
  {
    echo "=== GSI build.prop ==="
    debugfs -R "cat system/build.prop" "$RAW_IMG" 2>/dev/null | grep -E "^ro\.(build\.display\.id|build\.fingerprint|build\.version\.release|build\.version\.sdk|build\.version\.security_patch|infinity\.|system\.build\.)" || true
    echo "=== GSI skip_mount.cfg ==="
    debugfs -R "cat system/system_ext/etc/init/config/skip_mount.cfg" "$RAW_IMG" 2>/dev/null || true
    echo "=== GSI init.gsi.rc (with OPLUS Phoenix disarm) ==="
    debugfs -R "cat system/system_ext/etc/init/init.gsi.rc" "$RAW_IMG" 2>/dev/null || true
    echo "=== GSI proc_phoenix SELinux rules ==="
    debugfs -R "cat system/system_ext/etc/selinux/system_ext_sepolicy.cil" "$RAW_IMG" 2>/dev/null | grep "proc_phoenix" || true
    echo "=== GSI system_ext_property_contexts vendor/odm check ==="
    if debugfs -R "cat system/system_ext/etc/selinux/system_ext_property_contexts" "$RAW_IMG" 2>/dev/null | grep -qE "^(ro\.vendor\.|vendor\.|persist\.vendor\.|ro\.odm\.)"; then
      echo "ERROR: vendor/odm entries still present in system_ext_property_contexts!" >&2
      exit 1
    fi
    echo "(0 vendor/odm entries — clean!)"
  } | tee "$OUT/gsi-verify.txt"

  if command -v pigz >/dev/null 2>&1; then
    pigz -p "$JOBS" -c -6 "$RAW_IMG" > "$RAW_IMG.gz"
  else
    gzip -c -6 "$RAW_IMG" > "$RAW_IMG.gz"
  fi
  (
    cd "$OUT"
    sha256sum Infinity-X-2.9-gsi_arm64-ab.img Infinity-X-2.9-gsi_arm64-ab.img.gz gsi-verify.txt > SHA256SUMS.txt
    sha256sum -c SHA256SUMS.txt
  )
)
