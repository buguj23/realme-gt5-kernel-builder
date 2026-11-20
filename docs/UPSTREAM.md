# Upstream Provenance (`5.15.149`)

| Component | Source | Purpose |
|---|---|---|
| Kernel manifest & toolchain layout | `DestoryG/kernel_manifest` (`realme/sm8550` / `realme_gt5_v.xml`) & `buguj23/GT5-Action-Build` | Hermetic SM8550 OGKI source & Clang `r450784e` |
| Kernel / Vendor source | `realme-kernel-opensource/realme_GT5-AndroidV-{common,kernel,vendor}-source` (`master`) | Exact `5.15.149` GT5 source (`module_layout = 0x0222dd63`) |
| Root LKM | `Rouyashiki/YukiSU` (`CONFIG_KSU=m` + Kasumi + YukiZygisk + UTS View) | Out-of-tree LKM built against exact `Module.symvers` + `vmlinux` |
| AnyKernel3 template | `Numbersf/AnyKernel3` | Boot-only v4 `Image` flasher + optional `kernelsu.ko` staging |
| Optional patches | `patches/{ghost-task-for-midas,bbrv3,ntsync,unicode_bypass_fix_6.1-.patch}`, `Re-Kernel`, `Baseband-guard`, `SukiSU_patch` ZRAM `lz4kd` | Opt-in patches (disabled by default for Pure-OGKI KMI purity) |
| Device & common ROM deps | `LineageOS` (`device/oneplus/sm8550-common`, `hardware/oplus`, `tools/extract-utils`) & `ProjectInfinity-X` (`15`) | ROM build integration (`infinity_ossi`) |
