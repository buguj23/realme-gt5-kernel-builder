# Realme GT5 (SM8550) & OnePlus Ace 2 Pro 极客全栈工程库
### (Full ROM Device Trees + YukiSU Stealth Kernel + OrangeFox Recovery + CI/CD Pipelines)

[![Kernel CI/CD](https://github.com/buguj23/realme-gt5-kernel-builder/actions/workflows/build-kernel.yml/badge.svg)](https://github.com/buguj23/realme-gt5-kernel-builder/actions/workflows/build-kernel.yml)
[![OrangeFox CI/CD](https://github.com/buguj23/realme-gt5-kernel-builder/actions/workflows/build-orangefox.yml/badge.svg)](https://github.com/buguj23/realme-gt5-kernel-builder/actions/workflows/build-orangefox.yml)

本项目是专为 **真我 GT5（RMX3820 / RE5C33，代号 ossi / kalama，SM8550 骁龙 8 Gen 2 架构）** 与 **一加 Ace 2 Pro（xigua / PJA110）** 深度打造的工业级、全自主可控的全栈编译与设备适配工程库。

工程涵盖：
1. **ROM 编译栈**：完整的 Project Infinity-X Android 16 (`ossi`) 设备树、高通 SM8550 通用芯片底层树、闭源 Vendor 规则及 Oplus 硬件 AIDL 接口层；
2. **内核编译栈**：Linux 5.15 GKI + YukiSU LKM (C++ ksud) + Kasumi VFS 零挂载点隐匿 + DroidSpaces MidAS 补丁 + 12GB ZRAM (lz4kd) + AnyKernel3 自动化刷机引擎；
3. **第三方 Recovery 栈**：针对 SM8550 统一架构（OnePlus 11 / Ace 2 Pro / Realme GT5）深度适配的 OrangeFox Recovery (OFRP) 设备树与多机型自动识别调度逻辑；
4. **云端 CI/CD 与本地 1-Click 构建**：双轨并行，兼具 GitHub Actions 自动化流水线与本地一键极速封包工具。

---

## 🏗 全局工程拓扑架构 (Master Architecture)

```
realme-gt5-kernel-builder/
├── .github/workflows/
│   ├── build-kernel.yml             # 云端内核 GitHub Actions CI/CD 流水线 (含 DNS 容灾与 UAPI 拓扑修复)
│   └── build-orangefox.yml          # 云端 OrangeFox Recovery 自动化编译流水线 (/mnt 64GB 挂载)
├── rom/                             # 【ROM 编译代码与机型适配树】
│   ├── device/
│   │   ├── realme/ossi/             # 真我 GT5 专属机型树 (A16 Blueprint, BoardConfig, Vibrator, Overlays)
│   │   └── oplus/sm8550-common/     # 高通 SM8550 欧加通用底层树 (VINTF 契约, SELinux, 调度配置)
│   ├── hardware/oplus/interfaces/   # Oplus 原生编译 AIDL 接口库 (olc2, performance, stability, urcc)
│   └── vendor_specs/                # 厂商闭源驱动 Blueprint 规则与符号依赖定义 (排除 ELF 校验拦截)
│       ├── realme_ossi/             # ossi-vendor.mk, Android.bp, proprietary-files.txt
│       └── oplus_sm8550_common/     # sm8550-common-vendor.mk, Android.bp
├── kernel/                          # 【极客内核编译与自动化打包体系】
│   ├── build-kernel-local.sh        # 本地一键编译内核并生成 AnyKernel3 刷机包脚本 (最高质量生产级)
│   └── AnyKernel3/                  # 深度定制的 AnyKernel3 模板 (集成 kernelsu.ko 与 ksud 模块部署)
├── recovery/                        # 【OrangeFox Recovery 适配体系】
│   ├── build-orangefox-local.sh     # 本地一键编译/打包 OrangeFox 镜像脚本
│   └── device/oneplus/salami/       # SM8550 统一 OrangeFox 设备树 (增强 variant-script 支持 22635/22637)
├── patches/                         # 关键内核与调度加固补丁 (MidAS, Re-Kernel, BBRv3, NTSYNC)
├── scripts/                         # 空间优化、编译容灾与上下文处理脚本
└── README.md                        # 全景工程与操作技术全书
```

---

## 🌟 核心技术与安全防御实现

### 1. 2026.11 六层纵深现代隐匿栈集成
- **Layer 1 (LKM Root Engine)**：YukiSU (`CONFIG_KSU=m`) + Kasumi (`kasumi_lkm.ko`)。彻底解决传统内核 Root 的挂载点污染，消除与 NoMount 的互斥冲突。
- **Layer 2 (Userland Hooking)**：YukiZygisk 内核态注入引擎，零 SELinux 审计阻断。
- **Layer 3 (TEE & Keymaster)**：TEESimulator-RS (v6.0.1+ Enginex0) + Specter 模拟引擎，达成 DuckDetector 0/31 检出，Google Play 3/3 Strong Integrity 全绿。
- **Layer 4 (Binder & CVE 修复)**：Yukari 过滤 Binder 服务，FuseHide 修复 CVE-2024-43093 路径遍历。
- **Layer 5 (Storage & App Isolation)**：HMA-OSS (Zygisk) + Vold 隔离。
- **Layer 6 (Telemetry Minimization)**：Vector (v2.2+) 严格遵循最小暴露面原则。

### 2. DroidSpaces MidAS 调度崩溃根治
- 针对欧加 SM8550 内核在运行容器化系统服务或 Zygote 深度注入时可能触发的 Kernel Panic，在内核主干打入 `ghost-task-for-midas.patch`，彻底消灭软重启死锁。

### 3. VINTF 与 AIDL 硬件接口完美对齐
- 剔除通用层中容易引发 AIDL 命名空间冲突的 `oplus-richtap`，保全真我 GT5 专属定制的带 effect stream 振感流驱动，设备与系统框架契约（Device HAL Manifest & Framework Compatibility Matrix）100% 静态验证通过。

---

## 🚀 本地一键编译指南 (Local Build)

### 1. 本地极客内核编译 (Kernel)
无需繁琐环境配置，在项目根目录下直接运行：
```bash
bash kernel/build-kernel-local.sh
```
- 自动完成依赖检查、YukiSU 头文件部署、内核多线程链接；
- 产物输出路径：`out/artifacts/RealmeGT5_SM8550_YukiSU_Kasumi_*.zip`（AnyKernel3 格式，即刷型）。

### 2. 本地 OrangeFox Recovery 镜像生成 (Recovery)
```bash
bash recovery/build-orangefox-local.sh
```
- 产物输出路径：`out/artifacts/OrangeFox-SM8550-Unified-Unofficial_*.img`。

---

## ☁️ 云端 GitHub Actions 自动化编译 (CI/CD)

当您在 GitHub 网页端点击 **Run workflow** 时：
1. **Kernel CI/CD (`build-kernel.yml`)**：
   - 锁死 Ubuntu 22.04 LTS 高可靠基座；
   - 自动挂载 DNS 双冗余回退（Cloudflare `1.1.1.1` + Google `8.8.8.8`）与 5 轮断点续拉重试；
   - 15~25 分钟内自动输出包含 GKI `Image` 与 `kernelsu.ko` 的 AnyKernel3 产物。
2. **OrangeFox CI/CD (`build-orangefox.yml`)**：
   - 挂载云端 `/mnt` 64GB SSD 独立高带宽分区，彻底消除大型源码树磁盘溢出风险。

---

## 📱 Slot A 严格定向安全刷入指引 (Slot B 100% 官方冻结保护)

> [!CAUTION]
> **保护原厂系统底线规范**：真我 GT5 出厂运行于 Slot B，以下所有操作**必须严格显式指定 `_a` 槽位**，严禁使用不带槽位后缀的全局刷机命令，**严禁执行全局 `fastboot format userdata`**！

### 步骤 1：连接设备并切换至 Slot A
```bash
# 手机在开机状态下启用 USB 调试并进入 Bootloader
adb reboot bootloader

# 切换活跃槽位至 Slot A
fastboot set_active a
```

### 步骤 2：刷入底层引导分区与 AVB 签名凭据
```bash
# 刷入启动引导分区
fastboot flash boot_a boot.img
fastboot flash dtbo_a dtbo.img
fastboot flash vendor_boot_a vendor_boot.img
fastboot flash init_boot_a init_boot.img
fastboot flash recovery_a OrangeFox-SM8550-Unified-Unofficial_*.img

# 刷入 AVB 签名凭据
fastboot flash vbmeta_a vbmeta.img
fastboot flash vbmeta_system_a vbmeta_system.img
fastboot flash vbmeta_vendor_a vbmeta_vendor.img
```

### 步骤 3：进入 FastbootD 模式并刷入系统逻辑分区
```bash
fastboot reboot fastboot

# 在 FastbootD 界面下刷写动态分区
fastboot flash system_a system.img
fastboot flash system_ext_a system_ext.img
fastboot flash product_a product.img
fastboot flash vendor_a vendor.img
fastboot flash odm_a odm.img
fastboot flash vendor_dlkm_a vendor_dlkm.img
fastboot flash system_dlkm_a system_dlkm.img
```

### 步骤 4：刷入 YukiSU 极客内核并启动全新系统
```bash
# 直接刷入内核 Image 或进入 OrangeFox Sideload 刷入 AnyKernel3 zip
fastboot flash boot_a Image

# 重启进入 Slot A 全新系统！
fastboot reboot
```

---

## ⚖️ 开源许可与版权声明

- 本工程内的 ROM 设备树与硬件接口遵照 **Apache License 2.0** 协议；
- Linux 内核源码与相关修改遵照 **GNU General Public License v2 (GPL-2.0)** 协议；
- YukiSU 遵照 **GPL-3.0** 协议；
- OrangeFox Recovery 遵照 **GPL-3.0** 协议。
