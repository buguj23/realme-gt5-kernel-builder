#!/usr/bin/env bash
# 00-fetch.sh — Sync Realme GT5 (5.15.149) OEM OGKI tree from DestoryG/kernel_manifest (realme_gt5_v).
# Always fetches OEM OGKI (oplus_build_kernel.sh kalama gki), never Google generic GKI.
set -euo pipefail

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=scripts/lib-kernel.sh
source "$REPO_DIR/scripts/lib-kernel.sh"
enable_local_proxy_if_up

FILE=${FILE:-realme_gt5_v}
DYNAMIC_REPO=${DYNAMIC_REPO:-DestoryG}
MANIFEST_BRANCH=${MANIFEST_BRANCH:-realme/sm8550}
WORK=${WORK:-$HOME/gt5_kernel_5_15_149}

XML_SRC="$REPO_DIR/manifests/realme-sm8550/${FILE}.xml"
[ -f "$XML_SRC" ] || { echo "unknown FILE=$FILE (expected realme_gt5_v in manifests/realme-sm8550/)" >&2; exit 1; }

mkdir -p "$WORK/.repo/manifests_fallback"
cp "$XML_SRC" "$WORK/.repo/manifests_fallback/${FILE}.xml"
cp "$REPO_DIR/manifests/realme-sm8550/README.md" "$WORK/.repo/manifests_fallback/README.md"

ensure_repo_bin >/dev/null
ensure_repo_url >/dev/null

cd "$WORK"
repo_clean_locks "$WORK"
if [ -d "$WORK/.repo/projects" ]; then
  # Ensure interrupted preemptible runs or prior patch sets start from clean upstream state without discarding git objects.
  repo forall -j"$(mirror_net_jobs)" -c 'git reset --hard -q && git clean -fdxq' 2>/dev/null || true
fi

CANONICAL_MANIFEST="https://github.com/${DYNAMIC_REPO}/kernel_manifest.git"
mapfile -t MANIFEST_CANDIDATES < <(PYTHONPATH="$REPO_DIR/scripts" python3 "$REPO_DIR/scripts/mirror_helper.py" probe-github --url "$CANONICAL_MANIFEST" --mode "${MIRROR_MODE:-auto}")
[ "${#MANIFEST_CANDIDATES[@]}" -gt 0 ] || MANIFEST_CANDIDATES=("$CANONICAL_MANIFEST")

INIT_OK=0
for url in "${MANIFEST_CANDIDATES[@]}"; do
  git_resilient_args "$url"
  if GIT_TERMINAL_PROMPT=0 git "${GIT_RESILIENT_ARGS[@]}" ls-remote --heads "$url" "$MANIFEST_BRANCH" 2>/dev/null | grep -q "$MANIFEST_BRANCH"; then
    if GIT_TERMINAL_PROMPT=0 repo init -u "$url" -b "$MANIFEST_BRANCH" -m "${FILE}.xml" --depth=1 --no-clone-bundle --no-tags; then
      INIT_OK=1
      break
    fi
  fi
done

if [ "$INIT_OK" != 1 ]; then
  echo "Using vendored manifest $XML_SRC"
  mkdir -p .repo/local_manifests .repo/manifests
  for url in "${MANIFEST_CANDIDATES[@]}"; do
    GIT_TERMINAL_PROMPT=0 repo init -u "$url" -b "$MANIFEST_BRANCH" -m "${FILE}.xml" --depth=1 --no-clone-bundle --no-tags 2>/dev/null && break || true
  done
  cp "$XML_SRC" ".repo/manifests/${FILE}.xml"
  ln -sfn "manifests/${FILE}.xml" .repo/manifest.xml
fi

repo_sync_resilient "$WORK" "$(mirror_net_jobs)"

# Remove GKI protected export blockers if present, keeping OEM OGKI symbols intact.
for dir in kernel_platform/common kernel_platform/msm-kernel; do
  [ -e "$dir/BUILD.bazel" ] || continue
  sed -i '/^[[:space:]]*"protected_exports_list"[[:space:]]*:[[:space:]]*"android\/abi_gki_protected_exports_aarch64",$/d' "$dir/BUILD.bazel" || true
  rm -f "$dir/android/abi_gki_protected_exports_"* 2>/dev/null || true
done
if [ -f kernel_platform/common/build.config.gki ]; then
  sed -i 's/check_defconfig//' kernel_platform/common/build.config.gki || true
fi

SUBLEVEL=$(awk '/^SUBLEVEL =/ {print $3}' kernel_platform/common/Makefile)
echo "OGKI 5.15.${SUBLEVEL} tree ready under $WORK/kernel_platform (manifest=${DYNAMIC_REPO}:${MANIFEST_BRANCH}/${FILE}.xml)"
