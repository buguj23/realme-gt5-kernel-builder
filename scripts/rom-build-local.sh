#!/usr/bin/env bash
# Build one Realme GT5 ROM baseline. Also used by the self-hosted CI job.
set -euo pipefail

usage() {
  cat <<'EOF'
rom-build-local.sh --src DIR --branch 5.15.180 --pkg DIR --stock-images DIR
  [--sync] [--pool DIR] [--blobs DIR --blob-list FILE] [--output DIR]
  [--payload-metadata FILE] [--stock-layout FILE] [--stock-slot a|b] [--jobs N] [--min-free-gb N]
  [--oem-key FILE] [--avb-key FILE] [--check-only]
EOF
}

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/.." && pwd)
SRC=""; BR=""; PKG=""; STOCK=""; OEM_KEY=""; AVB_KEY=""
BLOBS=""; BLOB_LIST=""; POOL=""; OUT=""; METADATA=""; LAYOUT=""; STOCK_SLOT=""
LUNCH=""; DEPS_INPUT=""; SYNC=0; CHECK=0; JOBS=$(nproc); MIN_FREE=120
while (( $# > 0 )); do
  case "$1" in
    --src) SRC=$2; shift 2 ;;
    --branch) BR=$2; shift 2 ;;
    --pkg) PKG=$2; shift 2 ;;
    --stock-images) STOCK=$2; shift 2 ;;
    --oem-key) OEM_KEY=$2; shift 2 ;;
    --avb-key) AVB_KEY=$2; shift 2 ;;
    --stock-layout) LAYOUT=$2; shift 2 ;;
    --stock-slot) STOCK_SLOT=$2; shift 2 ;;
    --payload-metadata) METADATA=$2; shift 2 ;;
    --output) OUT=$2; shift 2 ;;
    --pool) POOL=$2; shift 2 ;;
    --blobs) BLOBS=$2; shift 2 ;;
    --blob-list) BLOB_LIST=$2; shift 2 ;;
    --lunch) LUNCH=$2; shift 2 ;;
    --deps-branch) DEPS_INPUT=$2; shift 2 ;;
    --jobs) JOBS=$2; shift 2 ;;
    --min-free-gb) MIN_FREE=$2; shift 2 ;;
    --sync) SYNC=1; shift ;;
    --check-only) CHECK=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

fail() { echo "FAIL: $*" >&2; exit 1; }
[ -n "$SRC" ] && [ -n "$BR" ] && [ -n "$PKG" ] && [ -n "$STOCK" ] ||
  { usage >&2; exit 2; }
[[ "$JOBS" =~ ^[1-9][0-9]*$ && "$MIN_FREE" =~ ^[0-9]+$ ]] || fail "invalid jobs or disk limit"
[ -z "$BLOBS" ] || [ -n "$BLOB_LIST" ] || fail "--blobs requires its --blob-list"
if [ -n "$AVB_KEY" ]; then AVB_KEY=$(realpath -e -- "$AVB_KEY"); fi
if [ -n "$BLOBS" ]; then BLOBS=$(realpath -e -- "$BLOBS"); fi
if [ -n "$BLOB_LIST" ]; then BLOB_LIST=$(realpath -e -- "$BLOB_LIST"); fi
if [ -n "$POOL" ]; then POOL=$(realpath -e -- "$POOL"); fi
PKG=$(realpath -e -- "$PKG")
STOCK=$(realpath -e -- "$STOCK")
if [ -n "$OEM_KEY" ]; then OEM_KEY=$(realpath -e -- "$OEM_KEY"); fi
METADATA=$(realpath -e -- "${METADATA:-$STOCK/payload_metadata.bin}")
LAYOUT=$(realpath -e -- "${LAYOUT:-$STOCK/super-layout.json}")
SRC=$(realpath -m -- "$SRC")

profile() { python3 "$HERE/rom-check-inputs.py" profile --branch "$BR" --field "$1"; }
BR=$(profile branch)
MANIFEST=$(profile source_manifest)
SOURCE_BRANCH=$(profile source_branch)
DEPS_BR=$(profile deps_branch)
PRODUCT=$(profile product)
SDK=$(profile api)
WANT_LUNCH="$PRODUCT-userdebug"
if [ "$PRODUCT" = lineage_ossi ]; then WANT_LUNCH="$PRODUCT-trunk_staging-userdebug"; fi
[ -z "$LUNCH" ] || [ "$LUNCH" = "$WANT_LUNCH" ] || fail "$BR requires lunch $WANT_LUNCH"
[ -z "$DEPS_INPUT" ] || [ "$DEPS_INPUT" = "$DEPS_BR" ] || fail "$BR requires dependencies $DEPS_BR"
OUT=$(realpath -m -- "${OUT:-$SRC/ossi-artifacts/$BR}")
[ "$CHECK" = 1 ] || [ ! -e "$OUT" ] || fail "output $OUT exists, choose a new --output directory"

