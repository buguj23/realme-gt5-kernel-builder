#!/usr/bin/env bash
# integrate-yukisu.sh — Build Rouyashiki/YukiSU as an out-of-tree LKM (CONFIG_KSU=m)
# against a compiled Realme GT5 (5.15.149) OGKI KDIR (Module.symvers + .config + vmlinux).
set -euo pipefail

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=scripts/lib-kernel.sh
source "$REPO_DIR/scripts/lib-kernel.sh"
enable_local_proxy_if_up

KP_DIR=${KP_DIR:-$HOME/gt5_kernel_5_15_149/kernel_platform}
C=${COMMON_DIR:-$KP_DIR/common}
KDIR=""
YUKI_DIR=${YUKI_DIR:-${TMPDIR:-/tmp}/yukisu_src/YukiSU}
YUKI_REPO=${YUKI_REPO:-https://github.com/Rouyashiki/YukiSU.git}
YUKI_REF=${YUKI_REF:-main}
OUT_DIR=""
ENABLE_YUKIZYGISK=${ENABLE_YUKIZYGISK:-1}
KSU_SUPERKEY=${KSU_SUPERKEY:-}
KSU_MANAGER_PACKAGE=${KSU_MANAGER_PACKAGE:-}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kp-dir) KP_DIR=$2; C=$KP_DIR/common; shift 2 ;;
    --src|--common) C=$2; shift 2 ;;
    --kdir) KDIR=$2; shift 2 ;;
    --yukisu-dir) YUKI_DIR=$2; shift 2 ;;
    --yukisu-repo) YUKI_REPO=$2; shift 2 ;;
    --yukisu-ref) YUKI_REF=$2; shift 2 ;;
    --output) OUT_DIR=$2; shift 2 ;;
    --yukizygisk) ENABLE_YUKIZYGISK=$2; shift 2 ;;
    --superkey) KSU_SUPERKEY=$2; shift 2 ;;
    --manager-pkg) KSU_MANAGER_PACKAGE=$2; shift 2 ;;
    -*) echo "Unknown flag: $1" >&2; exit 2 ;;
    *)
      if [ -f "$1/.config" ] && [ -f "$1/Module.symvers" ]; then
        KDIR=$1
      elif [ -d "$1/arch/arm64" ]; then
        C=$1
      fi
      shift
      ;;
  esac
done

KDIR=${KDIR:-$C/out}
[ -f "$KDIR/.config" ] && [ -f "$KDIR/Module.symvers" ] && [ -f "$KDIR/vmlinux" ] || {
  echo "ERROR: KDIR=$KDIR must contain built .config, Module.symvers, and vmlinux." >&2
  echo "       Never build YukiSU against an unbuilt modules_prepare tree." >&2
  exit 1
}

if grep -q '^CONFIG_KSU=y' "$KDIR/.config"; then
  echo "ERROR: $KDIR/.config sets CONFIG_KSU=y; YukiSU supports LKM mode (CONFIG_KSU=m) only." >&2
  exit 1
fi
for req in CONFIG_MODULES CONFIG_KPROBES CONFIG_KRETPROBES CONFIG_HAVE_SYSCALL_TRACEPOINTS CONFIG_KALLSYMS; do
  grep -q "^${req}=y" "$KDIR/.config" || { echo "ERROR: $KDIR/.config missing ${req}=y" >&2; exit 1; }
done

setup_kernel_toolchain "$KP_DIR" "$C" "$REPO_DIR"

if [ ! -f "$KDIR/usr/include/linux/unistd.h" ]; then
  echo "Installing UAPI headers into $KDIR/usr for YukiSU preinit runner..."
  make -C "$C" O="$KDIR" "${KERNEL_MAKE_ARGS[@]}" headers_install
fi

if [ ! -d "$YUKI_DIR/.git" ]; then
  mkdir -p "$(dirname "$YUKI_DIR")"
  git clone --branch "$YUKI_REF" "$YUKI_REPO" "$YUKI_DIR"
elif [ "${YUKI_SKIP_FETCH:-0}" != 1 ]; then
  git -C "$YUKI_DIR" fetch origin "$YUKI_REF"
  git -C "$YUKI_DIR" checkout -q FETCH_HEAD
fi

MDIR="$YUKI_DIR/kernel"
[ -f "$MDIR/Kbuild" ] && [ -f "$YUKI_DIR/uapi/supercall.h" ] || {
  echo "ERROR: incomplete YukiSU checkout under $YUKI_DIR" >&2
  exit 1
}

if ! grep -rqE '\bcancel_work\(' "$C/include/linux/workqueue.h" 2>/dev/null; then
  while IFS= read -r -d '' f; do
    sed -i -E 's/\bcancel_work\(/cancel_work_sync(/g' "$f"
  done < <(grep -rlZ --include='*.c' 'cancel_work(' "$MDIR" || true)
fi

YUKI_ARGS=(
  CONFIG_KSU=m
  CONFIG_KSU_SUPERKEY=y
  KBUILD_MODPOST_WARN=1
  CURL_BIN=true
  KSU_GITHUB_VERSION=
  KSU_GITHUB_VERSION_COMMIT=
)
if [ "$ENABLE_YUKIZYGISK" = 1 ]; then
  YUKI_ARGS+=(CONFIG_KSU_YUKIZYGISK=y)
fi
if [ -n "$KSU_SUPERKEY" ]; then
  YUKI_ARGS+=(KSU_SUPERKEY="$KSU_SUPERKEY")
fi
if [ -n "$KSU_MANAGER_PACKAGE" ]; then
  YUKI_ARGS+=(KSU_MANAGER_PACKAGE="$KSU_MANAGER_PACKAGE")
fi

# Clean prior module build outputs in MDIR without dirtying tracked sources.
make -C "$C" O="$KDIR" M="$MDIR" "${KERNEL_MAKE_ARGS[@]}" "${YUKI_ARGS[@]}" clean >/dev/null 2>&1 || true
make -C "$C" O="$KDIR" M="$MDIR" "${KERNEL_MAKE_ARGS[@]}" "${YUKI_ARGS[@]}" -j"$(nproc)" modules

KO="$MDIR/kernelsu.ko"
[ -f "$KO" ] || { echo "ERROR: kernelsu.ko not built at $KO" >&2; exit 1; }

# Verify every undefined relocation against the unstripped vmlinux symtab.
CHECK_SYM="$MDIR/check_symbol"
HOST_CC=${HOST_CC:-$(command -v clang || command -v cc || command -v gcc)}
"$HOST_CC" -O2 "$MDIR/tools/check_symbol.c" -o "$CHECK_SYM"
"$CHECK_SYM" "$KO" "$KDIR/vmlinux"

if [ -n "${KERNEL_LLVM_STRIP:-}" ] && [ -x "$KERNEL_LLVM_STRIP" ]; then
  "$KERNEL_LLVM_STRIP" -d "$KO" || true
fi

python3 - "$REPO_DIR/scripts" "$KDIR/arch/arm64/boot/Image" "$KO" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import kmi
from rom_kernel_package import kernel_release

rel = kernel_release(Path(sys.argv[2]))
vm = kmi.vermagic(Path(sys.argv[3]))
assert vm.split()[0] == rel, f"vermagic {vm} != Image release {rel}"
print(f"Verified kernelsu.ko vermagic={vm}")
PY

if [ -n "$OUT_DIR" ]; then
  mkdir -p "$OUT_DIR"
  cp -f "$KO" "$OUT_DIR/kernelsu.ko"
  echo "Copied $OUT_DIR/kernelsu.ko"
fi
