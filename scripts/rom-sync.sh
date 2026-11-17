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
# Re-running resumes: repo sync is incremental and --force-sync only resets
# refs it already tracks.
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
export REPO_URL=${REPO_URL:-https://mirrors.tuna.tsinghua.edu.cn/git/git-repo}

mkdir -p "$DIR"
cd "$DIR"

if [ ! -d .repo ]; then
  echo "[1/3] repo init $MANIFEST ($BRANCH)"
  repo init -u "$MANIFEST" -b "$BRANCH" --depth=1 --no-clone-bundle
fi

echo "[2/3] point remotes at domestic mirrors"
LIB_ARGS=()
[ -n "$GITHUB_PROXY" ] && LIB_ARGS+=(--github-proxy "$GITHUB_PROXY")
python3 "$HERE/rom-manifest-mirror.py" "$DIR" "${LIB_ARGS[@]}"

echo "[3/3] repo sync -j$JOBS"
repo sync -j"$JOBS" --force-sync --no-clone-bundle --no-tags

echo "sync done: $(du -sh "$DIR" | cut -f1) in $DIR"
