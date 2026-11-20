# KMI & Partition ABI Verification (`5.15.149`)

## Measured KMI Compatibility (`realme_gt5_v` vs OnePlus Analogues)

Stock `RMX3820_15.0.0.320(CN01)` kernel:
- `kernel_release`: `5.15.149-android13-8-o-01120-g3337bebe8205`
- `module_layout`: `0x0222dd63`
- Imported vmlinux symbols across all `822` stock `.ko`s (`vendor_boot`: 442, `vendor_dlkm`: 378, `system_dlkm`: 2): `3260`

Comparison of Kbuild output `vmlinux` / `Image` against those `3260` stock symbols:

| Source Manifest | `module_layout` | Stock Symbols Matched | Verdict |
|---|---|---|---|
| `oneplus_ace2_pro_v` (`OnePlusOSS`) | `0xbb266e1e` | Broken | Reject |
| **`realme_gt5_v` (`DestoryG` / `realme_GT5-AndroidV`)** | **`0x0222dd63`** | **3260 / 3260 (100%)** | **Supported Baseline** |

> Both Hermetic Clang `r450784e` (`14.0.7`) and unmodified KMI structs (`NO SUSFS`, `NO CONFIG_KSU=y`) are required to preserve `0x0222dd63`.

## Boot & Partition Verification (`init` Ground Truth)

Inspected directly in stock `init_boot` `init`:
- `ReadDefaultFstab`: locates `fstab.qcom` matching `androidboot.hardware=qcom`.
- `Modprobe::Insmod`: treats `EEXIST` (`17`) as already loaded; aborts in `FirstStageMain` on missing dependencies or CRC mismatch (`Failed to load kernel modules`).
- `vendor_boot`: header v4, `pagesize=0x1000`, `kernel_offset=0x8000`, `ramdisk_offset=0x1000000`, `tags_offset=0x100`, `dtb_offset=0x1f00000`, `os_version=13.0.0`, `os_patch_level=2024-11`, `5` concatenated DTBs (`dtb[1..4]` require disabling legacy `/firmware/android/fstab` during ROM staging).

Run offline CRC verification manually:
```bash
python3 scripts/kmi.py verify --symvers /path/to/Module.symvers --modules /path/to/modules --image /path/to/Image
```
