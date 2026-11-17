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

结论：Action-Build 的 OGKI 内核与原厂模块同 CRC，可直接配对；ROM 自编的
5.15.200 内核与原厂模块不同 CRC，必须成套替换。

复现：

```bash
python3 scripts/kmi.py verify --symvers Module.symvers --modules <dir> --image Image
python3 scripts/kmi.py image Image --crc 0x0222dd63
python3 scripts/ida_kmi_check.py --symvers Module.symvers --modules <dir> --image Image
```

IDA 侧脚本在读 ELF 时用符号表/`__versions`；对裸 `Image` 用 `Module.symvers`
给出的 CRC 做字节扫描（与审计同法）。

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

`rom-vendor-boot-fix.sh --check-only` 在交付包上会同时报出这三项，可用作 CI 门禁。

## 3. 分区与文件系统（原厂实测）

* `/metadata` **f2fs**（原厂 `vendor_boot` 的 `first_stage_ramdisk/fstab.qcom`）。
* `system` / `system_ext` / `product` ext4；`vendor` / `vendor_dlkm` / `system_dlkm` erofs；
  `odm` erofs。
* `boot` 头 v4 内无 ramdisk；首阶段模块与 fstab 在 `vendor_boot`。

## 4. 刷机边界（防 ARB / 双槽损坏）

只刷 OS 分区：`boot`、`init_boot`、`vendor_boot`、`dtbo`、`vbmeta`、`super` 内逻辑分区。
不要随 ROM 脚本覆盖 `xbl`、`abl`、`tz`、`hyp` 等引导链——这些一旦触发高版本
Rollback Index，EDL 也回不去。原厂全量包与解出的 `boot/init_boot/vendor_boot/dtbo/vbmeta`
必须本地归档，作为每次刷机前的兜底。

AVB：自编 `vbmeta` 需 `--flags 3`（HASHTREE_DISABLED | VERIFICATION_DISABLED），
与可用 ROM 的做法一致。
