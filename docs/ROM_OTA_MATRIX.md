# 官方全量包对照（禁止混刷 / 禁止自编译完整 ROM）

设备恒为 **RMX3820 / RE5C33 / 工程 22635**。下列均为 CN 全量 AB OTA，payload minor=8。

| ColorOS | 内核 UTS | os_patch | 指纹 incremental | `/metadata` | 对应 git 分支 |
|---|---|---|---|---|---|
| 14.0.0.1120 | `5.15.123-android13-8-00760-ga4e8787d5799` | 2024-10 | `T.1a73b78-941b-1` | **f2fs** | `5.15.123` |
| 15.0.0.320 | `5.15.149-android13-8-o-01120-g3337bebe8205` | 2024-11 | `T.1b22798_7579-6758f` | **f2fs** | `5.15.149` |
| 15.0.0.1300 | `5.15.167-android13-8-o-01140-g043e86cdd499` | 2025-08 | `T.1f182dd_1-4888b` | **f2fs** | **不建分支**（与 1400 同 SUBLEVEL，scm 不同，vendor_dlkm 不能混） |
| 15.0.0.1400 | `5.15.167-android13-8-o-01142-g18bd462653c5` | 2025-09 | `T.1fc6783-2-f6d31` | **f2fs** | `5.15.167` |
| 16.0.3.500 | `5.15.180-android13-8-o-01176-g6333b0dbc8ed` | 2026-02 | `T.5727b50-35127b2-34d6407` | **f2fs** | `5.15.180` |

五份包共同点（已从 boot/vendor_boot/recovery/vbmeta 实测）：

- boot v4 **kernel-only**，`os_version=13.0.0`（GKI 头，不是用户空间 Android 版本）
- init_boot v4 ramdisk only 8MiB
- recovery **100MiB、kernel_size=0**
- vbmeta flags=**0**
- vendor_boot 首阶段 fstab：`/metadata` f2fs，userdata f2fs + `resize,fscompress`，system 同时给 ext4/erofs
- 闭源驱动在 **官方 vendor_dlkm / vendor_boot ramdisk**，不在 boot Image

先前「设备原 metadata=ext4」**不是这五份官方全量包**。官方 CN 全量从 14.0.0.1120 到 16.0.3.500 全是 f2fs。ext4 fstab 对上 f2fs 分区 = 挂载失败/循环（`PROBLEMS_AND_PLAN.md`）。

## 安全刷法（唯一允许）

1. 手机先处于上表**某一行**的官方 ColorOS（完整 super + vendor_boot + vendor_dlkm + dtbo + init_boot）。
2. 只刷该行分支打出来的 **AnyKernel3 boot**（Image + kernelsu.ko）。
3. **不刷** 自编译 system / vendor / odm / product / super / userdata / metadata。
4. dtbo、init_boot、vendor_boot、vendor_dlkm 必须与该行 ColorOS **同包**。1300 与 1400 虽同为 5.15.167，scm 不同，禁止交叉。
5. 自定义 boot 若 AVB 拦：只对 vbmeta 关校验（flags=3），不要换官方 vbmeta 公钥。
6. OrangeFox：独立 recovery 分区、不含内核；不能当 fastbootd。

## 明确禁止

- 自编译完整类原生再刷 super（成本高、AVB/动态分区/oplus my_* 逻辑分区、FBE 全是砖点）
- 用 5.15.167 分支产物刷在 15.0.0.1300 上
- 16.0.2.402 的 dtbo/init_boot 配 16.0.3.500 内核
- 自建 vendor_dlkm 替换官方模块
