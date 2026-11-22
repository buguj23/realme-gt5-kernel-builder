# Realme GT5 (`ossi` / `5.15.149`) 全链路构建、排障、无损实测与发布实战手册

本文档完整沉淀 **Realme GT5 150W（`RMX3820` / `RE5C33` / `ossi`，ColorOS `15.0.0.320(CN01)`）** 从 **OEM OGKI 5.15.149 内核**、**Project Infinity-X 2.9 (Android 15) 完整类原生 ROM**、**Treble GSI (DSU)**、**YukiSU LKM** 到 **云端缓存与 GitHub Releases 自动化发布** 的实机验证经验、不同构建方式对比、完整踩坑根因修复以及真机零风险分层测试 SOP。

---

## 1. 实机验证基线与交付总览

### 1.1 锁定基线（已 100% 实机跑通）

| 项目 | 实测验证值 |
|---|---|
| 目标机型与代号 | Realme GT5 150W (`RMX3820` / `RE5C33` / `ossi`，Snapdragon 8 Gen 2 / SM8550) |
| 原厂底包基线 | ColorOS `RMX3820_15.0.0.320(CN01)`（Android 15 / API 35，Boot SPL `2024-11-05`） |
| 原厂 `payload_metadata.bin` SHA-256 | `3FQtS2u21MJg0xzEH5sM5u7KxPaoFK0EKeqqmza5V60=`（Virtual-A/B） |
| 内核源码与清单 | [`DestoryG/kernel_manifest`](https://github.com/DestoryG/kernel_manifest) (`realme/sm8550` / `realme_gt5_v.xml`) + `realme-kernel-opensource/realme_GT5-AndroidV-*` |
| 编译工具链 | Hermetic Clang `r450784e` (`14.0.7`) |
| 内核 KMI / CRC 对齐 | `android13-5.15` (gen `8`)，`module_layout = 0x0222dd63`，**`3260 / 3260` 原厂模块符号 100% 匹配** |
| 动态分区与文件系统 | `qti_dynamic_partitions` (`14491320320` B)，共 25 个 A/B 分区（17 动态分区含 10 个原厂 `my_*` + 8 引导/验证分区）；`/metadata = f2fs`，`vendor_dlkm`/`system_dlkm = ext4`，`vendor`/`odm`/`my_* = erofs` |
| Root 路线 | `Pure-OGKI`（零内置 Root）或同树编译 `YukiSU-LKM`（`CONFIG_KSU=m`，严禁 `CONFIG_KSU=y` / `SUSFS` / `KPM` / `FakeConfig`） |

### 1.2 真机实测成绩单（全程 Enforcing SELinux，0 分区刷写损坏）

1. **自编 `Pure-OGKI` 内核 (`5.15.149-o-gb285e01d0605`) + 原厂 ColorOS `15.0.0.320`**（`fastboot boot`）：
   - 49 秒亮屏进桌面，**518 / 518** 原厂内核模块加载正常，144Hz/HDR、触控、震动、音频、Wi-Fi、蓝牙、NFC、5 颗相机、35/35 传感器、指纹、充电全部正常。
2. **修复版 `Infinity-X 2.9 Treble GSI`（DSU-Sideloader-Plus）**：
   - **纯 Enforcing SELinux（无需宽容内核）**一把亮屏进桌面，持续稳跑 **55+ 分钟（3320 秒）**，完胜原厂 ColorOS 250 秒 Phoenix 开机看门狗；`1240×2772` 四档 `60/90/120/144Hz` + HDR10/HLG/HDR10+、`35/35` 传感器、双卡 5G NR_SA/IMS/Wi-Fi/BT/NFC/音频/马达/快充 HAL 全部在线。
3. **自编 `Pure-OGKI` 内核 + `Infinity-X 2.9` DSU 零刷写合体**（Sticky DSU + `fastboot boot`）：
   - `uname = 5.15.149-o-gb285e01d0605`，**518 / 518** 模块全加载，**35 / 35** 传感器全在线，`SELinux = Enforcing`，**`avc: denied = 0`**，`boot_completed = 1`。
4. **`YukiSU v1.9.0 DirectLKM` + `Infinity-X 2.9` DSU 零刷写合体**（Sticky DSU + `fastboot boot`）：
   - `518 / 518` 模块全加载，`Enforcing`，`avc = 0`；`org.rouyashiki.yukisu` 在 DSU 独立 `/data/adb` 自动同步 `/data/adb/ksud`（`isSuccess=true`），驱动通信与 `yukizygisk` 初始化正常，完全隔离不污染原厂 ColorOS `/data/adb`。

### 1.3 云端 Releases 矩阵（4 个独立 Release 各司其职）

| Release Tag | 用途 | 核心内容 |
|---|---|---|
| `kernel-5.15.149-pure-ogki-gt5` | 独立内核发布 | `gt5-5.15.149-pure-ogki-boot.img`（可直接 `fastboot boot`）、`gt5-5.15.149-pure-ogki-package.tar.zst`（含 `Image` + `Module.symvers` + `zram/zsmalloc.ko`）、`manifest.json`、`SHA256SUMS.txt` |
| `infinity-x-2.9-ossi-5.15.149` | 完整类原生 A/B OTA ROM | `infinity_ossi-ota.zip.part-00..03`（`1900 MiB` 分卷，通过完整 AVB/CMS/`delta_generator`/`TrieBuilder`/Phoenix 门禁）、`rom-delivery.json`、`source-manifest.xml`、`SHA256SUMS.txt` |
| `infinity-x-2.9-gsi-arm64-dsu` | DSU 无损体验 GSI | `Infinity-X-2.9-gsi_arm64-ab.img.gz`（含 `property_contexts` 去冲突 + `/proc/phoenix` 喂狗与 Enforcing SELinux 策略）、`gsi-verify.txt`、`SHA256SUMS.txt` |
| `rom-cache-5.15.149-infinity` | 三层流式构建缓存 | Tier 1 (`host-meta`, 2 卷) / Tier 2 (`target`, 4 卷) / Tier 3 (`soong-intermediates`, 12 卷) + `rom-cache-manifest.json` + `SHA256SUMS.txt`（共 ~31.6 GB，供增量构建/低内存提取 OTA 工具/CI 恢复） |

---

## 2. 六种构建与交付方式对比（按场景选型）

| 方式 | 适用场景 | 内存/磁盘需求 | 典型耗时 | 入口脚本 / Workflow |
|---|---|---|---|---|
| **方式 A：独立编译 OGKI / YukiSU-LKM 内核** | 单独调内核、更新 KMI 内核或编同树 `kernelsu.ko` | 8–16 GB RAM / ~35 GB 磁盘 | 15–35 分钟 | `kernel/build-kernel-local.sh` / `.github/workflows/build-kernel-gt5.yml` |
| **方式 B：全量编译 `infinity_ossi` 完整 ROM** | 从零构建完整可刷 A/B OTA 包（含 25 个分区与全链 AVB） | 16 GB RAM (+ 32–48 GB Swap) / ~260 GB 磁盘 | 首次 4–6 小时；带缓存 30–60 分钟 | `scripts/rom-build-local.sh` / `.github/workflows/build-infinity-rom.yml` |
| **方式 C：独立编译 `Treble GSI arm64-ab` (DSU)** | 无损在原厂 ColorOS 上验证上层框架、UI、SELinux 与外设 HAL | 16 GB RAM / ~220 GB 磁盘（复用同源码树仅增 ~30 GB） | ~45–90 分钟 | `scripts/rom-build-gsi.sh` / `.github/workflows/build-infinity-gsi.yml` |
| **方式 D：低内存零 Soong 官方 `releasetools` 增量热修** | 只改 `.rc` / `property_contexts` / `vendor_sepolicy.cil` / `precompiled_sepolicy`，不想重跑 16 GB Soong | **< 2.5 GB RAM** / ~50 GB 临时磁盘 | GSI ~2 分钟；完整 ROM ~35–50 分钟 | `secilc` + `build_image` / `add_img_to_target_files` + `ota_from_target_files` + `scripts/rom-verify-delivery.py` |
| **方式 E：云端分层构建缓存加速 / 抢占实例续编** | 云端抢占机或换机增量编译，避免重头编译 6 小时 | 按层按需拉取（Tier 1 仅 2.9 GB；全套 31.6 GB） | 恢复 5–20 分钟 | `scripts/rom-cache-sync.py` (`upload` / `restore`) |
| **方式 F：GitHub Actions 自托管 + 托管混合 CI** | 一键云端触发、国内镜像加速、自动归档与状态监控 | `self-hosted`（默认 CN 镜像）或 `ubuntu-latest` | 视 Runner 规格 | 见第 5 章 Workflow 总表 |

### 2.1 方式 A：内核构建（Pure-OGKI 与 YukiSU-LKM）

```bash
# 1. 拉取 realme_gt5_v 原厂 OGKI 源码与工具链（支持国内镜像自动探测与断点续传）
MIRROR_MODE=cn scripts/00-fetch.sh

# 2. 应用 KMI 安全补丁（自动拦截 SUSFS/KPM/FakeConfig）
scripts/10-patch.sh

# 3a. Pure-OGKI 模式（零内置 Root，推荐作为完整 ROM 底座与官方 LKM 宿主）
KSU_MODE=Pure-OGKI scripts/20-build.sh
scripts/30-package.sh

# 3b. 或 YukiSU-LKM 模式（同树 out-of-tree CONFIG_KSU=m + check_symbol 校验）
KSU_MODE=YukiSU-LKM ENABLE_YUKIZYGISK=1 scripts/20-build.sh
scripts/30-package.sh

# 4. 离线验证 3260/3260 原厂模块符号 CRC
python3 scripts/40-verify-crc.py "$HOME/gt5_kernel_5_15_149/kernel_platform/common/out/Module.symvers" /path/to/stock_modules
```

- **单步本地封装**：`kernel/build-kernel-local.sh --fetch --patch --mode Pure-OGKI`（或 `--mode YukiSU-LKM`）。
- **`OGKI_BUILD_MODE` 两种内核对接 ROM 模式**（`BoardConfigOgki.mk`）：
  - `prebuilt`（默认推荐）：直接消费 schema-2 `kernel-package.tar.zst`，由 `scripts/rom-stage-kernel.py` 自动完成 KMI 校验、原厂 DTB `dtb[1..4]` 禁用旧 DT fstab 节点并生成 `prebuilt/kernel-modules.mk`。
  - `inline`：在 ROM 源码树内联编译 `kernel/oneplus/sm8550` + 25 组树外模块（强制零 `CONFIG_KSU`）。

### 2.2 方式 B：完整 `infinity_ossi` ROM 构建

```bash
# 0. 安装宿主机依赖（自动探测国内最快 APT 镜像）
sudo bash scripts/setup-cn-runner.sh --with-rom-deps

# 1. 拉取已校验的 RMX3820_15.0.0.320 原厂基线镜像
scripts/fetch-stock.sh --mode full

# 2. 预检（不编译，先校验 stock payload / DTB / DTBO / OEM 公钥 / LP 布局 / 内核 KMI）
scripts/rom-build-local.sh --check-only \
  --src /mnt/rom-src --branch 5.15.149 \
  --pkg /mnt/kernel/Pure-OGKI --stock-images /mnt/stock_15.0.0.320

# 3. 同步源码、补丁、提取闭源、编译并执行 rom-verify-delivery.py 全项加密与运行时门禁校验
MIRROR_MODE=cn scripts/rom-build-local.sh --sync \
  --src /mnt/rom-src --branch 5.15.149 \
  --pkg /mnt/kernel/Pure-OGKI --stock-images /mnt/stock_15.0.0.320
```

> **16 GiB 内存宿主机关键经验**：
> 1. **禁止在含中文或空格路径直接跑 Soong/Kati**：用 `sudo unshare -m --propagation private` 把工作目录 `mount --bind` 到纯 ASCII 路径（如 `/mnt`），再用 `setpriv` 降回普通用户运行，彻底零路径污染。
> 2. **把 `OUT_DIR` / `DIST_DIR` / `OSSI_AVB_KEY` 保持在源码树相对路径，把 workdir/backup 放在源码树外**（见 commit `de27820`、`2af9688`、`400b214`、`95da0d6`）。
> 3. **16 GiB RAM + 32–48 GiB 临时 Swap 文件**：Soong 解析阶段峰值可达 ~16–24 GiB；使用脚本内 `SOONG_MAX_JOBS` / `JAVAC` 堆限制 + 临时 swapfile 可稳过链接峰值，构建完成后立刻 `swapoff` 删除临时 swap 并恢复系统原 VM/调度参数。

### 2.3 方式 C：独立构建 `Treble GSI arm64-ab`（DSU 无损验证）

```bash
# 复用已完成 repo sync 的 Infinity-X 源码树构建官方 Treble GSI，自动应用：
# 1) scripts/rom-patch-source.py 清理 system_ext_property_contexts 的 ro.vendor.dolby.dax.version 冲突
# 2) 注入 init.gsi.rc /proc/phoenix 250s 看门狗喂狗 + system_ext_sepolicy.cil Enforcing 写权限
# 3) 自动重算 system_ext_sepolicy_and_mapping.sha256 并通过 e2fsck / debugfs / TrieBuilder / secilc 门禁校验
scripts/rom-build-gsi.sh \
  --src /mnt/rom-src \
  --out-dir out/gsi \
  --delivery-dir /mnt/dsu-delivery \
  --stock-vendor-selinux /path/to/stock_vendor_selinux
```

云端一键触发：运行 `.github/workflows/build-infinity-gsi.yml`（支持从 Release 缓存恢复、自动压缩 `.img.gz`、生成 `gsi-verify.txt` 与 `SHA256SUMS.txt`）。

### 2.4 方式 D：低内存零 Soong 增量热修复重打包（实测仅 < 2.5 GiB RAM）

当你只需要修正 `init.*.rc`、`*_property_contexts`、`*_sepolicy.cil` 或 `precompiled_sepolicy` 时，**完全不需要启动 16 GiB 内存的 Soong**：

1. **提取官方 host OTA 工具**：直接从 `out/host/linux-x86` 或云端缓存 `tier1-host-meta` 流式解出 `secilc`、`build_image`、`add_img_to_target_files`、`ota_from_target_files`、`delta_generator`、`avbtool`、`mkfs.erofs`、`mke2fs`、`e2fsdroid`、`signapk.jar` 与 `lib64/`。
   - **SONAME 补齐技巧**：若 `.so` 从 `obj/SHARED_LIBRARIES/*_intermediates/` 抽出，用 `readelf -d` 扫描 SONAME，自动创建 `libssl.so -> libssl-host.so`、`libevent.so -> libevent-host.so`、`libcrypto.so -> libcrypto-host.so`、`libz.so -> libz-host.so` 等软链，1 秒补齐全部动态依赖。
2. **GSI 极速重打包（~2 分钟，< 300 MB RAM）**：
   - 修改 `system/system/system_ext/etc/{init/init.gsi.rc,selinux/system_ext_property_contexts,selinux/system_ext_sepolicy.cil}`，更新 `system_ext_sepolicy_and_mapping.sha256`；
   - 用实机/原厂 `/vendor/etc/selinux` 跑运行时同参 `secilc -m -M true -G -N -c 30` 验证通过；
   - 用官方 `build_image`（注意输出文件基名必须为 `system.img` 以匹配挂载点推断）+ `simg2img` + `e2fsck -fn` + `gzip -6` 打包交付。
3. **完整 `infinity_ossi` ROM 增量重打包（~35–50 分钟，稳在 1.7 GiB RAM）**：
   - 解压 `target_files` 务必带 **`UNZIP_DISABLE_ZIPBOMB_DETECTION=TRUE`**（Info-ZIP 对 17 GiB ZIP64 会误报 zip bomb）；
   - 修改 `VENDOR/etc/init/init.ossi.rc`、`SYSTEM_EXT/etc/selinux/system_ext_property_contexts`、`VENDOR/etc/selinux/vendor_sepolicy.cil`，用 `secilc -m -M true -G -N -c 30` 重编 `ODM/etc/selinux/precompiled_sepolicy`；
   - 删除旧 `IMAGES/{vendor,odm,system_ext,vbmeta*}.img` 与 `META/{care_map.pb,vbmeta_digest.txt}`，临时将 `META/misc_info.txt` 中的 `*_selinux_fc` 指向 `META/file_contexts.bin`，运行 `add_img_to_target_files -a -v` 重建镜像与完整 AVB 链后还原 `misc_info.txt`；
   - **关键防爆内存参数**：
     - **`export TMPDIR=/nvme/path/tmpdir`**（绝不要用默认的内存 `tmpfs` `/tmp`，否则 17 GiB `target_files` 解压直接 `ENOSPC` + 撑爆 Swap！）；
     - **`ota_from_target_files -t 2 --max_threads=2`**（默认 `delta_generator` 会开 25 分区 × 32 线程 = 347 线程吃掉 8 GiB 内存；限制 `--max_threads=2` + 可选 `systemd-run --property=AllowedCPUs=28-31` 仅占能效核与 1.7 GiB 内存！）；
   - 最后执行 `python3 scripts/rom-verify-delivery.py` 通过全项签名、AVB、`TrieBuilder` 与 Phoenix 门禁校验。

### 2.5 方式 E：云端三层构建缓存同步（`scripts/rom-cache-sync.py`）

为突破 GitHub 单附件 `2 GiB` 上限并适配国内网络/抢占实例：
- **三层拆分**：
  - `tier1-host-meta`（~2.9 GB）：宿主机编译工具与构建元数据，增量重打包/CI 必拉；
  - `tier2-target`（~6.1 GB）：`ossi` 目标分区中间产物；
  - `tier3-soong-intermediates`（~22.6 GB）：Soong 编译对象缓存。
- **流式分卷与校验**：边 `tar --zstd` 边按 `1900 MiB` 切卷并流式计算整包与分卷 SHA-256，支持 `upload` 断点续传与 `restore --tiers tier1,tier2` 按需恢复。

---

## 3. 全流程踩坑与根因修复大全

### 3.1 真机运行时两大致命坑（DSU 掉用户态 Recovery 深度复盘）

#### 坑 1：DSU 开机 ~1.02 秒直接掉进用户态 Recovery（**不是 SELinux 拦截，刷宽容内核也必死！**）
- **现象**：DSU-Sideloader-Plus 安装 GSI 后重启，既不亮开机动画，也不写 `fs_mgr_log` 和 `/metadata/vold/metadata_encryption/dsu/dsu`，每次都秒进用户态 Recovery。
- **排查实证**：
  1. 从实机提取原厂 `/vendor/etc/selinux/*` + `/odm/etc/selinux/*` 与 GSI `plat_sepolicy` 运行同参 `secilc -m -M true -G -N -c 30` —— **直接通过（exit 0）**，排除 SEPolicy 编译失败。
  2. 对 GSI 与原厂合并后的全套 `*_property_contexts` 执行 AOSP `TrieBuilder::AddToTrie()` 校验，100% 锁定冲突键：
     - GSI `system_ext_property_contexts:41`（源自 Lineage `device/lineage/sepolicy/common/private/property_contexts:14`）：
       `ro.vendor.dolby.dax.version  u:object_r:exported_system_prop:s0`
     - 原厂 ColorOS `15.0.0.320` `/vendor/etc/selinux/vendor_property_contexts:177`：
       `ro.vendor.dolby.dax.version  u:object_r:vendor_oplus_prop:s0`
  3. **致命链路**：Android `second_stage_init` 在早于挂载 `/data` 的 `PropertyInit()` 阶段调用 `TrieBuilder::AddToTrie()`，遇到重复前缀立即返回错误 `Duplicate prefix match detected for 'ro.vendor.dolby.dax.version'` → `/dev/__properties__/property_info` 创建失败 → `init` (PID 1) 执行 `LOG(FATAL) << "Failed to load serialized property info file"` 直接崩溃重启进 Recovery。**此崩溃发生在用户态属性树初始化，与 SELinux Enforcing/Permissive 完全无关。**
- **永久修复与门禁**（commit `e6e0aed`）：
  - `scripts/rom-patch-source.py` 在源码期移除 `device/lineage/sepolicy/common/private/property_contexts` 中的 `ro.vendor.dolby.dax.version`；
  - `scripts/rom-build-gsi.sh` 额外剔除 `system_ext_property_contexts` 中全部 `ro.vendor.*` / `vendor.*` / `persist.vendor.*` / `ro.odm.*` 越界声明；
  - `scripts/rom-verify-delivery.py` 新增 `check_property_contexts()` 精确模拟 `TrieBuilder::AddToTrie()`，构建交付期零容忍拦截。

#### 坑 2：ColorOS `oplus_phoenix.ko` 250 秒开机看门狗 + Enforcing 下 `init` 无法写 `/proc/phoenix`
- **现象与隐患**：GT5 Bootloader 强制传递内核参数 `phx_rus_conf.main_on=1 phx_rus_conf.recovery_method=2 phx_rus_conf.kernel_time=240 phx_rus_conf.android_time=250`，且 `vendor_boot` 在原厂与完整类原生 ROM 中都会加载 `oplus_phoenix.ko`。若 250 秒内未向 `/proc/phoenix` 写入 `SET_BOOTSTAGE@ANDROID_BOOT_COMPLETED`，内核看门狗会把正常系统强行踢回 Recovery！
- **更隐蔽的二级坑**：原厂 ColorOS 把 `proc_phoenix` 标签定义在 `system_ext_sepolicy.cil` 而非 `vendor_sepolicy.cil`。换用 AOSP/Infinity-X 上层后，`/proc/phoenix` 退化为默认 `proc` 类型，而 AOSP `plat_sepolicy.cil` 只给 `init` 授予 `proc` 的读权限（无 `write`），导致 Enforcing 模式下 `init.rc` 里写的 `write /proc/phoenix ...` 会被静默拒绝！
- **永久修复与门禁**（commit `e6e0aed`）：
  - 完整 ROM：`rom/device/realme/ossi/init.ossi.rc` 在 `post-fs` 与 `sys.boot_completed=1` 依次写入 `SET_BOOTSTAGE@NATIVE_INIT_POST_FS`、`SET_BOOTSTAGE@ANDROID_BOOT_COMPLETED`、`SET_BOOTSTAGE@PHOENIX_BOOT_COMPLETED`；并在 `rom/device/realme/ossi/sepolicy/vendor/{file.te,genfs_contexts,init.te,vendor_init.te}` 定义 `vendor_proc_phoenix`、`genfscon proc /phoenix` 与 `init`/`vendor_init` 写权限；
  - Treble GSI：`scripts/rom-build-gsi.sh` 在 `init.gsi.rc` 与 `system_ext_sepolicy.cil` 注入等效喂狗与 `proc_phoenix` Enforcing 写权限并重算 sha256 sidecar；
  - 门禁：`scripts/rom-verify-delivery.py` 新增 `check_target_files_runtime_guards()`，只要 `VENDOR_BOOT` 加载 `oplus_phoenix.ko` 就强制校验 `.rc` 喂狗与 `.cil` `genfscon` + `allow init ... write` 全部齐全。

### 3.2 内核与 KMI 排障速查

| 问题 | 根因 | 解决方案 |
|---|---|---|
| 刷入后无法开机或 0 模块加载（`FirstStageMain: Failed to load kernel modules`） | 误用 `oneplus_ace2_pro_v` 源码清单导致 `module_layout = 0xbb266e1e`，与原厂 `0x0222dd63` 不一致 | 严格使用 `DestoryG/kernel_manifest` `realme_gt5_v.xml` + Hermetic Clang `r450784e`，并用 `scripts/40-verify-crc.py` 验满 `3260/3260` |
| `system_dlkm` 模块冲突 | 构建产物包含被黑名单或与 `vendor_boot` 重复的模块 | 遵循 `system_dlkm` blocklist（仅保留 `zram.ko`、`zsmalloc.ko`；commit `b3e0d6f`） |
| KSU 内核破坏 KMI 或与模块冲突 | 启用 `CONFIG_KSU=y` / `SUSFS` / `KPM` / `FakeConfig` 改动核心结构体 | 严禁上述选项；统一采用 `Pure-OGKI` 或同树 `CONFIG_KSU=m` `YukiSU-LKM` + `tools/check_symbol` 校验 |

### 3.3 Project Infinity-X 15 / Soong / Kati 源码编译排障速查

| 阶段 | 典型报错 / 症状 | 根因与修复（含对应 Commit） |
|---|---|---|
| 源码同步 | `repo sync` 失败重试后疯狂下载数十 GB | `repo` 重试丢失 `--depth=1` 触发 unshallow → 增加重试深度保护（`af26bdc`、`bc7db97`） |
| 源码同步 | 国内直连 AOSP / GitHub `codeload` 卡死或 pack-gen 超时 | `scripts/mirror_helper.py` 自动探测 TUNA/BFSU/USTC/NJU 等国内镜像、600s pack-gen 窗口与本地代理隧道回退（`95b378a`） |
| 编译环境 | 非 ASCII / 含空格目录导致 Kati/Soong 失败 | `unshare -m` 绑定挂载源码目录至 `/mnt`，并确保 `OUT_DIR`/`DIST_DIR`/`OSSI_AVB_KEY`/`KERNEL_BUILD_OUT_PREFIX` 为相对路径且 workdir 在源码树外（`de27820`、`2af9688`、`400b214`、`95da0d6`） |
| 编译壳层 | 管道工具偶发异常退出、冷 ccache 显著降速 | 恢复 `SIGPIPE` 默认处理并跳过空/冷 ccache（`4b588a5`） |
| UAPI 头文件 | QCOM 音频/显示模块找不到内核 UAPI 头 | 自动拉取配置 `kernel/oneplus/sm8550-modules` 并修正音频内联头路径（`ff4abc0`、`46ad807`） |
| Lineage → Infinity-X 桥接 | Telephony/bootenv/马达/人脸/HIDL/XML/VINTF 冲突 | ① 桥接 Telephony shell/modem 检查（`cb9c4a7`）；② `vendor_process_bootenv` 桥接至 `vendor_load_properties`（`cce9e6f`）；③ `oplus-richtap` 对接原厂 `libaacvibrator`（`dc8515c`）；④ `face@1.0-service` `Trim@LIBBINDER` shim 并移除冗余 `virtual_device.camera`（`5b08ca3`）；⑤ 注册 `transmessage@1.0` HIDL（`1de6388`）；⑥ 合并 `vendor-oplus-hardware-cryptoeng.xml` 重复 `<permissions>` 标签（`95ccb85`）；⑦ 补齐 OPLUS VINTF 矩阵并调整 `BoardConfig.mk` 在 `common.mk` 之后追加（`c247a8d`、`ab1ae2a`） |
| OTA 校验 | `pre-device` 含逗号分隔多机型名导致验签脚本误拒 | 兼容 `,` 与 `\|` 分隔的 `pre-device` 断言（`de74665`） |
| 云端上传 | `gh release upload` 经代理上传 1.9 GB 大分卷 ~30 分钟后报 HTTP/2 `EOF`；`curl --data-binary` 吃掉 3 GB 内存 | 改用 `curl --http1.1 --upload-file --connect-timeout 30 --speed-time 90 --speed-limit 10240` 流式上传，内存恒定 ~30 MB，失败自动清理远端残片并最多重试 12 次 |

### 3.4 真机零风险 DSU 体检提前挖出的 3 个待优化适配点

在完全不擦物理 `/data` 的 DSU 实测阶段，通过 `adb shell` + `dumpsys` + `logcat` 提前锁定了以下 3 个上层适配细节（方便在真刷完整 ROM 前持续完善）：

1. **屏下指纹在设置中未显示（已定位根因）**：
   - OPLUS 指纹 AIDL HAL `android.hardware.biometrics.fingerprint.IFingerprint/default` 已正常运行，但 `pm list features` 缺少 `android.hardware.fingerprint`（原厂声明放在 `/my_product/etc/permissions/`，AOSP `SystemServer` 报 `Fingerprint configuration exists, but FingerprintService is null`）。
   - **修复方向**：在 `device/realme/ossi/device.mk` 增加拷贝 `frameworks/native/data/etc/android.hardware.fingerprint.xml:$(TARGET_COPY_OUT_VENDOR)/etc/permissions/android.hardware.fingerprint.xml`。
2. **相机关闭偶发 HAL Scudo 崩溃重启**：
   - 前后摄均可正常打开拍照，但退出 Lineage Aperture 相机时，原厂 `com.qti.chi.override.so` (`ChiFeature2Base::DestroyFeatureData`) 偶发触发 `Scudo ERROR: invalid chunk state when deallocating`（`vendor.qti.camera.provider-service_64` SIGABRT 后自动重启），属 OPLUS CamX 闭源库与 AOSP 严格 Scudo 内存校验的兼容现象。
3. **自动亮度未启用（`mAutoBrightnessAvailable=false`）**：
   - 环境光传感器（`android.sensor.light`）正常在线，但缺少 GT5 屏幕自动亮度 lux/nits 映射曲线 overlay（`config_autoBrightnessLevels` / `config_autoBrightnessDisplayValuesNits`），可从原厂 `my_product` 资源提取补入 `device/realme/ossi/overlay/`。

---

## 4. 真机零风险分层实测 SOP 与正式刷机防砖红线

在正式格式化 `/data` 刷入完整 `infinity_ossi-ota.zip` 之前，按以下 **5 步逐层拆解验证**，把 90% 的硬件与启动风险消灭在 **0 分区改动** 阶段：

### Step 1：原厂系统下 0 刷写单测自编 `Pure-OGKI` 内核
```bash
adb reboot bootloader
fastboot boot gt5-5.15.149-pure-ogki-boot.img
```
- 验收：`uname -r` 为自编版本、`/proc/modules` 满载 `518` 个模块、全外设与指纹/相机/快充正常；重启即恢复原内核。

### Step 2：原厂系统下用 DSU-Sideloader-Plus 0 风险单测 `Infinity-X 2.9` 框架
1. 下载 `Infinity-X-2.9-gsi_arm64-ab.img.gz`，在 DSU-Sideloader-Plus 分配 `16 GB` 数据空间一键安装并重启进入 DSU。
2. 验收：确认 `getenforce = Enforcing`、持续运行超过 **250 秒（4 分 10 秒）** 不掉 Recovery；通过 ADB 全面体检外设 HAL 与 `logcat` 里的 `avc: denied` / 崩溃日志。

### Step 3：Sticky DSU + `fastboot boot` 0 刷写合测「自编内核 + 自编框架」
```bash
# 1. 在 DSU 内开启常驻（Sticky）模式，防止进 bootloader 后退出 DSU
adb shell gsi_tool enable
adb shell gsi_tool status   # 确认输出 running / installed / enabled

# 2. 进 Fastboot 无损内存引导自编 Pure-OGKI 内核进 Sticky DSU
adb reboot bootloader
fastboot boot gt5-5.15.149-pure-ogki-boot.img
```
- 验收：同时确认 `uname -r = 5.15.149-o-gb285e01d0605` + `gsi_tool status = running` + `518/518` 模块 + `35/35` 传感器 + `Enforcing` + `avc: denied = 0`。

### Step 4：Sticky DSU + `fastboot boot` 0 刷写实测 `YukiSU DirectLKM`（隔离 `/data/adb`）
> **关键避坑**：
> - 严禁在物理 `boot_b` 仍是其他 KSU（如 ReSukiSU）时再刷 YukiSU 的 `init_boot_b`（两套 KSU 叠罗汉必冲突）；用 `fastboot boot` 引导干净内核封装的 `DirectLKM` 镜像即可完全绕开物理 `boot_b`！
> - `userdebug` GSI 自带 `/system/xbin/su`，测 Root/模块/YukiZygisk 没问题，但不要用它评估反 Root 隐藏检测。

```bash
# 1. 在隔离 DSU 内安装 YukiSU Manager（仅写入 DSU 独立 /data，不碰原厂 ColorOS）
adb install YukiSU_v1.9.0_10745-arm64-v8a-release.apk
adb shell gsi_tool enable

# 2. 无损内存引导 DirectLKM boot 进入 Sticky DSU
adb reboot bootloader
fastboot boot yukisu_v1.9.0_gt5_15.0.0.320_directlkm_boot.img
```
- 验收：打开 YukiSU Manager 确认自动同步 `/data/adb/ksud` 且驱动正常，在独立 `/data/adb` 内测试 `YukiZygisk` 等模块；测完执行 `adb shell gsi_tool disable && adb reboot` 秒回原厂 ColorOS。

### Step 5：独立验证自编 `recovery.img`（高通 SM8550 ABL 机制实证）
- **实机验证结论**：GT5 为 Android 13+ GKI 独立 `init_boot` + 独立 `recovery` 架构，高通 ABL 的 `fastboot boot` 仅加载内核并强制走 `init_boot` 进正常系统，**不支持通过 `fastboot boot` 引导 Recovery ramdisk**。
- **2 秒可逆安全测法**：从 `infinity_ossi-target_files-android-build.zip` 提取 `IMAGES/recovery.img`，仅单刷当前槽位 `recovery`（不碰 `boot`/`init_boot`/`super`/`/data`）：
  ```bash
  fastboot flash recovery_b infinity-ossi-recovery.img
  fastboot reboot recovery
  # 确认亮屏、触控/音量键、ADB、/metadata 与 super 识别正常；如需还原原厂：
  fastboot flash recovery_b stock_15.0.0.320/recovery.img
  ```

### 正式刷入完整 `infinity_ossi-ota.zip` 的防砖红线
1. **必须备份个人数据并 Format Data**：ColorOS 与 Infinity-X 的 FBEv2（`wrappedkey_v0`）密钥不兼容；A/B 两槽共用物理 `/data` 与 `super`，首次刷入必双清 `/data`。
2. **严禁重锁 Bootloader**：保持 `vb=orange` 解锁态，绝不执行 `fastboot flashing lock`。
3. **绝对禁碰分区**：`persist`、`modemst1`、`modemst2`、`fsg`、`oplusreserve2`、`xbl`、`abl`、`tz`。
4. **救砖兜底**：完整 OTA 不修改底层引导分区（`xbl`/`abl`），只要保留本地验证过的 `RMX3820_15.0.0.320` 原厂底包，遇到任何启动异常均可通过 Fastboot / Fastbootd 刷回原厂，不会变 9008 黑砖。

---

## 5. GitHub Actions 工作流与自动化质量门禁总览

| Workflow 文件 | 功能 | 默认 Runner / 亮点 |
|---|---|---|
| `.github/workflows/build-kernel-gt5.yml` | 构建 `Pure-OGKI` 或 `YukiSU-LKM` 5.15.149 内核 | `self-hosted` (`MIRROR_MODE=cn`) / `ubuntu-latest` 可选；内置 3260 符号 CRC 与 `check_symbol` 校验 |
| `.github/workflows/build-infinity-rom.yml` | 构建并全项验签 `infinity_ossi` 完整 A/B OTA ROM | 支持国内镜像、三层云端缓存恢复/上传、可选连带构建 GSI、强制过 `rom-verify-delivery.py` |
| `.github/workflows/build-infinity-gsi.yml` | 独立构建并验签 DSU `Treble GSI arm64-ab` | 自动应用 `property_contexts` 去冲突 + Phoenix 喂狗 + `secilc` 实编验证 + 打包 `.img.gz` |
| `.github/workflows/watch-local-rom.yml` | 监控本地长耗时 ROM 构建进度并同步状态到 Actions | 见 [`docs/local-actions-monitor.md`](local-actions-monitor.md) |
| `.github/workflows/seed-clo-mirrors.yml` / `seed-gitea-mirrors.yml` | 预热同步 CLO / 第三方仓库镜像 | 加速国内节点拉取 |
| `.github/workflows/cleanup.yml` | 清理历史工作流记录与过期缓存 | 释放仓库配额 |

### 本地回归单元测试（推送前必跑）

```bash
python3 -m unittest discover -s tests -v
```

覆盖 8 个测试套件（`test_cn_mirrors.py`、`test_module_delivery.py`、`test_repo_retry_depth.py`、`test_rom_cache_sync.py`、`test_rom_inputs_and_delivery.py`、`test_rom_source_preflight.py`、`test_rom_watch_local.py`、`test_zh_cn_translations.py`），包含 `TrieBuilder::AddToTrie()` 冲突拦截、`oplus_phoenix.ko` 喂狗与 SELinux 写权限、881 条 `zh-rCN` 汉化 XML 完整性与 GT5 原厂自动亮度曲线单调性回归用例。

---

## 6. 彻底汉化（881 条简体中文补全）、硬件收尾修复与 6 层隐匿架构施工

### 6.1 简体中文彻底汉化（解决选中文后仍有英文）

- **根因**：Project Infinity-X 2.9 仅翻译了部分上游资源，五大核心组件累计缺失 **881 条** `values-zh-rCN` 字符串/数组/复数：
  - `packages/apps/InfinitySuite`：**341 条**
  - `packages/apps/Settings`：**327 条**
  - `frameworks/base/packages/SystemUI`：**190 条**（原 `values/infinity_strings.xml` 整份缺失中文）
  - `packages/apps/Launcher3`：**12 条**
  - `frameworks/base/core/res`：**11 条**
- **永久方案**：
  - 全部 881 条经 XML 解析、`%1$s`/`%d`/`xliff:g` 占位符与转义严格校验后固化在 [`rom/translations/zh-rCN/`](../rom/translations/zh-rCN/)；
  - `scripts/rom-patch-source.py`（`patch_infinity_zh_cn_translations`）与 `scripts/rom-build-gsi.sh` 均自动合并这些 `infinity_zh_cn_extra.xml`，并**动态剔除上游已新增的同名键**，永不触发 `aapt2` 重复资源报错。

### 6.2 DSU 实测挖出的硬件适配收尾修复

1. **GT5 原厂自动亮度曲线**：已从原厂 `ColorOS 15.0.0.320` `display_brightness_config_common.xml`（`lux_table id="3"` + `hbm_lux_table id="3"`）提取 `0~80101 lux -> 2.5~800 nits` 完整单调曲线，写入 [`rom/device/realme/ossi/overlay/frameworks/base/core/res/res/values/config.xml`](../rom/device/realme/ossi/overlay/frameworks/base/core/res/res/values/config.xml)（开启 `config_automatic_brightness_available=true`）。
2. **屏下指纹 feature 声明**：完整 ROM 已由 `device/oneplus/sm8550-common/common.mk` 拷贝 `android.hardware.fingerprint.xml` 至 `vendor/etc/permissions/`；同时在 `scripts/rom-build-gsi.sh` 为 Treble GSI 补齐 `system_ext/etc/permissions/android.hardware.fingerprint.xml`，使独立 DSU 也能拉起 `FingerprintService`。

### 6.3 2026 六层隐匿架构与一键部署脚本（`scripts/deploy-6layers-adb.sh`）

| 层级 | 核心组件 | 技术形态 | 主要职责与配置要点 |
|---|---|---|---|
| **第 1 层** | **YukiSU v1.9.0 + 内置 Kasumi/Kagami** | 内核 LKM + VFS 隐匿 | 匿名 fd + ioctl 零挂载点污染（`/proc/mounts` 保持纯净；**严禁混用 NoMount**）；开启 **UTS View** 将 `uname` 伪装为高通官方 GKI 标准格式 |
| **第 2 层** | **YukiZygisk (独立版)** | 内核态 Zygisk 引擎 | 刷入前**先在 YukiSU 关闭内置 YukiZygisk 开关**；匹配 `android13-5.15_yukizygisk.ko`，严禁与 ZN/ReZygisk 混装 |
| **第 3 层** | **TEESimulator-RS + Specter** | Rust `kmr-ta` + 属性调度大脑 | TEE 硬件证书链模拟（Strong Integrity 3/3 + DuckDetector 0 检出）；Specter 开启 `Boot Spoofing`、`ROM Cleaner`（剥离类原生残留 + 修复 Widevine L1）、`PIF Props`，保持 `ADB Lock = OFF` |
| **第 4 层** | **Yukari + FuseHide** | 纯 Zygisk 插件 | Yukari 过滤类原生专属 Binder 服务；FuseHide 注入 `MediaProvider` 按 UID 隔离 `/sdcard` 并阻断 CVE-2024-43093 零宽字符越权扫描 |
| **第 5 层** | **HMA-OSS (Zygisk 版)** | 纯 Zygisk 应用列表隔离 | 摆脱 LSPosed 依赖；由 Specter 自动同步黑名单规则（`Set HMA-OSS Configs`），并在 HMA-OSS 开启 **Vold Isolation** |
| **第 6 层** | **Vector v2.2+** | 现代 Hook 框架 | **黄金最小作用域**：仅勾选微信/QQ/系统增强等非敏感应用，**银行/政务/检测/反作弊应用绝对不勾选** |

#### 一键自动化部署命令（同时支持完整 ROM 与零刷写 Sticky DSU 沙箱实测）

```bash
# 前置：在手机 YukiSU Manager → 超级用户 中给 Shell (com.android.shell) 授权 Root

# 方式 1：在零刷写 Sticky DSU 沙箱中全自动完成 6 层部署、分批重启与验证
scripts/deploy-6layers-adb.sh \
  --pack-dir /path/to/yuki_6layers \
  --directlkm-boot /path/to/yukisu_v1.9.0_gt5_15.0.0.320_directlkm_boot.img

# 方式 2：在已刷好的完整类原生 ROM 上全自动部署 6 层并验证
scripts/deploy-6layers-adb.sh --pack-dir /path/to/yuki_6layers
```

