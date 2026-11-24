# Project Infinity-X 3.12 (Android 16) Treble GSI Build Guide (`5.15.149` Baseline)

本指南面向 **`infinity-x-3.12`** 分支，专为 **Realme GT5 (`RMX3820` / ColorOS `15.0.0.320` / `5.15.149` OGKI 内核)** 构建与部署 **Project Infinity-X 3.12（Android 16 QPR2 / `bp4a`）Treble GSI**（不涉及 `ossi` 完整 ROM 刷机包）。

---

## 1. 架构与兼容性说明

- **内核与底包零改动**：直接复用原厂 `RMX3820_15.0.0.320` 的 `vendor` / `odm` / `my_*` 分区，以及本仓库 `5.15.149` Pure-OGKI / YukiSU-LKM 内核（`module_layout = 0x0222dd63`，`android13-5.15` GKI gen 8，官方支持至 Android 17）。
- **为什么不需要改 BPF 内核检查**：Infinity-X `16` 分支的 `packages/modules/Connectivity/bpf/loader/NetBpfLoad.cpp` 已放宽内核版本硬校验，且 `5.15.149` 原生满足 Android 16 最低内核要求（`>= 5.10`）。
- **无损 DSU 体验**：构建产出的 `Infinity-X-3.12-gsi_arm64-<vanilla|gapps>-<user|userdebug>-ab.img.gz` 可通过 **DSU-Sideloader-Plus** 直接挂载启动，完全不破坏原厂 ColorOS `system` 分区。

---

## 2. 本分支集成的全部适配与补丁

由 [`scripts/rom-patch-source.py`](../scripts/rom-patch-source.py) 与 [`scripts/rom-build-gsi.sh`](../scripts/rom-build-gsi.sh) 自动应用（并在构建结束后自动还原源码树，保持 `rom-src` 干净）：

### A. Android 16 / Infinity-X 3.12 GSI 上游修复
1. 修复上游 `vendor/infinity/build/target/product/infinity_gsi_arm64.mk` 中 `lineage_generic_target.mk` 不存在及 `PRODUCT_NAME := lineage_gsi_arm64` 命名错位问题，并设置 `soong_config_set_bool,gsi,building_lineage_gsi,true`。
2. 修复 `device/generic/common/gsi_system_ext.mk`：仅在 `userdebug`/`eng` 构建时安装 `system_ext_userdebug_plat_sepolicy.cil`；**`user` 构建彻底剥离该调试策略**，杜绝 `shell -> su` / `adbd -> adbroot` SELinux Policy 检测异常。
3. 注释 `device/lineage/sepolicy/common/private/backuptool.te` 中的 `permissive backuptool;`，并将 `adbd.te` 中的 `adbroot` 规则限定在 `userdebug_or_eng(...)`，使 `infinity_gsi_arm64-user`（自动识别 `bp4a`）严格通过 Android 16 `user` 模式 SELinux 检查且零调试策略残留。
4. 修复 `build/make/target/product/gsi_release.mk` 中 `BUILDING_LINEAGE_GSI` 未匹配 `infinity_gsi_%` 的上游漏改，并将 `BoardConfigGsiCommon.mk` 的 `gsi_dynamic_partitions` 上限从 3.0 GiB 提升至 9.0 GiB（配合 `PRODUCT_USE_DYNAMIC_PARTITION_SIZE=true` 按实际内容动态收缩镜像），同时支持 Vanilla 与 GApps 构建。

### B. Realme GT5 (`RMX3820_15.0.0.320`) 硬件与国内网络修复
1. **ColorOS `property_contexts` 冲突清理**：剥离 `system_ext` 中的 `ro.vendor.*` / `vendor.*` / `persist.vendor.*` / `ro.odm.*`，并用 [`scripts/gsi_verify.py`](../scripts/gsi_verify.py) 模拟 `TrieBuilder::AddToTrie` 校验 0 冲突。
2. **OPLUS Phoenix 250 秒看门狗解除**：在 `init.gsi.rc` 写入 `SET_BOOTSTAGE@NATIVE_INIT_POST_FS` / `ANDROID_BOOT_COMPLETED` / `PHOENIX_BOOT_COMPLETED`，并配置 Enforcing 模式 `proc_phoenix` SELinux 规则。
3. **光学屏下指纹修复**：将 `android.hardware.fingerprint.xml` 暴露至 `/system_ext/etc/permissions/`，并在 `UdfpsExtension.cpp` 写入 OPLUS/OPPO 光学指纹 Z-order（`0x41000005` 压暗层 / `0x41000033` 触控高亮层）。
4. **GT5 原厂自动亮度曲线**：应用 [`gsi/overlay/gt5/frameworks/base/core/res/res/values/config.xml`](../gsi/overlay/gt5/frameworks/base/core/res/res/values/config.xml)。
5. **国内 Wi-Fi 连通性检测修复**：将 `NetworkStack` 的 `values/config.xml` 与 `values-mcc460/config.xml` 默认检测地址替换为 `connect.rom.miui.com/generate_204` + `connectivitycheck.qualcomm.cn/generate_204`，并开启无 SIM 卡邻近 MCC 推断。

