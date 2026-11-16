# Upstream and YukiSU adaptation

## What is forbidden

- Google generic GKI boot.img / `ci.android.com` `android13-5.15` Image
- `himanshusaini010/kernel_oneplus_sm8550` as the build common tree
- `common/build.config.gki.aarch64` as a Google GKI bootstrap
- Overlaying `configs/reference/rom_ikconfig.defconfig` onto the OEM tree
- SukiSU-Ultra `setup.sh` + `CONFIG_KSU=y`
- `susfs4ksu` (`50_add_susfs_in_gki-*-5.15.patch`) — rewrites `task_struct` / `super_block`, breaks YukiSU LKM CRC

## What is required

| Item | Value |
|---|---|
| Builder upstream | https://github.com/Numbersf/Action-Build (`SukiSU-Ultra` tree, scripts/patches) |
| Kernel upstream | OnePlusOSS / Numbersf `kernel_manifest` **oneplus/sm8550** (or Appendix **oppo/sm8550**) |
| SoC | SM8550 kalama |
| Build | `oplus_build_kernel.sh kalama gki` (OEM OGKI flavor) |
| Root | https://github.com/Rouyashiki/YukiSU `CONFIG_KSU=m` LKM + Kasumi + YukiZygisk |
| Device | Realme GT5 ossi / RMX3820 / RE5C33 |

## YukiSU integration (professional)

1. Copy `YukiSU/kernel` → `drivers/kernelsu`, `YukiSU/uapi` → `drivers/kernelsu/include/uapi`
2. `obj-$(CONFIG_KSU) += kernelsu/` and `source "drivers/kernelsu/Kconfig"`
3. Inject `config KSU_YUKIZYGISK` (upstream Kbuild tests it, Kconfig did not declare it)
4. Force `CONFIG_KSU=m` (Kconfig `depends on m`)
5. `CONFIG_KPROBES=y` `CONFIG_KRETPROBES=y` `CONFIG_HAVE_SYSCALL_TRACEPOINTS=y` for TSR
6. Export SELinux / VFS / kallsyms / BTF / syscall symbols the LKM relocates
7. Strip `KSU_GITHUB_VERSION := $(shell curl …)` so the kernel build is network-free
8. Package `Image` + `kernelsu.ko` in AnyKernel3; optional `ksud boot-patch`

## ROM

- Replace **boot** with the OGKI Image (same slot).
- Do not replace `vendor_boot` unless that ramdisk was built from this OGKI tree (fstab ext4/f2fs mismatch boot-loops GT5).
- vbmeta: keep ROM `flags=3` disable-verity.
- Modules: if ROM kernel had SukiSU+SUSFS, CRC will not match this LKM kernel. Flash AnyKernel3 (kernel only) **or** a full same-tree `vendor_dlkm`. Never mix.

See `scripts/rom-adapt.sh` and `docs/PROBLEMS_AND_PLAN.md` §1.2 / §4.4.
