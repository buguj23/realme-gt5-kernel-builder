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
| `5.15.123` | `5.15.123-android13-8-00760-ga4e8787d5799` | 14.0.0.1120 | lineage-21 / 14 | f2fs |
| `5.15.149` | `5.15.149-android13-8-o-01120-g3337bebe8205` | 15.0.0.320 | lineage-22.2 / 15 | f2fs |
| `5.15.167` | `5.15.167-android13-8-o-01142-g18bd462653c5` | 15.0.0.1400 | lineage-22.2 / 15 | f2fs |
| `5.15.180` | `5.15.180-android13-8-o-01176-g6333b0dbc8ed` | **16.0.3.500** | lineage-23.2 / 16 | **f2fs** |

Actions → **Build Realme GT5 OGKI (KSU)** → 选 `FILE` 与 `KSU_VARIANT`。`main` 默认 5.15.180；各 `5.15.*` 分支锁定本版本，工作流文件随 `main` 同步。

产物命名：`AnyKernel3_<KSU_VARIANT>_GT5_<FILE>_<KSUVER>(<CKERNEL>)<SUFFIX>.zip`

```bash
git clone -b 5.15.180 https://github.com/buguj23/realme-gt5-kernel-builder.git
```

## ROM（ossi）

[构建手册](docs/ROM_BUILD.md)记录四个分支的原厂输入和 Android 基线。GitHub Actions 和本地共用一套构建与验收流程。

```bash
scripts/rom-build-local.sh --sync --src ~/gt5-rom/5.15.180 --branch 5.15.180 \
  --pkg ~/gt5_work/pkgs/5.15.180 --stock-images ~/gt5-stock/5.15.180
```

内核包使用 schema 2，记录同一个 Kbuild 输出中 Image、符号表和模块的哈希。构建验证 target-files、A/B OTA 和 AVB 后收集 userdebug 工件。