for command in python3 avbtool fdtget fdtput; do command -v "$command" >/dev/null || fail "$command not in PATH"; done
if [ "$CHECK" = 0 ]; then
  for command in git repo rsync; do command -v "$command" >/dev/null || fail "$command not in PATH"; done
  mkdir -p "$SRC"
  FREE=$(df -BG --output=avail "$SRC" | tail -1 | tr -dc '0-9')
  [ "$FREE" -ge "$MIN_FREE" ] || fail "not enough disk space: $FREE GiB free, need $MIN_FREE"
fi

WORK=$(mktemp -d -p "$SRC" .ossi-build.XXXXXXXX 2>/dev/null || mktemp -d -p "${TMPDIR:-/tmp}" ossi-build.XXXXXXXX)
VENDOR_BACKUP=""
VENDOR_READY=0
VENDOR_GENERATING=0
cleanup() {
  if [ "$VENDOR_GENERATING" = 1 ] && [ "$VENDOR_READY" = 0 ]; then
    if [ -e "$SRC/vendor/realme/ossi" ]; then
      mv -T -- "$SRC/vendor/realme/ossi" "$WORK/vendor-incomplete"
    fi
    if [ -n "$VENDOR_BACKUP" ]; then
      mv -T -- "$VENDOR_BACKUP" "$SRC/vendor/realme/ossi"
    fi
  fi
  rm -rf -- "$WORK"
}
trap cleanup EXIT
stock=(--branch "$BR" --stock-images "$STOCK" --payload-metadata "$METADATA")
python3 "$HERE/rom-check-inputs.py" stock "${stock[@]}"
if [ -z "$POOL" ]; then
  POOL="$WORK/pool"
  bash "$HERE/stock-module-lists.sh" "$STOCK" "$POOL" --branch "$BR" --payload-metadata "$METADATA"
fi
mkdir -p "$WORK/device"
cp "$REPO_ROOT/rom/device/realme/ossi/fstab.default" "$WORK/device/"
part_args=(--images "$STOCK" --device-tree "$WORK/device" --branch "$BR" --payload-metadata "$METADATA"
           --stock-layout "$LAYOUT")
if [ -n "$OEM_KEY" ]; then part_args+=(--oem-key "$OEM_KEY"); fi
if [ -n "$STOCK_SLOT" ]; then part_args+=(--stock-slot "$STOCK_SLOT"); fi
kernel_args=(--package "$PKG" --device-tree "$WORK/device" --stock-pool "$POOL" "${stock[@]}")
if [ "$CHECK" = 1 ]; then
  python3 "$HERE/rom-stage-partitions.py" "${part_args[@]}" --dry-run
  python3 "$HERE/rom-stage-kernel.py" "${kernel_args[@]}" --dry-run
  if [ -n "$BLOBS" ]; then
    python3 "$HERE/rom-check-inputs.py" stock "${stock[@]}" --blobs "$BLOBS" --blob-list "$BLOB_LIST"
  fi
  if [ -d "$SRC/.repo" ]; then
    python3 "$HERE/rom-check-inputs.py" source --branch "$BR" --src "$SRC"
  fi
  echo "Stock, kernel, and OEM partition checks passed for $BR"
  exit 0
fi
python3 "$HERE/rom-stage-partitions.py" "${part_args[@]}"
python3 "$HERE/rom-stage-kernel.py" "${kernel_args[@]}"

if [ "$SYNC" = 1 ]; then
  bash "$HERE/rom-sync.sh" --dir "$SRC" --manifest "$MANIFEST" --branch "$SOURCE_BRANCH" --jobs "$JOBS"
fi
python3 "$HERE/rom-check-inputs.py" source --branch "$BR" --src "$SRC"
[ -f "$SRC/build/envsetup.sh" ] || fail "source tree sync is incomplete"
bash "$HERE/rom-provision-deps.sh" "$SRC" --branch "$DEPS_BR"
if [ -z "$BLOBS" ]; then
  BLOBS="$WORK/blobs"
  selected="$WORK/proprietary-files.txt"
  python3 "$HERE/rom-select-blobs.py" --images "$STOCK" --label "$BR" \
    --base-list "${BLOB_LIST:-$SRC/device/oneplus/sm8550-common/proprietary-files.txt}" \
    --payload-metadata "$METADATA" --materialize "$BLOBS" --out "$selected"
  BLOB_LIST=$selected
fi
python3 "$HERE/rom-check-inputs.py" stock "${stock[@]}" --blobs "$BLOBS" --blob-list "$BLOB_LIST"

mkdir -p "$SRC/.ossi"
# Keep generated files out of independently managed device/vendor projects.
for dir in device/realme/ossi device/realme/sm8550-ogki vendor/realme/ossi; do
  [ ! -e "$SRC/$dir/.git" ] || fail "$SRC/$dir is managed by repo, use a dedicated ossi source checkout"
