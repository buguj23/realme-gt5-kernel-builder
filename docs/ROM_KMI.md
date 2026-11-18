# OGKI / ROM KMI 对齐与刷机边界

设备：Realme GT5 `ossi` / `RMX3820` / `RE5C33`，SM8550 `kalama`。
原厂基线：`RMX3820_16.0.3.500(CN01)` 全量包（`payload.bin` 8,431,831,240 B）。

## 1. 真正的门是 CRC，不是 vermagic

`CONFIG_MODVERSIONS=y` 时，内核按符号逐个比对：
`module_layout`（`struct module` 布局）以及模块导入的每个 `EXPORT_SYMBOL`。
`same_magic()` 只比较空格之后的部分，所以 `5.15.180` 与 `5.15.200` 的前缀差异
本身不会拒绝模块——拒绝发生在 `check_modstruct_version()`。

实测（`scripts/kmi.py`，逐个解析 ELF `__versions`，非抽样）：

| 对象 | 模块数 | `module_layout` CRC |
|---|---|---|
| 原厂 `boot.img` 内核 | — | `0x0222dd63`（镜像内出现 1 次） |
| 原厂 `vendor_dlkm.img` | 385 | `0x0222dd63` |
| 原厂 `vendor_boot` 首阶段 | 450 | `0x0222dd63` |
| 本仓库 OGKI `5.15.123` / BakaSU `Image` | — | **`0x0222dd63`**（`0xedfc7a5c` 出现 0 次） |
| Infinity-X 前一版 ROM 内核（5.15.200） | — | `0xedfc7a5c` |
| 该 ROM 的 `vendor_boot` 模块 | 306 | `0xedfc7a5c` |

结论：上述 `module_layout` 相同只是一项必要条件，不能证明原厂模块可直接配对。
还须验证每个导入符号 CRC、实际交付的模块导出提供者，以及首阶段依赖所在分区。
ROM 自编的 5.15.200 内核与上述模块布局不同，不能混用。

复现：

```bash
python3 scripts/kmi.py verify --symvers Module.symvers --modules <dir> --image Image
python3 scripts/kmi.py image Image --crc 0x0222dd63
python3 scripts/ida_kmi_check.py --symvers Module.symvers --modules <dir> --image Image
```

IDA 侧脚本在读 ELF 时用符号表/`__versions`；对裸 `Image` 用 `Module.symvers`
给出的 CRC 做字节扫描（与审计同法）。

`kmi.py verify` 拒绝缺失 `__versions` / `module_layout`、未知符号、CRC 不匹配以及
重复导出。`Module.symvers` 的模块行不能替代实际交付的 `.ko`：内建符号取 vmlinux 行，
模块符号从交付 ELF 的 `__ksymtab_*` / `__crc_*` 提取。
`rom-stage-kernel.py` 对最终交付集合做同一检查，并要求首阶段导入的模块提供者也在
vendor ramdisk 内；不再静默跳过未通过的 OEM vendor 模块。

此前四分支在平铺模块池中出现 `zsmalloc.ko` 与 `oplus_bsp_zsmalloc.ko`
重复导出 `zs_*`。现在独立检查正常首阶段、正常启动的 DLKM 和 Recovery，
在同一阶段出现重复导出时拒绝交付。该行为已用 AArch64 ELF 样本验证，
原厂 DLKM 和 schema 2 内核包的整套复验待做。构建同源记录取自打包清单。

## 2. 三项致命项与对应守卫

| 致命项（2026-11-13 交付包） | 证据 | 守卫 |
|---|---|---|
| 模块与内核非同一构建 | 306/306 模块 `0xedfc7a5c`，内核 `0x0222dd63` | `scripts/kernel-package.sh`（成套打包）+ `kmi.py verify` |
| 首阶段 `modules.load` 50 vs 146 | 缺 `crypto-qti-hwkm`、`ufs_qcom` 等 | `scripts/rom-stage-kernel.py` 强制原厂顺序 |
| `vendor_boot` 头用 mkbootimg 默认值 | page `0x800`、kernel `0x10008000`、ramdisk `0x11000000`、tags `0x10000100` | `scripts/rom-vendor-boot-fix.sh` |

原厂 `vendor_boot` 的正确信封：

```
header_version 4   pagesize 0x1000   base 0x0
kernel_offset 0x8000   ramdisk_offset 0x1000000   tags_offset 0x100
dtb_offset 0x1f00000
vendor_cmdline "video=vfb:640x400,bpp=32,memsize=3072000 nosoftlockup bootconfig buildvariant=user"
bootconfig 85 B
```

构建入口使用 `rom-verify-delivery.py` 验收 target-files 与 OTA，包括独立 Recovery 镜像中的程序与挂载表。`rom-vendor-boot-fix.sh --check-only` 单独校验 vendor_boot 头部、两套模块顺序及其引用的 ELF。

## 3. 分区与文件系统（原厂实测）

* `/metadata` **f2fs**（原厂 `vendor_boot` 的 `first_stage_ramdisk/fstab.qcom`）。
* 构建时从经过 OTA 哈希校验的两个 DLKM 镜像分别识别 ext4 或 EROFS。
* `boot` 头 v4 内无 ramdisk；首阶段模块与 fstab 在 `vendor_boot`。

## 4. 发布签名

当前构建输出 userdebug 工件并保持 AVB 验证启用。构建以实际 target-files 的 AVB 信任链和 OEM 镜像签名检查为收集条件。
