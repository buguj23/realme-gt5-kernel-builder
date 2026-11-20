#!/usr/bin/env bash
# rom-sync.sh — init + mirror + sync a ROM source tree, tuned for this region.
#
# Measured (2026-11-17): direct GitHub 18-25 KB/s, android.googlesource.com
# unreachable, TUNA 60 MB/s. A full Infinity-X 16 tree is >110 GB, so the mirror
# path is what makes a sync take ~1 h instead of days.
#
# usage:
#   rom-sync.sh --dir ~/rom16 --manifest https://github.com/ProjectInfinity-X/manifest \
#               --branch 16 [--jobs 16] [--github-proxy https://gh-proxy.com/]
#
# Re-running resumes the sync after validating the existing manifest identity.
set -euo pipefail

DIR=""
MANIFEST="https://github.com/ProjectInfinity-X/manifest"
BRANCH=""
JOBS=$(nproc)
GITHUB_PROXY=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR=${2:?}; shift 2 ;;
    --manifest) MANIFEST=${2:?}; shift 2 ;;
    --branch) BRANCH=${2:?}; shift 2 ;;
    --jobs) JOBS=${2:?}; shift 2 ;;
    --github-proxy) GITHUB_PROXY=${2:?}; shift 2 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ -n "$DIR" ] && [ -n "$BRANCH" ] || { echo "--dir and --branch are required" >&2; exit 2; }

HERE=$(cd "$(dirname "$0")" && pwd)
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-mirror.sh"
ensure_repo_bin >/dev/null
export REPO_URL=${REPO_URL:-$(ensure_repo_url)}

mkdir -p "$DIR"
cd "$DIR"
DIR=$PWD
repo_clean_locks "$DIR"

if [ ! -d .repo ]; then
  echo "[1/3] repo init $MANIFEST ($BRANCH)"
  mapfile -t MANIFEST_CANDIDATES < <(PYTHONPATH="$HERE" python3 "$HERE/mirror_helper.py" probe-github --url "$MANIFEST" --mode "${MIRROR_MODE:-auto}")
  [ "${#MANIFEST_CANDIDATES[@]}" -gt 0 ] || MANIFEST_CANDIDATES=("$MANIFEST")
  INIT_OK=0
  for m_url in "${MANIFEST_CANDIDATES[@]}"; do
    if GIT_TERMINAL_PROMPT=0 repo init -u "$m_url" -b "$BRANCH" --depth=1 --no-clone-bundle --no-tags; then
      INIT_OK=1
      break
    fi
    rm -rf .repo
  done
  [ "$INIT_OK" = 1 ] || { echo "repo init failed for $MANIFEST ($BRANCH)" >&2; exit 1; }
fi
python3 "$HERE/rom-check-inputs.py" source --src "$DIR" --manifest "$MANIFEST" --source-branch "$BRANCH"

echo "[2/3] point remotes at domestic mirrors"
LFS_SEED_URL=""
if [ "$(resolve_mirror_mode)" = "cn" ] && grep -qs 'gitea.com/projectInfinity-x' "$DIR/.repo/manifests/snippets/infinity.xml" 2>/dev/null; then
  SEED_TAG="${INFINITY_SEED_TAG:-infinity-${BRANCH}-gitea-seed}"
  SEED_REPO="${INFINITY_SEED_REPO:-buguj23/realme-gt5-kernel-builder}"
  SEED_DIR="${INFINITY_SEED_DIR:-$HOME/.cache/gt5-rom-seed/$BRANCH}"
  if [ ! -f "$SEED_DIR/.ready" ]; then
    SEED_DL=$(mktemp -d "${TMPDIR:-/tmp}/gitea-seed.XXXXXXXX")
    BASE_SEED="https://github.com/${SEED_REPO}/releases/download/${SEED_TAG}"
    if download_multi_mirror "$SEED_DL/SHA256SUMS.txt" "" "${BASE_SEED}/SHA256SUMS.txt" 2>/dev/null; then
      echo "Fetching verified Gitea/LFS seed bundle ($SEED_TAG) via multi-mirror aria2c..."
      SEED_PARTS=$(awk '$2 ~ /\.tar\.zst/ {print $2}' "$SEED_DL/SHA256SUMS.txt" | sort)
      [ -n "$SEED_PARTS" ] || { echo "WARN: SHA256SUMS.txt in $SEED_TAG has no .tar.zst parts; skipping seed" >&2; }
      SEED_OK=1
      for part in $SEED_PARTS; do
        part_sha=$(awk -v f="$part" '$2 == f || $2 == ("*" f) {print $1; exit}' "$SEED_DL/SHA256SUMS.txt")
        if ! download_multi_mirror "$SEED_DL/$part" "$part_sha" "${BASE_SEED}/${part}"; then
          SEED_OK=0
          break
        fi
      done
      if [ "$SEED_OK" = 1 ] && [ -n "$SEED_PARTS" ]; then
        rm -rf "${SEED_DIR}.tmp"
        mkdir -p "${SEED_DIR}.tmp"
        if (for part in $SEED_PARTS; do cat "$SEED_DL/$part"; done) | zstd -dc | tar -xf - -C "${SEED_DIR}.tmp"; then
          rm -rf "$SEED_DIR"
          mv "${SEED_DIR}.tmp" "$SEED_DIR"
          touch "$SEED_DIR/.ready"
        else
          rm -rf "${SEED_DIR}.tmp"
        fi
      fi
    fi
    rm -rf "$SEED_DL"
  fi
  if [ -f "$SEED_DIR/.ready" ]; then
    LFS_SEED_URL="file://${SEED_DIR}"
    echo "Using verified local Gitea/LFS seed: $LFS_SEED_URL"
  fi
fi

LIB_ARGS=(--aosp auto --lineage auto)
if [ -n "$GITHUB_PROXY" ]; then
  LIB_ARGS+=(--github-proxy "$GITHUB_PROXY")
elif [ "$(resolve_mirror_mode)" = "cn" ]; then
  LIB_ARGS+=(--github-proxy auto)
fi
if [ -n "$LFS_SEED_URL" ]; then
  LIB_ARGS+=(--lfs "$LFS_SEED_URL")
fi
python3 "$HERE/rom-manifest-mirror.py" "$DIR" "${LIB_ARGS[@]}"

echo "[3/3] repo sync -j$JOBS"
repo_sync_resilient "$DIR" "$JOBS"

echo "sync done: $(du -sh "$DIR" | cut -f1) in $DIR"
