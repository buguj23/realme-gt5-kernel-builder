#!/usr/bin/env bash
# ksu-exports.sh — export every symbol the YukiSU LKM relocates.
#
# MUST run after the Action-Build patch series. Some of those patches add their own
# EXPORT_TRACEPOINT_SYMBOL_GPL() lines; a second export of the same symbol is a fatal
# "exported twice" modpost error at the vmlinux link (5.15.167/180 hit it when the
# export ran before the patches). Running last lets the guard see theirs and skip.
#
#   ./scripts/ksu-exports.sh /path/to/kernel_platform/common
set -euo pipefail

COMMON=${1:-${KP_DIR:-$HOME/gt5_kernel_ab/kernel_platform}/common}
[ -d "$COMMON" ] || { echo "common tree not found: $COMMON" >&2; exit 1; }

# Symbols the LKM resolves that OGKI may not export.
#
# The vmlinux link covers every project under kernel_platform (common, msm-kernel,
# ...), so an export that already exists in ANY of them turns our addition into a
# fatal "exported twice" modpost error. 5.15.167/180 hit exactly that for
# __tracepoint_sys_enter while 5.15.123 needed the export, so the guard has to look
# wider than $COMMON.
KP_ROOT=$(cd "$COMMON/.." 2>/dev/null && pwd || echo "$COMMON")
exported_anywhere() {
  grep -rqE "EXPORT_[A-Z_]*SYMBOL[A-Z_]*\(\s*(__tracepoint_)?$1\s*\)" \
    --include='*.c' --include='*.h' \
    --exclude-dir=out --exclude-dir=.repo --exclude-dir=.git \
    "$KP_ROOT" 2>/dev/null
}
exp() {
  local f=$1; shift
  [ -f "$COMMON/$f" ] || return 0
  for s in "$@"; do
    exported_anywhere "$s" && continue
    grep -q "EXPORT_SYMBOL_GPL($s)" "$COMMON/$f" || printf 'EXPORT_SYMBOL_GPL(%s);\n' "$s" >> "$COMMON/$f"
  done
}
# Tracepoints are exported as __tracepoint_<event>. EXPORT_TRACEPOINT_SYMBOL_GPL()
# is the same thing but, being a macro over an undeclared identifier, only compiles
# where the event is instantiated. Using the plain EXPORT_SYMBOL_GPL form with an
# explicit extern removes that constraint; either spelling counts as already done.
exptp() {
  local s f
  # EXPORT_SYMBOL_GPL only needs the symbol's address, not a same-TU definition, so
  # the export does not have to live where the tracepoint is instantiated. That
  # matters here: kernel/entry/common.c holds CREATE_TRACE_POINTS for
  # trace/events/syscalls.h yet arm64 does not compile it, so appending there
  # produced a line that compiled and exported nothing (modpost still reported
  # __tracepoint_sys_enter undefined). Emit an extern plus the export into a file
  # that is always part of the arm64 kernel and already exports tracepoints.
  f=${EXPORT_TP_FILE:-kernel/sched/core.c}
  [ -f "$COMMON/$f" ] || { echo "exptp: $f missing" >&2; return 0; }
  for s in "$@"; do
    if exported_anywhere "$s"; then
      echo "exptp: $s already exported"
      continue
    fi
    {
      printf 'extern struct tracepoint __tracepoint_%s;\n' "$s"
      printf 'EXPORT_SYMBOL_GPL(__tracepoint_%s);\n' "$s"
    } >> "$COMMON/$f"
    echo "exptp: $s -> $f (extern + export)"
  done
}
# syscall entry points the LKM resolves by address
for pair in "fs/open.c __arm64_sys_close" "kernel/nsproxy.c __arm64_sys_setns" "kernel/fork.c __arm64_sys_unshare"; do
  f=${pair%% *}
  s=${pair##* }
  [ -f "$COMMON/$f" ] || continue
  grep -q "EXPORT_SYMBOL_GPL($s)" "$COMMON/$f" \
    || printf 'extern long %s(const struct pt_regs *regs);\nEXPORT_SYMBOL_GPL(%s);\n' "$s" "$s" >> "$COMMON/$f"
done

# Optional: ksu-exports.sh <common> <event>...  exports only those tracepoints.
# Used by CI after the patch series, where a patch may already have exported them.
if [ -n "${2:-}" ]; then
  shift
  exptp "$@"
  exit 0
fi
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
exptp sched_process_free sched_process_fork
# 5.15.123 in the OnePlusOSS tree exports sys_exit but not sys_enter, and modpost
# rejects kernelsu.ko on exactly that symbol. Locating the site by header keeps
# this correct for trees that instantiate syscall tracepoints elsewhere.
exptp sys_enter
