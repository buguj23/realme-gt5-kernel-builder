#!/usr/bin/env bash
# Build one Realme GT5 ROM baseline. Also used by the self-hosted CI job.
set -euo pipefail

# GitHub Actions Runner.Worker sets SIGPIPE to SIG_IGN; non-interactive bash cannot undo an inherited SIG_IGN with trap.
if [ "${OSSI_SIGPIPE_RESET:-0}" != 1 ] && command -v python3 >/dev/null 2>&1; then
  export OSSI_SIGPIPE_RESET=1
  exec python3 -c 'import os, signal, sys; signal.signal(signal.SIGPIPE, signal.SIG_DFL); os.execvp("bash", ["bash", sys.argv[1], *sys.argv[2:]])' "$0" "$@"
fi

usage() {
  cat <<'EOF'
rom-build-local.sh --src DIR --branch 5.15.149 --pkg DIR --stock-images DIR
  [--sync] [--pool DIR] [--blobs DIR --blob-list FILE] [--output DIR]
  [--payload-metadata FILE] [--stock-layout FILE] [--stock-slot a|b] [--jobs N] [--min-free-gb N]
  [--oem-key FILE] [--avb-key FILE] [--check-only]
EOF
}

HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=scripts/lib-mirror.sh
source "$HERE/lib-mirror.sh"
REPO_ROOT=$(cd "$HERE/.." && pwd)
SRC=""; BR=""; PKG=""; STOCK=""; OEM_KEY=""; AVB_KEY=""
BLOBS=""; BLOB_LIST=""; POOL=""; OUT=""; METADATA=""; LAYOUT=""; STOCK_SLOT=""
LUNCH=""; DEPS_INPUT=""; SYNC=0; CHECK=0; AUTO_FETCH_STOCK=0; JOBS=$(nproc); MIN_FREE=120
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
    --auto-fetch-stock) AUTO_FETCH_STOCK=1; shift ;;
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
if [ "$AUTO_FETCH_STOCK" = 1 ] && [ ! -f "$STOCK/payload_metadata.bin" ]; then
  bash "$HERE/fetch-stock.sh" --mode full --dest "$STOCK"
fi
STOCK=$(realpath -e -- "$STOCK")
if [ -n "$OEM_KEY" ]; then OEM_KEY=$(realpath -e -- "$OEM_KEY"); fi
if [ -z "$METADATA" ] && [ ! -f "$STOCK/payload_metadata.bin" ] && [ -f "$REPO_ROOT/official/stock/15.0.0.320/payload_metadata.bin" ]; then
  METADATA="$REPO_ROOT/official/stock/15.0.0.320/payload_metadata.bin"
fi
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

WORK=$(mktemp -d -p "$(dirname "$SRC")" ".ossi-work.$(basename "$SRC").XXXXXXXX" 2>/dev/null || mktemp -d -p "${TMPDIR:-/tmp}" ossi-build.XXXXXXXX)
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
rm -f \
  "$SRC/hardware/qcom/sm7250/Android.bp" "$SRC/hardware/qcom/sm7250/Android.mk" \
  "$SRC/hardware/qcom/sm8150/Android.bp" "$SRC/hardware/qcom/sm8150/Android.mk"
bash "$HERE/rom-provision-deps.sh" "$SRC" --branch "$DEPS_BR"
python3 "$HERE/rom-patch-source.py" "$SRC"
if [ -z "$BLOBS" ]; then
  BLOBS="$WORK/blobs"
  selected="$WORK/proprietary-files.txt"
  blob_args=()
  if [ -n "${BLOB_LIST:-}" ]; then
    blob_args+=(--base-list "$BLOB_LIST")
  else
    blob_args+=(--base-list "$SRC/device/oneplus/sm8550-common/proprietary-files.txt")
    [ -f "$REPO_ROOT/rom/device/realme/ossi/proprietary-files.txt" ] &&
      blob_args+=(--extra-list "$REPO_ROOT/rom/device/realme/ossi/proprietary-files.txt")
  fi
  python3 "$HERE/rom-select-blobs.py" --mount "$WORK/blobmnt" --images "$STOCK" --label "$BR" \
    "${blob_args[@]}" \
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
    fetched_tools=0
    if [ "$(resolve_mirror_mode)" = "cn" ]; then
      for lin_url in \
        "https://mirrors.bfsu.edu.cn/git/lineageOS/LineageOS/android_tools_extract-utils.git" \
        "https://mirrors.tuna.tsinghua.edu.cn/git/lineageOS/LineageOS/android_tools_extract-utils.git"; do
        git_resilient_args "$lin_url"
        if GIT_TERMINAL_PROMPT=0 git -C "$TOOLS" "${GIT_RESILIENT_ARGS[@]}" fetch --depth=1 "$lin_url" "$REV" 2>/dev/null; then
          fetched_tools=1
          break
        fi
      done
    fi
    if [ "$fetched_tools" != 1 ]; then
      git_fetch_resilient "$TOOLS" "https://github.com/LineageOS/android_tools_extract-utils.git" "$REV" --depth=1
    fi
  fi
  git -C "$TOOLS" checkout --quiet --detach "$REV"
