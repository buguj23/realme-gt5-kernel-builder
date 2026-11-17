# Realme GT5 — OGKI 内核

设备 **ossi / RMX3820 / RE5C33**。上游 [Action-Build](https://github.com/Numbersf/Action-Build) 5.15 OGKI，**不使用 Google 通用 GKI**。

Root 为内核内 KernelSU 实现，派发时三选一：

| `KSU_VARIANT` | 上游仓库 | 内置分支默认 |
|---|---|---|
| `SukiSU-Nova`（默认） | `SukiSU-Nova/SukiSU-Nova` | `main/builtin/Numbersf/` |
| `BakaSU` | `Baka-SU/BakaSU` | `main/main/Numbersf/` |
| `FinaSU` | `LyraVoid/FinaSU` | `master/master/Numbersf/` |

三套步骤均取自上游对应分支原文，按 `KSU_VARIANT` 门控只执行一套。`KSU_META` 输入留空时自动套用所选变体的默认值，显式填写优先。

已用 `RMX3820_16.0.3.500(CN01)` 全量包校准 `5.15.180`（内核仍是 5.15.180，UTS `…-o-01176-g6333b0dbc8ed`，`/metadata` **f2fs**）。

| 分支 | 官方 uname | ColorOS | 类原生 | `/metadata` |
|---|---|---|---|---|
| `5.15.123` | `5.15.123-android13-8-00760-ga4e8787d5799` | 14.0.0.1120 | lineage-21 / 14 | ext4 |
| `5.15.149` | `5.15.149-android13-8-o-01120-g3337bebe8205` | 15.0.0.320 | lineage-22.2 / 15 | ext4 |
| `5.15.167` | `5.15.167-android13-8-o-01142-g18bd462653c5` | 15.0.0.1400 | lineage-22.2 / 15 | ext4 |
| `5.15.180` | `5.15.180-android13-8-o-01176-g6333b0dbc8ed` | **16.0.3.500** | lineage-23.2 / 16 | **f2fs** |

Actions → **Build Realme GT5 OGKI (KSU)** → 选 `FILE` 与 `KSU_VARIANT`。`main` 默认 5.15.180；各 `5.15.*` 分支锁定本版本，工作流文件随 `main` 同步。

产物命名：`AnyKernel3_<KSU_VARIANT>_GT5_<FILE>_<KSUVER>(<CKERNEL>)<SUFFIX>.zip`

```bash
git clone -b 5.15.180 https://github.com/buguj23/realme-gt5-kernel-builder.git
```

## ROM（Project Infinity-X，ossi）

设备树覆盖层在 `rom/`，内核必须用本仓库产出的 OGKI 包（`Image` + 全部 `.ko` + `Module.symvers` 同一次构建）：

| 环节 | 工具 |
|---|---|
| 内核成套打包（CI） | `scripts/kernel-package.sh` → 工件 `kernel-package_<变体>_<版本>` |
| 对齐校验 | `scripts/kmi.py verify`（`module_layout` 与逐符号 CRC） |
| ROM 暂存 | `scripts/rom-stage-kernel.py`（原厂 146 项一阶段顺序，CRC 不符即中止） |
| vendor_boot 守卫 | `scripts/rom-vendor-boot-fix.sh`（page `0x1000`、偏移、`modules.load`） |
| IDA 侧复核 | `scripts/ida_kmi_check.py` |
| 原厂清单抽取 | `scripts/stock-module-lists.sh` |

工作流：**Build Project Infinity-X (ossi)**。`verify` 作业在托管 runner 上校验内核包；`build` 作业需要自托管 runner（AOSP 源码树 200 GB 起，托管 runner 的 14 GB 磁盘与 6 小时上限无法承载）。

### 本地构建（推荐）

完整手册见 **`docs/ROM_BUILD.md`**。四个脚本覆盖全流程：

| 脚本 | 作用 |
|---|---|
| `scripts/rom-sync.sh` | `repo init` + 改写 remote 到清华镜像 + 增量同步 |
| `scripts/rom-manifest-mirror.py` | 把 AOSP/Lineage/GitHub remote 指向国内镜像或加速前缀 |
| `scripts/rom-provision-deps.sh` | 补齐清单没有的 `sm8550-common`、`hardware/oplus`、`pixelworks` |
| `scripts/rom-build-local.sh` | 预检磁盘/输入 → 设备树 → Blob → 内核暂存 → `lunch` → `mka bacon` |

首条命令：

```bash
scripts/rom-sync.sh --dir ~/rom16 --manifest https://github.com/ProjectInfinity-X/manifest --branch 16
scripts/rom-build-local.sh --src ~/rom16 --branch 5.15.180 \
  --blobs ~/gt5_work/dumps/5.15.180 --pool ~/gt5_work/pools/5.15.180 \
  --pkg ~/gt5_work/pkgs/5.15.180 --lunch infinity_ossi-userdebug --deps-branch lineage-23.2
```

云端实测（16C/64G/300G）四棵树无法轮流容纳，且时间几乎全花在网络上（A16 单树同步至
113 GB 仍未结束、镜像端并发排队），故不再使用。