done
mkdir -p "$SRC/device/realme/ossi" "$SRC/device/realme/sm8550-ogki" "$SRC/vendor/realme"
rsync -a --exclude prebuilt/ "$REPO_ROOT/rom/device/realme/ossi/" "$SRC/device/realme/ossi/"
rsync -a "$REPO_ROOT/rom/device/realme/sm8550-ogki/" "$SRC/device/realme/sm8550-ogki/"
mkdir -p "$SRC/device/realme/ossi/prebuilt"
rsync -a --delete "$WORK/device/prebuilt/" "$SRC/device/realme/ossi/prebuilt/"
python3 "$HERE/rom-check-inputs.py" profile --branch "$BR" --stage-device "$SRC/device/realme/ossi"

# The shared hardware config inherits a vendor makefile. The ossi product
# already inherits its own generated vendor tree through device.mk.
COMMON_VENDOR="$SRC/vendor/oneplus/sm8550-common/sm8550-common-vendor.mk"
BRIDGE='# ossi: hardware common tree uses the verified Realme proprietary tree.'
if [ ! -e "$COMMON_VENDOR" ]; then
  mkdir -p "$(dirname "$COMMON_VENDOR")"
  printf '%s\n' "$BRIDGE" > "$COMMON_VENDOR"
else
  [ "$(cat "$COMMON_VENDOR")" = "$BRIDGE" ] ||
    fail "foreign sm8550-common vendor configuration at $COMMON_VENDOR"
fi
cp "$BLOB_LIST" "$SRC/device/realme/ossi/proprietary-files.txt"
TOOLS="$SRC/tools/extract-utils"
if [ ! -f "$TOOLS/extract_utils/main.py" ]; then
  TOOLS="$SRC/.ossi/extract-utils"
  REV=3f351b85d09ac0160ee42130dff6b0c695333b86
  if [ ! -d "$TOOLS/.git" ]; then
    git init -q "$TOOLS"
  fi
  if ! git -C "$TOOLS" cat-file -e "$REV^{commit}" 2>/dev/null; then
    git -C "$TOOLS" fetch --depth=1 https://github.com/LineageOS/android_tools_extract-utils.git "$REV"
  fi
  git -C "$TOOLS" checkout --quiet --detach "$REV"
fi
if [ -d "$SRC/vendor/realme/ossi" ]; then
  if [ -f "$SRC/vendor/realme/ossi/.ossi-generated" ]; then
    previous="$WORK/vendor-previous"
  else
    previous=$(mktemp -d -p "$SRC/.ossi" vendor-previous.XXXXXXXX)
    rmdir "$previous"
  fi
  mv -T -- "$SRC/vendor/realme/ossi" "$previous"
  VENDOR_BACKUP=$previous
fi
VENDOR_GENERATING=1
(
  cd "$SRC/device/realme/ossi"
  # Regenerate the pins from the verified GT5 dump so donor-device SHA1
  # entries cannot cause extract-utils to skip an ossi fixup.
  OSSI_PLATFORM_SDK="$SDK" PYTHONPATH="$TOOLS" python3 extract-files.py --kang "$BLOBS"
)
python3 "$HERE/rom-check-inputs.py" vendor --vendor "$SRC/vendor/realme/ossi" --blob-list "$BLOB_LIST"
touch "$SRC/vendor/realme/ossi/.ossi-generated"
VENDOR_READY=1

(
  cd "$SRC"
  repo manifest -r -o "$WORK/source-manifest.xml"
  export OUT_DIR="$SRC/out/ossi/$BR"
  export DIST_DIR="$WORK/dist"
  export OSSI_AVB_KEY="${AVB_KEY:-$SRC/external/avb/test/data/testkey_rsa4096.pem}"
  [ -s "$OSSI_AVB_KEY" ] || fail "AVB signing key missing"
  set +u
  source build/envsetup.sh
  lunch "$WANT_LUNCH"
  [ "$(get_build_var TARGET_DEVICE)" = ossi ] || fail "source product must build for ossi"
  [ "$(get_build_var PLATFORM_SDK_VERSION)" = "$SDK" ] || fail "source platform SDK differs from $SDK"
  PLATFORM_SPL="$(get_build_var PLATFORM_SECURITY_PATCH)"
  OTA_CERT="$(get_build_var DEFAULT_SYSTEM_DEV_CERTIFICATE).x509.pem"
  DELTA_GENERATOR="$(get_abs_build_var HOST_OUT_EXECUTABLES)/delta_generator"
  OTA_NAME=$PRODUCT
  if [ "$(get_build_var TARGET_BUILD_TYPE)" = debug ]; then OTA_NAME="${OTA_NAME}_debug"; fi
  OTA_ZIP="$(get_abs_build_var PRODUCT_OUT)/$OTA_NAME-ota.zip"
  mka -j"$JOBS" target-files-package otapackage check-vintf-all dist
  set -u
  python3 "$HERE/rom-verify-delivery.py" --dist "$DIST_DIR" --ota "$OTA_ZIP" \
    --prebuilt "$SRC/device/realme/ossi/prebuilt" --stock "$STOCK" --avb-key "$OSSI_AVB_KEY" \
    --ota-cert "$OTA_CERT" --delta-generator "$DELTA_GENERATOR" --platform-security-patch "$PLATFORM_SPL" \
    --output "$OUT" --source-manifest "$WORK/source-manifest.xml"
)