fi
if [ -d "$SRC/vendor/realme/ossi" ]; then
  if [ -f "$SRC/vendor/realme/ossi/.ossi-generated" ]; then
    previous="$WORK/vendor-previous"
  else
    previous=$(mktemp -d -p "$WORK" vendor-previous.XXXXXXXX)
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
if [ -n "$VENDOR_BACKUP" ] && [ -f "$VENDOR_BACKUP/.ossi-generated" ]; then
  rm -rf -- "$VENDOR_BACKUP"
  VENDOR_BACKUP=""
fi

(
  cd "$SRC"
  repo manifest -r -o "$WORK/source-manifest.xml"
  export OUT_DIR="out/ossi/$BR"
  export DIST_DIR="$OUT_DIR/dist"
  rm -rf -- "$DIST_DIR"
  export OSSI_AVB_KEY="${AVB_KEY:-external/avb/test/data/testkey_rsa4096.pem}"
  [[ "$OSSI_AVB_KEY" == "$SRC/"* ]] && export OSSI_AVB_KEY="${OSSI_AVB_KEY#"$SRC/"}"
  [ -s "$OSSI_AVB_KEY" ] || fail "AVB signing key missing"
  set +euo pipefail
  if [ "${USE_CCACHE:-0}" != 1 ]; then
    export CCACHE_EXEC="${CCACHE_EXEC:-disabled}" USE_CCACHE=0
  fi
  source build/envsetup.sh
  if [ "${USE_CCACHE:-0}" != 1 ]; then
    unset CCACHE_EXEC || true
    export USE_CCACHE=0
  fi
  lunch "$WANT_LUNCH" || fail "lunch $WANT_LUNCH failed"
  # Force binary.mk / Soong cc to map legacy KERNEL_OBJ/usr & qti_kernel_headers
  # onto generated_kernel_headers while TARGET_FORCE_PREBUILT_KERNEL keeps our OGKI Image.
  export INLINE_KERNEL_BUILDING=true
  set -e
  [ "$(get_build_var TARGET_DEVICE)" = ossi ] || fail "source product must build for ossi"
  [ "$(get_build_var PLATFORM_SDK_VERSION)" = "$SDK" ] || fail "source platform SDK differs from $SDK"
  PLATFORM_SPL="$(get_build_var PLATFORM_SECURITY_PATCH)"
  OTA_CERT="$(get_build_var DEFAULT_SYSTEM_DEV_CERTIFICATE).x509.pem"
  DELTA_GENERATOR="$(get_abs_build_var HOST_OUT_EXECUTABLES)/delta_generator"
  OTA_NAME=$PRODUCT
  if [ "$(get_build_var TARGET_BUILD_TYPE)" = debug ]; then OTA_NAME="${OTA_NAME}_debug"; fi
  OTA_ZIP="$(get_abs_build_var PRODUCT_OUT)/$OTA_NAME-ota.zip"
  set +eo pipefail
  mka -j"$JOBS" target-files-package otapackage check-vintf-all dist || fail "mka build failed"
  set -euo pipefail
  python3 "$HERE/rom-verify-delivery.py" --dist "$DIST_DIR" --ota "$OTA_ZIP" \
    --prebuilt "$SRC/device/realme/ossi/prebuilt" --stock "$STOCK" --avb-key "$OSSI_AVB_KEY" \
    --ota-cert "$OTA_CERT" --delta-generator "$DELTA_GENERATOR" --platform-security-patch "$PLATFORM_SPL" \
    --output "$OUT" --source-manifest "$WORK/source-manifest.xml"
)
