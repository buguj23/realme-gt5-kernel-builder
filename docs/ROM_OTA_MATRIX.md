# 官方 OTA 基线对照

设备恒为 **RMX3820 / RE5C33 / 工程 22635**。表内固件属于 CN A/B OTA。审计中核验的 A14/A15 payload 标记为部分更新。

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

## 原厂输入校验

按同一行校验并准备原厂输入。15.0.0.1300 与 15.0.0.1400 的内核均为 5.15.167，各自具有不同 UTS 和 OTA 元数据标识。16.0.2.402 与 16.0.3.500 也需要各自的原厂 DTB、DTBO 与模块。对应构建参数见 [ROM_BUILD.md](ROM_BUILD.md)。
