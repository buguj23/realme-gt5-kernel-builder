#!/usr/bin/env bash
# integrate-yukisu.sh — professional YukiSU LKM integration for Action-Build OGKI 5.15.
#
# YukiSU contract (Rouyashiki/YukiSU):
#   * CONFIG_KSU=m only (depends on m; builtin =y is rejected)
#   * TSR hook needs CONFIG_KPROBES=y CONFIG_KRETPROBES=y CONFIG_HAVE_SYSCALL_TRACEPOINTS=y
#   * Kasumi is in-tree with the LKM; do NOT apply SukiSU/SUSFS (they rewrite task_struct)
#   * This is NOT Google GKI. COMMON is the OEM OGKI common tree from Action-Build.
set -euo pipefail

COMMON=${1:-${KP_DIR:-$HOME/gt5_kernel_ab/kernel_platform}/common}
REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
WORK=${WORK:-${TMPDIR:-/tmp}/yukisu_src}
YUKI_REPO=${YUKI_REPO:-https://github.com/Rouyashiki/YukiSU.git}
YUKI_REF=${YUKI_REF:-main}

[ -d "$COMMON" ] || { echo "common tree not found: $COMMON" >&2; exit 1; }

mkdir -p "$WORK"
if [ ! -d "$WORK/YukiSU/.git" ]; then
  git clone --depth 1 --branch "$YUKI_REF" "$YUKI_REPO" "$WORK/YukiSU"
else
  git -C "$WORK/YukiSU" fetch --depth 1 origin "$YUKI_REF"
  git -C "$WORK/YukiSU" checkout -q FETCH_HEAD
fi

DST=$COMMON/drivers/kernelsu
rm -rf "$DST"
mkdir -p "$DST"
cp -a "$WORK/YukiSU/kernel/." "$DST/"

# Upstream kasumi calls cancel_work(), which only exists in some OEM forks:
#   oneplus/sm8550_u_14.0.0_oneplus11 (5.15.123)  -> ABSENT  => link fails
#   oneplus/sm8550_v_15.0.0_ace_2_pro (149/167)   -> present
#   oneplus/sm8550_b_16.0.0_ace_2_pro (180)       -> present
# Only rewrite where the symbol is missing. cancel_work() does not wait for a
# running callback while cancel_work_sync() does, and both kasumi call sites use
# the non-blocking form to poll ("return false, retry later"), so rewriting on a
# tree that has the real symbol would silently turn two quiesce paths blocking.
if grep -qE '\bbool[[:space:]]+cancel_work[[:space:]]*\(' \
      "$COMMON/include/linux/workqueue.h" 2>/dev/null \
   && grep -rqE 'EXPORT_SYMBOL(_GPL)?\([[:space:]]*cancel_work[[:space:]]*\)' \
      "$COMMON/kernel/workqueue.c" 2>/dev/null; then
  echo "cancel_work() is declared and exported here; leaving YukiSU call sites as-is"
else
  echo "cancel_work() missing in this tree; rewriting YukiSU call sites to cancel_work_sync()"
  while IFS= read -r -d '' f; do
    sed -i -E 's/\bcancel_work\(/cancel_work_sync(/g' "$f"
  done < <(grep -rlZ --include='*.c' 'cancel_work(' "$DST" || true)
  if grep -rqE '\bcancel_work\(' --include='*.c' "$DST"; then
    echo "YukiSU sources still call non-existent cancel_work()" >&2
    exit 1
  fi
fi

rm -rf "$DST/include/uapi"
mkdir -p "$DST/include"
cp -a "$WORK/YukiSU/uapi" "$DST/include/uapi"

# Upstream keeps uapi/ at repo root, so kernel/feature/yukizygisk/patch_transaction.h
# reaches it as ../../../uapi/. We relocate uapi/ to include/uapi (which Kbuild puts
# on -I, hence every other file in the tree says "uapi/<h>"). That one header kept
# the repo-root form and resolves to drivers/uapi (absent) -> clang: file not found.
PT=$DST/feature/yukizygisk/patch_transaction.h
if [ -f "$PT" ]; then
  sed -i 's|#include "\.\./\.\./\.\./uapi/|#include "uapi/|' "$PT"
  grep -q '#include "uapi/yukizygisk.h"' "$PT" \
    || { echo "patch_transaction.h: uapi include not normalized" >&2; exit 1; }
fi
if grep -rq '"\.\./\.\./\.\./uapi/' "$DST"; then
  echo "YukiSU sources still reach uapi via repo-root relative path:" >&2
  grep -rn '"\.\./\.\./\.\./uapi/' "$DST" >&2
  exit 1
fi

# No network during kernel make (Kbuild otherwise curls GitHub for version).
sed -i 's|^KSU_GITHUB_VERSION := \$(shell.*|KSU_GITHUB_VERSION :=|' "$DST/Kbuild"
sed -i 's|^  KSU_GITHUB_VERSION_COMMIT := \$(shell.*|  KSU_GITHUB_VERSION_COMMIT :=|' "$DST/Kbuild"

printf 'include $(src)/Kbuild\n' > "$DST/Makefile"

# YukiZygisk is compiled via CONFIG_KSU_YUKIZYGISK but has no Kconfig entry upstream.
if ! grep -q 'config KSU_YUKIZYGISK' "$DST/Kconfig"; then
  cat >> "$DST/Kconfig" <<'EOF'

config KSU_YUKIZYGISK
	bool "YukiZygisk (kernel Zygisk)"
	depends on KSU
	default y
	help
	  Built-in YukiZygisk, compatible with Zygisk Next modules.
EOF
fi

grep -q 'kernelsu/' "$COMMON/drivers/Makefile" \
  || printf '\n# YukiSU LKM (CONFIG_KSU=m)\nobj-$(CONFIG_KSU) += kernelsu/\n' >> "$COMMON/drivers/Makefile"

if ! grep -q 'drivers/kernelsu/Kconfig' "$COMMON/drivers/Kconfig"; then
  if grep -q '^endmenu' "$COMMON/drivers/Kconfig"; then
    sed -i '/^endmenu/i source "drivers/kernelsu/Kconfig"' "$COMMON/drivers/Kconfig"
  else
    echo 'source "drivers/kernelsu/Kconfig"' >> "$COMMON/drivers/Kconfig"
  fi
fi

# Symbol exports live in scripts/ksu-exports.sh and run after the patch series.
# Config comes from upstream's "Add Configuration Settings" step, which sets the
# KSU, kprobe, module and feature symbols (a superset of what was in
# configs/features.config). Keeping a second overlay here would silently diverge
# from the upstream build.

if [ -f "$COMMON/build.config.gki" ]; then
  sed -i 's/check_defconfig//' "$COMMON/build.config.gki" || true
fi

echo "YukiSU LKM integrated into $DST (CONFIG_KSU=m, Kasumi+YukiZygisk, OEM OGKI defconfig)"
