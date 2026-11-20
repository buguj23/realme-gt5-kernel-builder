# Official Realme GT5 150W Stock Baseline (`5.15.149`)

Single supported firmware baseline: **`RMX3820_15.0.0.320(CN01)`** (`RMX3820_11.F.06_2060_202411241938`, Android 15 / API 35, SPL `2024-11-05`).

- Kernel release: `5.15.149-android13-8-o-01120-g3337bebe8205`
- Kernel manifest: `DestoryG/kernel_manifest` (`realme/sm8550`, `realme_gt5_v.xml`) -> `realme-kernel-opensource/realme_GT5-AndroidV-*`
- KMI / CRC: `android13-5.15` (gen `8`), `module_layout = 0x0222dd63`
- Boot layout: `boot` (`192 MiB`, header v4, kernel-only, `os_version=13.0.0`, `os_patch_level=2024-11`), `init_boot` (`8 MiB`), `vendor_boot` (`192 MiB`, 144 unique first-stage / 435 unique recovery modules, 5 concatenated DTBs), `dtbo` (`24 MiB`), `recovery` (`100 MiB`, kernel-less), `vbmeta` (`12 KiB`, flags `0`)
- Dynamic partitions: group `qti_dynamic_partitions` (`14491320320` bytes), `/metadata` = **`f2fs`**, `vendor_dlkm` = **ext4** (`378` modules), `system_dlkm` = **ext4** (`2` modules: `zram.ko`, `zsmalloc.ko`), `vendor`/`odm`/`system_ext`/`product`/`my_manifest` = **EROFS**.
