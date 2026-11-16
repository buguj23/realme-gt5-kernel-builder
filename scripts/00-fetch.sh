#!/usr/bin/env bash
# 00-fetch.sh — sync Action-Build OEM OGKI (OnePlus/OPPO SM8550 5.15 analogue).
# Never downloads Google generic GKI. The oplus script argument "gki" is the
# OEM OGKI flavor: ./kernel_platform/oplus/build/oplus_build_kernel.sh kalama gki
set -euo pipefail

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
FILE=${FILE:-oneplus_ace2_pro_b}
WORK=${WORK:-$HOME/gt5_kernel_ab}
DYNAMIC_REPO=${DYNAMIC_REPO:-Numbersf}

mkdir -p "$WORK/.repo/manifests" "$WORK/.repo/manifests_fallback"

pick_xml() {
  local name=$1
  if [ -f "$REPO_DIR/manifests/oneplus-sm8550/${name}.xml" ]; then
    cp "$REPO_DIR/manifests/oneplus-sm8550/${name}.xml" "$WORK/.repo/manifests_fallback/${name}.xml"
    cp "$REPO_DIR/manifests/oneplus-sm8550/README.md" "$WORK/.repo/manifests_fallback/README.md"
    echo "local-oneplus"
    return 0
  fi
  if [ -f "$REPO_DIR/manifests/oppo-sm8550/${name}.xml" ]; then
    cp "$REPO_DIR/manifests/oppo-sm8550/${name}.xml" "$WORK/.repo/manifests_fallback/${name}.xml"
    cp "$REPO_DIR/manifests/oppo-sm8550/README.md" "$WORK/.repo/manifests_fallback/README.md" 2>/dev/null || true
    echo "local-oppo"
    return 0
  fi
  return 1
}

FOUND=""
if pick_xml "$FILE" >/tmp/gt5_xml_src; then
  FOUND=$(cat /tmp/gt5_xml_src)
else
  echo "unknown FILE=$FILE (need an SM8550 5.15 analogue: oneplus_ace2_pro_b / oneplus_11_v / ...)" >&2
  exit 1
fi

XML_PATH="$WORK/.repo/manifests_fallback/${FILE}.xml"
REVISION=$(grep -oP '<project[^>]+revision="\K[^"]+' "$XML_PATH" | head -n1)
CPU=$(echo "$REVISION" | sed -E 's#^(oneplus|realme|oppo)/([^_]+).*#\2#')
echo "FILE=$FILE analogue revision=$REVISION cpu=$CPU source=$FOUND"
echo "Action-Build has no 真我 SKU; this is the SM8550 OGKI stand-in for Realme GT5 (ossi/RMX3820)."

command -v repo >/dev/null || {
  echo "repo tool missing. Install: curl https://storage.googleapis.com/git-repo-downloads/repo > ~/bin/repo && chmod +x ~/bin/repo"
  echo "XML staged at $XML_PATH — CI uses the same file via Numbersf/kernel_manifest."
  exit 0
}

cd "$WORK"
cp "$XML_PATH" ".repo/manifests/${FILE}.xml"
if [[ "$FOUND" == local-oppo ]]; then
  repo init -u "https://github.com/Numbersf/Kernel_Manifest_Appendix.git" -b oppo/sm8550 -m "${FILE}.xml" --depth=1 --no-clone-bundle --no-tags
else
  repo init -u "https://github.com/${DYNAMIC_REPO}/kernel_manifest.git" -b oneplus/sm8550 -m "${FILE}.xml" --depth=1 --no-clone-bundle --no-tags
fi
repo sync -c -j"$(nproc)" --no-clone-bundle --no-tags --force-sync

# Strip GKI ABI fences so OEM OGKI + extra LKM (kernelsu.ko) can link.
for dir in kernel_platform/common kernel_platform/msm-kernel; do
  [ -e "$dir/BUILD.bazel" ] || continue
  sed -i '/^[[:space:]]*"protected_exports_list"[[:space:]]*:[[:space:]]*"android\/abi_gki_protected_exports_aarch64",$/d' "$dir/BUILD.bazel" || true
  rm -f "$dir/android/abi_gki_protected_exports_"* 2>/dev/null || true
done
if [ -f kernel_platform/common/build.config.gki ]; then
  sed -i 's/check_defconfig//' kernel_platform/common/build.config.gki || true
fi

echo "OGKI tree ready under $WORK/kernel_platform (oplus_build_kernel.sh kalama gki)"
