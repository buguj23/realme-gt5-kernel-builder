# Realme GT5 (`5.15.149`) Source Manifest Map

This repository targets **one** verified Realme GT5 (`RMX3820` / `RE5C33` / `ossi`) source baseline matching stock **`RMX3820_15.0.0.320(CN01)`** (Android 15, SPL `2024-11-05`):

| Key | Value |
|---|---|
| Manifest Repo | `https://github.com/DestoryG/kernel_manifest` (`realme/sm8550`) |
| Manifest File | `manifests/realme-sm8550/realme_gt5_v.xml` (`FILE=realme_gt5_v`) |
| Kernel Source | `realme-kernel-opensource/realme_GT5-AndroidV-common-source` (`5.15.149`) |
| SoC / Platform | `SM8550` / `kalama` (`KMI: android13-5.15`, gen `8`) |
| Toolchain | Hermetic Clang `r450784e` (`14.0.7`) |
| Verified `module_layout` | `0x0222dd63` (**3260 / 3260** vmlinux symbol CRCs match stock `.ko`s) |

> Why OnePlus analogues (`oneplus_ace2_pro_v`, `oneplus_ace2_pro_b`) were removed:
> Empirically tested `OnePlusOSS` SM8550 sources produce `module_layout = 0xbb266e1e`, which fails `insmod` against stock Realme GT5 `15.0.0.320` modules (`0x0222dd63`). Only `realme_gt5_v` (`realme_GT5-AndroidV-*`) preserves exact KMI compatibility.
