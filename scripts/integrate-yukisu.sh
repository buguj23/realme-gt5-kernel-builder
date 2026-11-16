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

# Upstream kasumi calls cancel_work(). That symbol only exists in some OEM
# forks: OnePlusOSS android_kernel_common_oneplus_sm8550
#   oneplus/sm8550_u_14.0.0_oneplus11 (5.15.123)  -> ABSENT  => build fails
#   oneplus/sm8550_v_15.0.0_ace_2_pro (149/167)   -> present
#   oneplus/sm8550_b_16.0.0_ace_2_pro (180)       -> present
# cancel_work_sync() exists on all three and returns the same bool, and the
# neighbouring code in these very files already uses the _sync form.
while IFS= read -r -d '' f; do
  sed -i -E 's/\bcancel_work\(/cancel_work_sync(/g' "$f"
done < <(grep -rlZ --include='*.c' 'cancel_work(' "$DST" || true)
if grep -rqE '\bcancel_work\(' --include='*.c' "$DST"; then
  echo "YukiSU sources still call non-existent cancel_work()" >&2
  exit 1
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

# Symbols the LKM resolves that OGKI may not export.
exp() {
  local f=$1; shift
  [ -f "$COMMON/$f" ] || return 0
  for s in "$@"; do
    grep -rqE "EXPORT_SYMBOL(_GPL)?\($s\)" --include='*.c' "$COMMON" 2>/dev/null && continue
    grep -q "EXPORT_SYMBOL_GPL($s)" "$COMMON/$f" || printf 'EXPORT_SYMBOL_GPL(%s);\n' "$s" >> "$COMMON/$f"
  done
}
# Tracepoints are not EXPORT_SYMBOL'ed by name: the kernel idiom is
# EXPORT_TRACEPOINT_SYMBOL_GPL(<event>), which expands to
# EXPORT_SYMBOL_GPL(__tracepoint_<event>). The macro only compiles in the single
# translation unit that defines CREATE_TRACE_POINTS and includes the event header,
# and that unit differs between OEM trees (5.15.123 keeps it in
# kernel/entry/common.c, other trees elsewhere). So locate it by header instead of
# hardcoding a path, and treat either export spelling as already done.
tp_site() {
  local hdr=$1 f first=""
  for f in $(grep -rl 'CREATE_TRACE_POINTS' --include='*.c' \
        --exclude-dir=tools --exclude-dir=samples --exclude-dir=Documentation \
        --exclude-dir=scripts --exclude-dir=selftests \
        "$COMMON" 2>/dev/null | sort); do
    grep -q "$hdr" "$f" || continue
    # A file that already carries EXPORT_TRACEPOINT_SYMBOL is proven to be linked
    # into vmlinux and to own instantiations; prefer it over a plain header match.
    if grep -q 'EXPORT_TRACEPOINT_SYMBOL' "$f"; then
      echo "${f#"$COMMON"/}"
      return 0
    fi
    [ -n "$first" ] || first="${f#"$COMMON"/}"
  done
  [ -n "$first" ] && echo "$first"
  return 0
}
exptp() {
  local f=$1; shift
  [ -n "$f" ] && [ -f "$COMMON/$f" ] || { echo "exptp: no instantiation site for $*" >&2; return 0; }
  for s in "$@"; do
    if grep -rqE "EXPORT_(TRACEPOINT_)?SYMBOL(_GPL)?\(\s*(__tracepoint_)?$s\s*\)" --include='*.c' "$COMMON" 2>/dev/null; then
      echo "exptp: $s already exported"
      continue
    fi
    if ! grep -qE "EXPORT_(TRACEPOINT_)?SYMBOL_GPL\(\s*(__tracepoint_)?$s\s*\)" "$COMMON/$f"; then
      printf 'EXPORT_TRACEPOINT_SYMBOL_GPL(%s);\n' "$s" >> "$COMMON/$f"
      echo "exptp: $s -> $f"
    fi
  done
}
exp security/selinux/avc.c avc_ss_reset avc_has_perm
exp security/selinux/ss/avtab.c avtab_alloc avtab_destroy avtab_insert_nonunique avtab_search_node avtab_search_node_next
exp security/selinux/ss/conditional.c cond_compute_av
exp security/selinux/ss/ebitmap.c ebitmap_set_bit ebitmap_cmp ebitmap_contains ebitmap_destroy ebitmap_get_bit
exp security/selinux/ss/hashtab.c __hashtab_insert
exp security/selinux/ss/mls.c mls_compute_context_len mls_context_to_sid mls_sid_to_context
exp security/selinux/ss/policydb.c policydb_filenametr_search policydb_load_isids policydb_context_isvalid policydb_read policydb_write policydb_destroy
exp security/selinux/ss/sidtab.c sidtab_context_to_sid sidtab_destroy sidtab_search_entry sidtab_sid2str_get sidtab_sid2str_put
exp security/selinux/ss/symtab.c symtab_search symtab_insert
exp security/selinux/status.c selinux_status_update_policyload
exp security/selinux/netlink.c selnl_notify_policyload
exp security/selinux/hooks.c selinux_blob_sizes selinux_state security_bounded_transition
exp security/security.c security_inode_init_security_anon
exp mm/init-mm.c init_mm
exp mm/maccess.c copy_to_kernel_nofault strncpy_from_user_nofault
exp arch/arm64/mm/mmu.c __set_fixmap dcache_clean_inval_poc
exp fs/namespace.c mntns_operations path_mount path_umount
exp fs/nsfs.c ns_get_path
exp fs/fs_struct.c set_fs_pwd
exp fs/seq_file.c seq_path_root
exp fs/file.c __fdget_raw
exp fs/ext4/sysfs.c ext4_unregister_sysfs
exp kernel/kallsyms.c kallsyms_lookup_name kallsyms_lookup_size_offset
exp kernel/cred.c set_cred_ucounts
exp kernel/task_work.c task_work_add
exp kernel/user.c alloc_uid
exp kernel/pid.c change_pid
exp kernel/seccomp.c seccomp_filter_release
exp lib/is_single_threaded.c current_is_single_threaded
exp kernel/bpf/btf.c btf_find_by_name_kind btf_name_by_offset btf_type_by_id btf_type_skip_modifiers
exp kernel/bpf/verifier.c bpf_get_btf_vmlinux
# modpost 5.15.180: undefined in kernelsu.ko, present-but-unexported in OEM OGKI
# on all three OnePlusOSS sm8550 branches (u_14.0.0_oneplus11, v_15.0.0_ace_2_pro,
# b_16.0.0_ace_2_pro) — verified against the official Image symbol table too.
exp kernel/task_work.c task_work_cancel_match
exp kernel/audit.c audit_log_n_untrustedstring
exp security/commoncap.c cap_capable
exp security/selinux/ss/services.c security_validate_transition
exptp "$(tp_site trace/events/sched.h)" sched_process_free sched_process_fork
# 5.15.123 in the OnePlusOSS tree exports sys_exit but not sys_enter, and modpost
# rejects kernelsu.ko on exactly that symbol. Locating the site by header keeps
# this correct for trees that instantiate syscall tracepoints elsewhere.
exptp "$(tp_site trace/events/syscalls.h)" sys_enter
for pair in "fs/open.c __arm64_sys_close" "kernel/nsproxy.c __arm64_sys_setns" "kernel/fork.c __arm64_sys_unshare"; do
  set -- $pair
  [ -f "$COMMON/$1" ] || continue
  grep -q "EXPORT_SYMBOL_GPL($2)" "$COMMON/$1" \
    || printf 'extern long %s(const struct pt_regs *regs);\nEXPORT_SYMBOL_GPL(%s);\n' "$2" "$2" >> "$COMMON/$1"
