# Realme GT5 (ossi / SM8550) — ROM + Kernel 统一构建仓库

本仓库统一维护 **类原生 ROM（Project Infinity-X / ossi）** 与 **自编译内核（5.15.200）** 的
构建、打包与刷写流程，取代此前分散的 Action-Build / 5.15.180 方案。

---

## 1. 内核基线（与 ROM 内核严格对齐）

| 项 | 值 |
|---|---|
| 源码 | `himanshusaini010/kernel_oneplus_sm8550` @ `a1403aca1412`（分支 `16.0`）|
| 版本 | `5.15.200-ga1403aca1412-dirty`（`.scmversion` 锁定，与 ROM 内核 vermagic 一致）|
| 配置 | `configs/gki_defconfig.rom` —— 由 ROM 内核 Image 内嵌 IKCONFIG 提取（2461 项）|
| 叠加 | `configs/features.config`（root / 容器 / ZRAM / 网络）|
| 厂商模块 | `himanshusaini010/android_kernel_oneplus_sm8550-modules` @ `16.0` |

> 用 ROM 原始配置作基线是本仓库的核心原则：只有这样，编出的内核才与 ROM 的
> 驱动/模块生态保持一致。详见 `docs/COMPATIBILITY.md`。

## 2. 集成特性

| 层 | 内容 | 配置 |
|---|---|---|
| Root | YukiSU LKM + Kasumi（VFS 隐匿） | `CONFIG_KSU=m` |
| 注入 | Re-Kernel（tombstone 解冻，Generic Netlink） | `CONFIG_REKERNEL=y` |
| 容器 | MidAS ghost-task 补丁（`kernel/pid.c`） | — |
| 容器 | namespaces / cgroup(devices,pids,frozen,net_classid) / seccomp / binfmt_misc / fuse / overlayfs / squashfs / veth / bridge / ipset / POSIX mqueue / tmpfs ACL | `configs/features.config` |
| 内存 | ZRAM lz4kd（默认压缩器 lz4kd）+ lz4k_oplus | `CONFIG_ZRAM=m` |
| UTS | `5.15.200-ga1403aca1412-dirty`（与原厂 ROM 内核一致）| `.scmversion` |
| 符号 | 47 个内核符号导出（SELinux/BTF/kallsyms/path/VFS/syscall）| `scripts/10-patch.sh` |

## 3. 构建流水线

```bash
# 0) 前置：一个已同步的 OnePlusOSS kernel_platform（提供 build/ 与 prebuilts/）
export KP_DIR=~/gt5_kernel_ab/kernel_platform

scripts/00-fetch.sh      # 拉取 5.15.200 common + sm8550-modules，替换进 kernel_platform
scripts/10-patch.sh      # 打全部补丁、注入统一配置
scripts/20-build.sh      # 构建（产物 out200/dist：Image / Image.gz / Image.lz4 / *.ko）
scripts/30-package.sh    # 打包 boot / vendor_boot / vendor_dlkm / system_dlkm
scripts/40-verify-crc.py # 校验指定模块集与本内核的 CRC 兼容性
```

产物默认输出到 `~/gt5_infinity_workspace/kernel_deliver/`。

## 4. 刷写（重要：A/B 槽与 super 元数据）

> 教训：**先确认 `fastboot getvar current-slot` 与要刷的槽一致**；
> 错误槽位 + super 元数据重置 = 无限重启。

```bash
adb reboot bootloader                      # 或 fastboot/引导模式（音量下+电源）
fastboot getvar current-slot               # 期望 a
fastboot --set-active=a                    # 如不是 a，先切

# 物理分区（在 bootloader 模式）
fastboot flash boot        boot.img
fastboot flash init_boot   init_boot.img
fastboot flash dtbo        dtbo.img
fastboot flash vendor_boot vendor_boot.img
fastboot flash vbmeta      vbmeta.img      # ROM 的 vbmeta 已含 flags=3（关闭校验）
fastboot flash vbmeta_system vbmeta_system.img
fastboot flash vbmeta_vendor vbmeta_vendor.img

# super 元数据（在 bootloader 模式写，成功率高）
fastboot flash super super_empty.img

# 逻辑分区（fastbootd）
fastboot reboot fastboot
fastboot getvar partition-size:super       # 必须能读到，否则不要继续
fastboot flash odm odm.img
fastboot flash product product.img
fastboot flash system_ext system_ext.img
fastboot flash system system.img
fastboot flash system_dlkm system_dlkm.img
fastboot flash vendor vendor.img
fastboot flash vendor_dlkm vendor_dlkm.img
fastboot reboot
```

## 5. 目录

```
configs/  gki_defconfig.rom（ROM 原配） + features.config（叠加特性）
patches/  ghost-task-for-midas.patch（DroidSpaces/MidAS）
scripts/  00-fetch / 10-patch / 20-build / 30-package / 40-verify-crc
kernel/   AnyKernel3 模板（备用打包）
recovery/ OrangeFox 构建脚本（备用）
docs/     COMPATIBILITY.md（模块 ABI 分析与缺失清单）
```

## 6. 已知限制

本内核可编译出的 336 个模块 **不含** 显示/GPU/WiFi/蓝牙/音频/相机/移动数据
等 ex-module（`qcom/opensource/*`）。这些模块必须在 ROM 的 AOSP 构建体系中编译
（Soong 注入 `DISPLAY_ROOT` 等参数），详见 `docs/COMPATIBILITY.md` §3–§4。

在补齐 ex-module 之前，本内核**不建议**用于日常使用；ROM 自带内核
（5.15.200 + SukiSU/SUSFS）可继续正常使用。
