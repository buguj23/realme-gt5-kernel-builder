#!/usr/bin/env bash
# 10-patch.sh — apply the unified feature set to the 5.15.200 tree and install the
# ROM's own kernel config as the build base, then add our features on top.
#
#   Root      : YukiSU LKM (CONFIG_KSU=m) + Kasumi (embedded)
#   Injector  : Re-Kernel (LKM-Source, Generic Netlink + netfilter)
#   Container : MidAS ghost-task patch + namespaces/cgroup/seccomp/squashfs/overlayfs
#   ZRAM      : lz4kd + lz4k_oplus (CONFIG_ZRAM=m, default compressor lz4kd)
#   UTS       : .scmversion -> 5.15.200-ga1403aca1412-dirty (identical to ROM kernel)
#   Symbols   : 47 kernel symbols exported for the LKM (SELinux/BTF/kallsyms/path/VFS)
set -euo pipefail

KP_DIR=${KP_DIR:-$HOME/gt5_kernel_ab/kernel_platform}
C=$KP_DIR/common
REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
WORK=${WORK:-/tmp/kbuild_src}
mkdir -p "$WORK"

# ---------- sources for the patches ----------
[ -d "$WORK/YukiSU" ]    || git clone --depth 1 https://github.com/Rouyashiki/YukiSU.git "$WORK/YukiSU"
[ -d "$WORK/Re-Kernel" ] || git clone --depth 1 https://github.com/Sakion-Team/Re-Kernel.git "$WORK/Re-Kernel"
[ -d "$WORK/SukiSU_patch" ] || git clone --depth 1 https://github.com/ShirkNeko/SukiSU_patch.git "$WORK/SukiSU_patch"

# ---------- 1. MidAS (DroidSpaces container support) ----------
patch -d "$C" -p1 -F3 --forward < "$REPO_DIR/patches/ghost-task-for-midas.patch" || true

# ---------- 2. YukiSU + Kasumi ----------
mkdir -p "$C/drivers/kernelsu"
cp -a "$WORK/YukiSU/kernel/." "$C/drivers/kernelsu/"
rm -rf "$C/drivers/kernelsu/include/uapi"
cp -a "$WORK/YukiSU/uapi" "$C/drivers/kernelsu/include/uapi"
# no network lookups during the build
sed -i 's|^KSU_GITHUB_VERSION := \$(shell.*|KSU_GITHUB_VERSION :=|' "$C/drivers/kernelsu/Kbuild"
sed -i 's|^  KSU_GITHUB_VERSION_COMMIT := \$(shell.*|  KSU_GITHUB_VERSION_COMMIT :=|' "$C/drivers/kernelsu/Kbuild"
printf 'include $(src)/Kbuild\n' > "$C/drivers/kernelsu/Makefile"
grep -q 'kernelsu/' "$C/drivers/Makefile" || echo 'obj-$(CONFIG_KSU) += kernelsu/' >> "$C/drivers/Makefile"
grep -q 'drivers/kernelsu/Kconfig' "$C/drivers/Kconfig" || echo 'source "drivers/kernelsu/Kconfig"' >> "$C/drivers/Kconfig"

# ---------- 3. Re-Kernel ----------
mkdir -p "$C/drivers/rekernel"
cp -a "$WORK/Re-Kernel/LKM-Source/." "$C/drivers/rekernel/"
grep -q 'drivers/rekernel/Kconfig' "$C/drivers/Kconfig" || sed -i '/^endmenu/i source "drivers/rekernel/Kconfig"' "$C/drivers/Kconfig"
grep -q 'rekernel/' "$C/drivers/Makefile" || printf '\n# Re-Kernel Support\nobj-$(CONFIG_REKERNEL) += rekernel/\n' >> "$C/drivers/Makefile"

# ---------- 4. ZRAM lz4kd / lz4k_oplus ----------
S=$WORK/SukiSU_patch/other/zram
cp -r "$S"/lz4k/include/linux/* "$C/include/linux/"
cp -r "$S"/lz4k/lib/* "$C/lib/"
cp -r "$S"/lz4k/crypto/* "$C/crypto/"
cp -r "$S"/lz4k_oplus "$C/lib/"
patch -d "$C" -p1 -F3 --forward < "$S/zram_patch/5.15/lz4kd.patch" || true
patch -d "$C" -p1 -F3 --forward < "$S/zram_patch/5.15/lz4k_oplus.patch" || true

# ---------- 5. exported symbols required by the LKM ----------
exp() {
    local f=$1; shift
    for s in "$@"; do
        grep -rqE "EXPORT_SYMBOL(_GPL)?\($s\)" --include=*.c "$C" 2>/dev/null && continue
        grep -q "EXPORT_SYMBOL_GPL($s)" "$C/$f" || printf 'EXPORT_SYMBOL_GPL(%s);\n' "$s" >> "$C/$f"
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
for pair in "fs/open.c __arm64_sys_close" "kernel/nsproxy.c __arm64_sys_setns" "kernel/fork.c __arm64_sys_unshare"; do
    set -- $pair
    grep -q "EXPORT_SYMBOL_GPL($2)" "$C/$1" || printf 'extern long %s(const struct pt_regs *regs);\nEXPORT_SYMBOL_GPL(%s);\n' "$2" "$2" >> "$C/$1"
done
grep -q EXPORT_TRACEPOINT_SYMBOL_GPL\(sys_enter\) "$C/arch/arm64/kernel/ptrace.c" || \
    sed -i 's/^EXPORT_TRACEPOINT_SYMBOL_GPL(sys_exit);$/EXPORT_TRACEPOINT_SYMBOL_GPL(sys_exit);\nEXPORT_TRACEPOINT_SYMBOL_GPL(sys_enter);/' "$C/arch/arm64/kernel/ptrace.c"

# ---------- 6. config: ROM base + unified features ----------
cp "$REPO_DIR/configs/gki_defconfig.rom" "$C/arch/arm64/configs/gki_defconfig"
CFG=$C/arch/arm64/configs/gki_defconfig
set_config() {
    local val=$1 key=${1%%=*}
    if grep -qF "${key}=" "$CFG" || grep -qF "# ${key} is not set" "$CFG"; then
        VAL=$val awk -v key="$key" '$0=="# "key" is not set" || index($0,key"=")==1 {print ENVIRON["VAL"]; next} {print}' "$CFG" > "$CFG.tmp" && mv "$CFG.tmp" "$CFG"
    else
        printf '%s\n' "$val" >> "$CFG"
    fi
}
while IFS= read -r kv; do
    case "$kv" in ''|'#'*) continue;; esac
    set_config "$kv"
done < "$REPO_DIR/configs/features.config"
sed -i 's/check_defconfig//' "$C/build.config.gki"

# ---------- 7. tree glue ----------
# vendor trees expected by the fork (symlinks into sm8550-modules)
[ -e "$C/drivers/power/oplus" ] || ln -s ../../../sm8550-modules/oplus/kernel/charger "$C/drivers/power/oplus"

echo "patched: $C"
