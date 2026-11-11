# Realme GT5 (SM8550) & OnePlus Ace 2 Pro 极客内核云端编译工程

本项目是专为 **真我 GT5（RMX3820 / RE5C33，代号 ossi / kalama，SM8550 骁龙 8 Gen 2 架构）** 与 **一加 Ace 2 Pro** 深度定制的独立内核云端编译系统。

本仓库集成 2026 最新内核级 Root、VFS 零痕迹隐匿框架与调度增强流水线，支持一键在 GitHub Actions 云端全自动编译并输出可刷入的 AnyKernel3 / Boot 刷机包。

---

## 🌟 核心特性与架构集成

1. **Root 引擎支持**：
   - **YukiSU (Rouyashiki/YukiSU)**：新一代 C++ 重构版 LKM（`CONFIG_KSU=m`），原生集成 Kagami 挂载系统与 Kasumi 隐匿规则。
   - **BakaSU**：经典内置 Inline Hook + SUSFS 架构。
   - **KernelSU-Next / GKI 纯净内核**。
2. **Kasumi VFS 零痕迹文件系统 (Rouyashiki/Kasumi)**：
   - 内核层匿名 fd + ioctl 控制平面动态路径重定向，彻底消灭 `/proc/mounts` 挂载点污染。
   - 规则按需白名单放行（`KSM_FEATURE_RULE_BYPASS`）。
3. **系统调度与崩溃防御**：
   - **DroidSpaces MidAS 防崩溃补丁 (`ghost-task-for-midas.patch`)**：彻底修复 Oplus 独占调度器与容器、Zygote 进程注入冲突导致的系统软重启与 Kernel Panic。
   - **Re-Kernel 后台加速与解冻**：Sakion-Team 专属 CPU 任务调度加速。
   - **12GB ZRAM 内存扩展**：集成 `lz4kd` 极速压缩算法。
   - **消灭死锁**：彻底关闭 `LSM_BBG`，杜绝 Baseband Guard 拦截虚拟磁盘 loop 节点导致的开机卡米死锁。
   - **UTS Uname 伪装**：自动擦除 `-lineageos` 等类原生版本后缀，伪装为高通官方纯净 GKI 签名。

---

## 🚀 如何推送本仓库到你的 GitHub

在本地终端执行以下指令，将本工程推送到你的 GitHub 账户：

```bash
cd /home/buguj/gt5_infinity_workspace/gt5_kernel_action_build

# 1. 初始化本地仓库
git init -b main
git add .
git commit -m "feat: initial commit for Realme GT5 SM8550 Kernel Action Build"

# 2. 关联你的 GitHub 远程仓库（请将下方 URL 替换为你在 GitHub 上新建的仓库地址）
# 例如: git remote add origin https://github.com/your-username/gt5-kernel-action.git
git remote add origin <YOUR_GITHUB_REPO_URL>

# 3. 推送上云
git push -u origin main
```

---

## ⚙️ 如何在 GitHub Actions 一键更新与编译内核

仓库推送到 GitHub 后，未来更新内核或更换 Root 管理器无需动用本地电脑配置，只需在网页端点击即可完成：

1. 打开你的 GitHub 仓库页面，进入 **Actions** 标签页。
2. 在左侧工作流列表中选择 **Realme GT5 & OnePlus Ace 2 Pro Kernel CI/CD**。
3. 点击右侧的 **Run workflow** 下拉按钮：
   - **Target Device**：选择 `oneplus_ace2_pro_b`（与真我 GT5 硬件基线 100% 互通）；
   - **Root & Stealth Stack Engine**：选择 `YukiSU` 或 `BakaSU`；
   - **Compile & Embed Kasumi**：勾选 `true`；
   - **DroidSpaces MidAS patch**：勾选 `true`；
   - **Re-Kernel / ZRAM**：按需开启；
   - 点击绿色的 **Run workflow** 开始运行。
4. **编译耗时与产物获取**：
   - 借助 GitHub Actions 提供的 16 核心云端环境与 Ccache 缓存，完整编译仅需约 15 ~ 25 分钟。
   - 编译完成后，在工作流详情页底部的 **Artifacts** 区域即可直接下载形如 `RealmeGT5_SM8550_YukiSU_2026xxxx.zip` 的 AnyKernel3 刷机包！

---

## 📱 刷入指引（严格保护 Slot B）

1. **Recovery / 刷机工具刷入**：
   - 将下载的 AnyKernel3 zip 包传输至手机，在 Recovery（如 TWRP / OrangeFox）中直接选择刷入。
   - 或使用已获得 Root 权限的管理器（Kernel Flasher）选择 AnyKernel3 刷入。
2. **Fastboot 刷入（如导出 boot.img）**：
   - 若提取了单独的 `boot.img`，请确保仅刷入 **Slot A**：
     ```bash
     fastboot flash boot_a boot.img
     ```
   - **严禁执行 `fastboot flash boot boot.img`**，避免误覆盖保留原厂官方系统的 Slot B。

---

## 🛠️ 目录架构说明

```
├── .github/workflows/
│   └── build-kernel.yml       # GitHub Actions 云端构建流水线配置文件
├── patches/
│   ├── ghost-task-for-midas.patch  # DroidSpaces MidAS 调度补丁
│   ├── unicode_bypass_fix_6.1-.patch # CVE-2024-43093 修复补丁
│   └── bbrv3/                 # BBRv3 网络拥塞控制算法
├── scripts/
│   ├── maximize-build-space.sh # 云端 Runner 磁盘空间最大化清理脚本
│   └── SusfsCompat.kts        # SUSFS 兼容与上下文自动化注入脚本
└── README.md                  # 本说明文档
```