done
if [ -f "$COMMON/arch/arm64/kernel/ptrace.c" ]; then
  grep -q 'EXPORT_TRACEPOINT_SYMBOL_GPL(sys_enter)' "$COMMON/arch/arm64/kernel/ptrace.c" \
    || sed -i 's/^EXPORT_TRACEPOINT_SYMBOL_GPL(sys_exit);$/EXPORT_TRACEPOINT_SYMBOL_GPL(sys_exit);\nEXPORT_TRACEPOINT_SYMBOL_GPL(sys_enter);/' \
         "$COMMON/arch/arm64/kernel/ptrace.c"
fi

# Overlay YukiSU + kprobe flags onto OEM OGKI defconfig (never Google GKI / ROM IKCONFIG).
CFG=$COMMON/arch/arm64/configs/gki_defconfig
if [ ! -f "$CFG" ]; then
  echo "OEM OGKI gki_defconfig missing at $CFG" >&2
  exit 1
fi
set_config() {
  local val=$1 key=${1%%=*}
  if grep -qE "^(${key}=|# ${key} is not set)" "$CFG"; then
    VAL=$val awk -v key="$key" '
      $0 == "# " key " is not set" || index($0, key "=") == 1 { print ENVIRON["VAL"]; next }
      { print }
    ' "$CFG" > "$CFG.tmp" && mv "$CFG.tmp" "$CFG"
  else
    printf '%s\n' "$val" >> "$CFG"
  fi
}
while IFS= read -r kv; do
  [[ -z "$kv" || "$kv" =~ ^# ]] && continue
  set_config "$kv"
done < "$REPO_DIR/configs/features.config"

if [ -f "$COMMON/build.config.gki" ]; then
  sed -i 's/check_defconfig//' "$COMMON/build.config.gki" || true
fi

echo "YukiSU LKM integrated into $DST (CONFIG_KSU=m, Kasumi+YukiZygisk, OEM OGKI defconfig)"
