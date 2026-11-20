#!/usr/bin/env bash
# Bootstrap a fresh domestic China preemptible VM (or Ubuntu host) as a GT5 builder / GitHub Actions runner.
set -euo pipefail

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
source "$REPO_DIR/scripts/lib-mirror.sh"

WITH_ROM_DEPS=0
FORCE_APT_MIRROR=0
SKIP_APT=0
DRY_RUN=0
CCACHE_SIZE=${CCACHE_SIZE:-20G}
INSTALL_REPO_BIN=${INSTALL_REPO_BIN:-/usr/local/bin/repo}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --with-rom-deps) WITH_ROM_DEPS=1 ;;
    --force-apt-mirror) FORCE_APT_MIRROR=1 ;;
    --skip-apt) SKIP_APT=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --ccache-size) CCACHE_SIZE="$2"; shift ;;
    --repo-bin) INSTALL_REPO_BIN="$2"; shift ;;
    -h|--help)
      cat <<'EOF'
Usage: setup-cn-runner.sh [options]
  --with-rom-deps      Also install AOSP/Infinity-X ROM build & image verification packages
  --force-apt-mirror   Rewrite APT mirror even if already pointing to a mirror
  --skip-apt           Skip APT mirror switch and package installation
  --dry-run            Probe fastest mirrors and print planned actions without modifying system
  --ccache-size SIZE   Configure ccache max size (default: 20G)
  --repo-bin PATH      Destination for git-repo launcher (default: /usr/local/bin/repo)
EOF
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    echo "sudo is required when running as non-root" >&2
    exit 1
  fi
fi

echo "=== Host Summary ==="
uname -a
nproc
free -h || true
df -h /

if [ "$DRY_RUN" = 1 ]; then
  echo "Mode: $(resolve_mirror_mode)"
  echo "Fastest APT mirror: $(python3 "$MIRROR_HELPER" probe-apt)"
  echo "Fastest REPO_URL: $(python3 "$MIRROR_HELPER" probe-repo-url --mode cn)"
  echo "Fastest AOSP mirror: $(python3 "$MIRROR_HELPER" probe-aosp)"
  echo "Fastest LineageOS mirror: $(python3 "$MIRROR_HELPER" probe-lineage)"
  echo "GitHub mirror ranking for DestoryG/kernel_manifest:"
  python3 "$MIRROR_HELPER" probe-github --url "https://github.com/DestoryG/kernel_manifest.git" --mode cn
  python3 "$MIRROR_HELPER" configure-apt --dry-run ${FORCE_APT_MIRROR:+--force}
  exit 0
fi

if [ "$SKIP_APT" != 1 ]; then
  if [ "$(resolve_mirror_mode)" = "cn" ]; then
    $SUDO python3 "$MIRROR_HELPER" configure-apt ${FORCE_APT_MIRROR:+--force}
  fi

  PKGS=(
    aria2 ca-certificates ccache cpio curl wget git git-lfs gh gnupg lzip
    bc bison flex build-essential libelf-dev libssl-dev dwarves zstd lz4 xz-utils
    clang lld llvm python3 python-is-python3 python3-yaml rsync unzip zip
    erofs-utils e2fsprogs android-sdk-libsparse-utils mkbootimg
  )
  if [ "$WITH_ROM_DEPS" = 1 ]; then
    PKGS+=(
      openjdk-17-jdk xsltproc libxml2-utils dosfstools mtools squashfs-tools
      libncurses-dev zlib1g-dev fontconfig jq patchelf
    )
  fi

  $SUDO apt-get update
  $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${PKGS[@]}"
fi

if ! command -v avbtool >/dev/null 2>&1; then
  tmp_avb=$(mktemp)
  python3 "$MIRROR_HELPER" download --output "$tmp_avb" --expect-token "#!/usr/bin/env python" \
    "https://raw.githubusercontent.com/LineageOS/android_external_avb/lineage-22.2/avbtool.py"
  $SUDO install -m 0755 "$tmp_avb" /usr/local/bin/avbtool
  rm -f "$tmp_avb"
fi

if command -v ccache >/dev/null 2>&1; then
  ccache -M "$CCACHE_SIZE" >/dev/null 2>&1 || true
fi

if [ -w "$(dirname "$INSTALL_REPO_BIN")" ] || [ -n "$SUDO" ]; then
  tmp_repo=$(mktemp)
  python3 "$MIRROR_HELPER" ensure-repo --output "$tmp_repo" --mode "${MIRROR_MODE:-auto}" >/dev/null
  $SUDO install -m 0755 "$tmp_repo" "$INSTALL_REPO_BIN"
  rm -f "$tmp_repo"
fi

echo "=== Resilience Check ==="
ensure_repo_url >/dev/null
echo "REPO_URL=$REPO_URL"
echo "Setup complete."
cat <<'EOF'

Tips for preemptible cloud instances (抢占实例) registered as GitHub Actions self-hosted runners:
1. Prefer a persistent data disk (or cloud disk mount) for runner `_work` and `CCACHE_DIR` so preemption resumes incrementally.
2. Export MIRROR_MODE=cn in the runner `.env` file alongside your runner labels (e.g. self-hosted,linux,x64,cn,gt5-rom).
3. Fetch verified RMX3820_15.0.0.320 stock assets once via:
     scripts/fetch-stock.sh --mode kernel   # 97 MiB for KMI CRC checks
     scripts/fetch-stock.sh --mode full     # full partition set for ROM builds
EOF