### C. 类原生 / LineageOS 特征隐藏（基于 `yokeshiq` 仓库适配至 Android 16）
- **`bionic/libc/bionic/custom_rom_hide.cpp`**（无缝融合进 Infinity-X 16 原生 `custom_rom_hide` 机制）：
  - 白名单放行 `com.android.systemui`、`com.android.settings`、`com.android.launcher*`、`com.android.shell`、`com.infinity.updater`、`org.lineageos.*` 及内置游戏白名单。
  - 放行应用 `/data/*` 私有目录，但拦截 `/data/resource-cache/*lineage*` idmap 缓存。
  - 拦截三方应用探测 `/etc/selinux/`（阻断 `ROM detected (a)`），`open`/`stat`/`lstat`/`faccessat` 一致返回 `ENOENT`。
  - 拦截并过滤目录遍历（`readdir`）中的 `lineage`、`addon.d`、`hwservice_contexts`、`platform-infinity`。
  - 动态过滤 `*/etc/sysconfig/*.xml`（如 `preinstalled-packages-platform-list-product.xml`）中的 `org.lineageos.*` `<install-in-user-type>` 段落（阻断 `LineageOS detected (17)`）。
  - 全面屏蔽 `lineage`、`ro.modversion`、`ro.cm.*`、`ro.infinity.*` 属性。
- **`frameworks/base`（12 个 Java 文件，已针对 Android 16 精确重基）**：
  - `ApkAssets`、`AssetManager`、`Resources`、`ServiceManager`、`SystemProperties`、`SettingsProvider`、`BroadcastController`、`ComputerEngine`、`PackageManagerService`（含 `getInitialNonStoppedSystemPackages` 过滤，阻断 `LineageOS detected (18)`）、`ResolveIntentHelper`、`PackageInfoUtils`、`PermissionManagerService`。
- **`vendor/infinity/config/version.mk` & `packages/apps/Updater`**：移除 `ro.modversion`，更新器改读 `ro.infinity.build.version`。

### D. 简体中文（`zh-rCN`）全量补充汉化
- 整合本仓库原有精选汉化与 [`yokeshiq/infinity_chinese_translations`](https://github.com/yokeshiq/infinity_chinese_translations)，共计 **20 个包、8,997 条词条**（存放于 [`gsi/translations/zh-rCN/`](../gsi/translations/zh-rCN/)）。
- 构建期自动对照上游 `values/*.xml`（仅注入当前 Android 16 源码中真实存在的默认键）和上游 `values-zh-rCN/*.xml`（跳过已有译文），确保 `aapt2` 零重复、零缺省值告警。

---

## 3. 本地同步与构建流程

### 第一步：拉取 Project Infinity-X 3.12 (`16`) 源码

```bash
# 若国内机器先在 GitHub Actions 触发一次 Seed Gitea/LFS Mirrors (branch=16)，同步速度更快
bash scripts/rom-sync.sh \
  --dir ~/gt5-gsi/infinity-x-3.12 \
  --manifest https://github.com/ProjectInfinity-X/manifest \
  --branch 16
```

### 第二步：编译并校验 Treble GSI

```bash
# 默认：user 构建 + Vanilla + yokeshiq 特征隐藏 + 简体中文汉化
# 在 <=20 GiB 内存主机上自动限制 JOBS=4、SOONG_GOMEMLIMIT=7GiB、JAVA_TOOL_OPTIONS=-Xmx2560M 防止 R8 OOM
bash scripts/rom-build-gsi.sh \
  --src ~/gt5-gsi/infinity-x-3.12 \
  --output ~/gt5-gsi-out

# 如需 GApps 版本或 userdebug 版本：
bash scripts/rom-build-gsi.sh \
  --src ~/gt5-gsi/infinity-x-3.12 \
  --output ~/gt5-gsi-out-gapps \
  --variant user \
  --gapps true
```

构建完成后，`$OUT` 目录将包含：
- `Infinity-X-3.12-gsi_arm64-<vanilla|gapps>-<user|userdebug>-ab.img`
- `Infinity-X-3.12-gsi_arm64-<vanilla|gapps>-<user|userdebug>-ab.img.gz`
- `gsi-verify.txt`（自动校验 `init.gsi.rc`、`proc_phoenix`、`system_ext_property_contexts`、`android.hardware.fingerprint.xml`、`ro.modversion` 清理以及 `user` 构建无 `userdebug` SELinux 策略）
- `SHA256SUMS.txt`

### 第三步：增量缓存云端同步（可选）

```bash
# 上传 pruned out/gsi 缓存至 GitHub Release gsi-cache-3.12-infinity
python3 scripts/rom-cache-sync.py upload \
  --out-dir ~/gt5-gsi/infinity-x-3.12/out/gsi \
  --work-dir /tmp/gsi-cache-work

# 在新机器恢复缓存
python3 scripts/rom-cache-sync.py restore \
  --src ~/gt5-gsi/infinity-x-3.12 \
  --tag gsi-cache-3.12-infinity
```

---

## 4. 真机 DSU 无损启动与 6 层隐匿部署

1. 将生成的 `Infinity-X-3.12-gsi_arm64-*.img.gz` 传到手机，用 **DSU-Sideloader-Plus** 安装（建议分配 >= 16 GB userdata）。
2. 如需 YukiSU LKM 隐匿环境，配合本仓库 `5.15.149` YukiSU-LKM 内核与 [`scripts/deploy-6layers-adb.sh`](../scripts/deploy-6layers-adb.sh) 一键部署（已自动开启 Specter `toggle_custom_rom_props=1` 及国内 Captive Portal 配置）。
