#!/usr/bin/env bash
# lib-kernel.sh — shared toolchain, proxy, and Kconfig helpers for Realme GT5 (5.15.149).
# Source from 00-fetch.sh, 10-patch.sh, 20-build.sh, integrate-yukisu.sh, and CI.

enable_local_proxy_if_up() {
  if [ -z "${http_proxy:-}" ] && timeout 1 bash -c '</dev/tcp/127.0.0.1/7890' 2>/dev/null; then
    export http_proxy="http://127.0.0.1:7890"
    export https_proxy="http://127.0.0.1:7890"
    export HTTP_PROXY="$http_proxy"
    export HTTPS_PROXY="$https_proxy"
  fi
}

detect_clang_dir() {
  local kp_dir=$1
  local common_dir=${2:-$kp_dir/common}
  if [ -n "${CLANG_DIR:-}" ] && [ -x "$CLANG_DIR/bin/clang" ]; then
    echo "$CLANG_DIR"
    return 0
  fi
  local ver="" cand
  if [ -f "$common_dir/build.config.constants" ]; then
    ver=$(grep -m1 '^CLANG_VERSION=' "$common_dir/build.config.constants" | cut -d= -f2 || true)
  fi
  for cand in \
    ${ver:+"$kp_dir/prebuilts/clang/host/linux-x86/clang-$ver"} \
    "$kp_dir"/prebuilts/clang/host/linux-x86/clang-r*; do
    if [ -d "$cand/bin" ] && [ -x "$cand/bin/clang" ]; then
      echo "$cand"
      return 0
    fi
  done
  return 1
}

detect_pahole_bin() {
  local kp_dir=$1
  local cand
  for cand in \
    "$kp_dir/prebuilts/kernel-build-tools/linux-x86/bin/pahole" \
    "$kp_dir/build/kernel/build-tools/path/linux-x86/pahole" \
    "$(command -v pahole 2>/dev/null || true)"; do
    if [ -n "$cand" ] && [ -x "$cand" ]; then
      echo "$cand"
      return 0
    fi
  done
  return 1
}

detect_ccache_bin() {
  local repo_dir=$1
  if command -v ccache >/dev/null 2>&1; then
    command -v ccache
    return 0
  fi
  if [ -x "$repo_dir/lib/ccache" ]; then
    echo "$repo_dir/lib/ccache"
    return 0
  fi
  return 1
}

setup_kernel_toolchain() {
  local kp_dir=$1
  local common_dir=${2:-$kp_dir/common}
  local repo_dir=$3
  local clang_dir pahole_bin ccache_bin real_clang lld_bin

  clang_dir=$(detect_clang_dir "$kp_dir" "$common_dir" || true)
  if [ -n "$clang_dir" ]; then
    export PATH="$clang_dir/bin:$PATH"
    real_clang="$clang_dir/bin/clang"
  else
    real_clang=$(command -v clang 2>/dev/null || true)
  fi
  [ -x "${real_clang:-}" ] || { echo "clang not found in $kp_dir/prebuilts or PATH" >&2; return 1; }

  pahole_bin=$(detect_pahole_bin "$kp_dir" || true)
  [ -x "${pahole_bin:-}" ] || { echo "pahole not found in $kp_dir or PATH" >&2; return 1; }

  lld_bin="$({ [ -n "$clang_dir" ] && [ -x "$clang_dir/bin/ld.lld" ] && echo "$clang_dir/bin/ld.lld"; } || command -v ld.lld || true)"
  [ -x "${lld_bin:-}" ] || { echo "ld.lld not found" >&2; return 1; }

  local wrap_dir="$kp_dir/.gt5-wrappers"
  mkdir -p "$wrap_dir"
  local cc_bin="$real_clang"
  if [ "${USE_CCACHE:-1}" = 1 ]; then
    ccache_bin=$(detect_ccache_bin "$repo_dir" || true)
    if [ -n "$ccache_bin" ]; then
      printf '#!/usr/bin/env bash\nexec "%s" "%s" "$@"\n' "$ccache_bin" "$real_clang" > "$wrap_dir/cc"
      chmod +x "$wrap_dir/cc"
      cc_bin="$wrap_dir/cc"
    fi
  fi

  local ld_bin="$lld_bin"
  if [ -n "${THINLTO_CACHE_DIR:-}" ]; then
    mkdir -p "$THINLTO_CACHE_DIR"
    printf '#!/usr/bin/env bash\nexec "%s" "$@" --thinlto-cache-dir="%s" --thinlto-cache-policy=cache_size_bytes=3g --thinlto-jobs=%s\n' \
      "$lld_bin" "$THINLTO_CACHE_DIR" "$(nproc)" > "$wrap_dir/ld"
    chmod +x "$wrap_dir/ld"
    ld_bin="$wrap_dir/ld"
  fi

  local root_real
  root_real=$(cd "$kp_dir/.." && pwd -P)
  local map_cflags="-fdebug-prefix-map=$root_real=. -ffile-prefix-map=$root_real=. -no-canonical-prefixes -O2 -pipe -Wno-error -fno-stack-protector -D__ANDROID_COMMON_KERNEL__"
  local map_cppflags="-fmacro-prefix-map=$root_real=."

  KERNEL_CLANG_BIN="$real_clang"
  KERNEL_LLVM_STRIP="${clang_dir:+$clang_dir/bin/}llvm-strip"
  [ -x "$KERNEL_LLVM_STRIP" ] || KERNEL_LLVM_STRIP="$(command -v llvm-strip || true)"
  KERNEL_MAKE_ARGS=(
    LLVM=1
    LLVM_IAS=1
    ARCH=arm64
    CROSS_COMPILE=aarch64-linux-gnu-
    CC="$cc_bin"
    HOSTCC="$cc_bin"
    LD="$ld_bin"
    HOSTLD="$lld_bin"
    PAHOLE="$pahole_bin"
    KCFLAGS="$map_cflags"
    KCPPFLAGS="$map_cppflags"
  )
  export KERNEL_CLANG_BIN KERNEL_LLVM_STRIP
}

apply_config_fragment() {
  local common_dir=$1
  local cfg_file=$2
  local fragment=$3
  local cfg_tool="$common_dir/scripts/config"
  [ -x "$cfg_tool" ] || { echo "missing $cfg_tool" >&2; return 1; }
  [ -f "$fragment" ] || { echo "missing fragment: $fragment" >&2; return 1; }

  local line key val
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [ -z "$line" ] && continue
    if [[ "$line" =~ ^#\ (CONFIG_[A-Za-z0-9_]+)\ is\ not\ set$ ]]; then
      "$cfg_tool" --file "$cfg_file" -d "${BASH_REMATCH[1]}"
      continue
    fi
    [[ "$line" == \#* ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    case "$val" in
      y) "$cfg_tool" --file "$cfg_file" -e "$key" ;;
      m) "$cfg_tool" --file "$cfg_file" -m "$key" ;;
      n) "$cfg_tool" --file "$cfg_file" -d "$key" ;;
      \"*\") "$cfg_tool" --file "$cfg_file" --set-str "$key" "${val:1:${#val}-2}" ;;
      *) "$cfg_tool" --file "$cfg_file" --set-val "$key" "$val" ;;
    esac
  done < "$fragment"
}
