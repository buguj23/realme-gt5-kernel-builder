# 兼容性结论与缺失清单

## 1. 为什么 ROM 现有模块不能直接复用

ROM 的 `vendor_dlkm` / `vendor_boot` 模块 vermagic 为 `5.15.200-ga1403aca1412-dirty`，
本内核源码可对齐该字符串；但 **modversions CRC 无法对齐**：

- ROM 内核构建时在同一源码上叠加了 **SukiSU + SUSFS + Re-Kernel** 补丁集；
- SUSFS 会改写 `struct task_struct` / `struct super_block` 等核心结构（新增字段），
  `module_layout`、`_dev_err`、`kmalloc_caches` 等导出符号的 CRC 随之改变；
- 本内核用 YukiSU（LKM 形态）+ 自己的导出集，结构布局与 ROM 内核不同。

实测：ROM 的 413 个模块 vs 本内核 `Module.symvers` → 6571 处 CRC 不匹配（全量不兼容）。
校验工具：`scripts/40-verify-crc.py`。

结论：**刷本内核必须同时替换 vendor_boot ramdisk、vendor_dlkm、system_dlkm 的模块**。

## 2. 本地可编出的模块（336 个）

来自 `common`（GKI）+ `sm8550-modules`（oplus 驱动）+ 内核树内驱动，覆盖：

- 时钟/调压/互连/UFS/PCIe/PMIC/热管理/传感器核心（msm-kernel 内建对象）
- oplus charger / touchpanel / vibrator / device_info / dfr / dft / boot / secure
- GKI：zram、zsmalloc、kernelsu、rekernel

## 3. 缺失的 36 个关键模块（必须由 ROM 构建体系补齐）

| 模块 | 来源仓库 | 影响 |
|---|---|---|
| msm_drm、msm_kgsl | `qcom/opensource/display-drivers`、`graphics-kernel` | 显示 / GPU（缺失=黑屏） |
| msm_video、msm-eva | `qcom/opensource/video-driver`、`eva-kernel` | 视频编解码 |
| qca_cld3_kiwi_v2、cnss2、cnss_* | `qcom/opensource/wlan` | Wi-Fi |
| bt_fm_slim、btpower、radio-i2c-rtc6226-qca | `qcom/opensource/bt-kernel`、`nxp` | 蓝牙 / FM |
| 多个 *_dlkm（audio codec、lpass、swr、wcd938x） | `qcom/opensource/audio-kernel` | 音频 |
| camera | `qcom/opensource/camera-kernel` | 相机 |
| rmnet_*、ipa_clientsm、ipanetm | `qcom/opensource/dataipa`、`datarmnet` | 移动数据 |
| qcedev/qcrypto | `qcom/opensource/securemsm-kernel` | 硬件加解密 |

这些仓库**不能**用裸 kbuild 独立编译（实测 display-drivers 缺 `clk-regmap.h`），
原因是它们依赖 msm-kernel 头文件与 ROM Soong 注入的 `DISPLAY_ROOT` / `CONFIG_*` /
编译开关。

## 4. 补齐方式

在 ROM 的 AOSP 源码树中：

```bash
# kernel/oneplus/sm8550        -> 本仓库 00-fetch.sh 得到的 common 树（含本仓库补丁）
# kernel/oneplus/sm8550-modules-> 16.0 分支
# device/oneplus/sm8550-common -> 既有设备树（TARGET_KERNEL_EXT_MODULE_ROOT 指向上面两处）

source build/envsetup.sh && lunch <rom>-userdebug
m bootimage vendor_dlkmimage system_dlkmimage   # 或 make bacon
```

Soong 会按 `Android.bp` 的 `kernel_module` 定义注入 `DISPLAY_ROOT` 等参数并产出
与内核 ABI 匹配的全部模块；随后用 `scripts/30-package.sh` 同法打包即可。

## 5. 备选：保留 ROM 内核

ROM 现内核（5.15.200 + SukiSU 内置 + SUSFS）已具备 root 能力；若目标是日常稳定，
可仅使用 ROM 原内核，不替换 kernel/dlkm 分区。
