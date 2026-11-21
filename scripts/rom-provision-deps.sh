#!/usr/bin/env bash
# rom-provision-deps.sh — fetch the trees the GT5 device config needs but the
# Infinity-X/Lineage manifests do not carry.
#
#   device/oneplus/sm8550-common      platform HALs, init, vintf, overlays
#   hardware/oplus                    Oplus HALs + sepolicy/qti
#   hardware/pixelworks/interfaces    referenced by sm8550-common/common.mk
#
# usage: rom-provision-deps.sh <src-dir> [--branch lineage-22.2] [--mirror URL]
#   branch must match the manifest's Android version:
#     A16 -> lineage-23.2,  A15 -> lineage-22.2,  A14 -> lineage-21
# Existing trees must use the requested branch and the mirror or LineageOS origin;
# validation is local only and never switches branches or rewrites user trees.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=scripts/lib-mirror.sh
source "$HERE/lib-mirror.sh"

SRC=${1:?usage: rom-provision-deps.sh <src-dir> [--branch BR] [--mirror URL]}
shift || true
BRANCH=lineage-22.2
MIRROR_EXPLICIT=0
MIRROR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --branch) BRANCH=${2:?}; shift 2 ;;
    --mirror) MIRROR=${2:?}; MIRROR_EXPLICIT=1; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [ "$MIRROR_EXPLICIT" = 0 ]; then
  if [ "$(resolve_mirror_mode)" = "cn" ]; then
    MIRROR="$(PYTHONPATH="$HERE" python3 "$HERE/mirror_helper.py" probe-lineage | sed 's:/*$::')/LineageOS"
  else
    MIRROR="https://github.com/LineageOS"
  fi
fi

ensure() { # <path> <repo>
  local path=$1 repo=$2 top branch origin expected="${MIRROR%/}/$2"
  if [ -e "$SRC/$path" ] || [ -L "$SRC/$path" ]; then
    top=$(git -C "$SRC/$path" rev-parse --show-toplevel 2>/dev/null) \
      || { echo "  FAILED  $path is not a Git worktree" >&2; return 1; }
    if [ "$top" != "$(cd "$SRC/$path" && pwd -P)" ]; then
      echo "  FAILED  $path is not a Git worktree root" >&2
      return 1
    fi
    branch=$(git -C "$SRC/$path" symbolic-ref --quiet --short HEAD || true)
    if [ "$branch" != "$BRANCH" ] &&
       ! git -C "$SRC/$path" rev-parse --verify "refs/remotes/origin/$BRANCH" >/dev/null 2>&1; then
      echo "  FAILED  $path does not track $BRANCH" >&2
      return 1
    fi
    if [ "$branch" != "$BRANCH" ] &&
       [ "$(git -C "$SRC/$path" rev-parse HEAD)" != "$(git -C "$SRC/$path" rev-parse "refs/remotes/origin/$BRANCH")" ]; then
      echo "  FAILED  $path is not at the requested $BRANCH revision" >&2
      return 1
    fi
    origin=$(git -C "$SRC/$path" config --get remote.origin.url) \
      || { echo "  FAILED  $path has no origin URL" >&2; return 1; }
    origin=${origin%/}
    origin=${origin%.git}
    origin=$(PYTHONPATH="$HERE" python3 -c 'import sys, mirror_helper as m; print(m.strip_github_proxy(sys.argv[1]))' "$origin")
    case "$origin" in
      "$expected"|"https://mirrors.tuna.tsinghua.edu.cn/git/lineageOS/LineageOS/$repo"|"https://mirrors.bfsu.edu.cn/git/lineageOS/LineageOS/$repo"|"https://github.com/LineageOS/$repo"|"git@github.com:LineageOS/$repo"|"ssh://git@github.com/LineageOS/$repo") ;;
      *) echo "  FAILED  $path origin does not match the expected LineageOS repository or mirror ($origin)" >&2; return 1 ;;
    esac
    echo "  present $path"
    return 0
  fi
  mkdir -p "$(dirname "$SRC/$path")"
  echo "  clone   $path ($repo @ $BRANCH)"
  local cloned=0
  local -a clone_bases=()
  if [ "$MIRROR_EXPLICIT" = 1 ]; then
    clone_bases+=("$MIRROR")
  fi
  if [ "$(resolve_mirror_mode)" = "cn" ]; then
    [ "$MIRROR_EXPLICIT" = 1 ] || clone_bases+=("$MIRROR")
    clone_bases+=(
      "https://mirrors.tuna.tsinghua.edu.cn/git/lineageOS/LineageOS"
      "https://mirrors.bfsu.edu.cn/git/lineageOS/LineageOS"
    )
  fi
  for m_base in "${clone_bases[@]}"; do
    git_resilient_args "${m_base%/}/$repo.git"
    if GIT_TERMINAL_PROMPT=0 git "${GIT_RESILIENT_ARGS[@]}" clone --depth=1 -b "$BRANCH" -q "${m_base%/}/$repo.git" "$SRC/$path" 2>/dev/null; then
      cloned=1
      break
    fi
    rm -rf "$SRC/$path"
  done
  if [ "$cloned" != 1 ]; then
    git_clone_resilient "https://github.com/LineageOS/$repo.git" "$SRC/$path" --depth=1 -b "$BRANCH" -q \
      || { echo "  FAILED  $repo @ $BRANCH" >&2; return 1; }
  fi
}

case "$BRANCH" in
  lineage-21|lineage-22.2|lineage-23.2) ;;
  *) echo "unknown dependency branch" >&2; exit 2 ;;
esac
ensure device/oneplus/sm8550-common   android_device_oneplus_sm8550-common
ensure hardware/oplus                 android_hardware_oplus
ensure kernel/oneplus/sm8550          android_kernel_oneplus_sm8550
ensure kernel/oneplus/sm8550-modules  android_kernel_oneplus_sm8550-modules
if [ "$BRANCH" = lineage-23.2 ]; then
  ensure hardware/pixelworks/interfaces android_hardware_pixelworks_interfaces
fi
echo "deps ready in $SRC"
