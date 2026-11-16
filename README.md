# Realme GT5 kernel builder (Action-Build OGKI 5.15 + YukiSU)

真我 GT5（ossi / RMX3820 / RE5C33，SM8550 kalama）内核构建仓库。

- 上游构建系统：**[Numbersf/Action-Build](https://github.com/Numbersf/Action-Build)**（禁止 Google 通用 GKI）
- 内核源码：Action-Build 的 **一加 / OPPO SM8550 5.15 OGKI** 清单（真我 SKU 不在 Action-Build 机型表，用同 SoC 近亲）
- Root：**[Rouyashiki/YukiSU](https://github.com/Rouyashiki/YukiSU)** LKM（`CONFIG_KSU=m` + Kasumi + YukiZygisk）
- 默认 analogue：`oneplus_ace2_pro_b`（Android 16 / kalama / ColorOS）

`oplus_build_kernel.sh kalama gki` 里的 `gki` 是 **OEM OGKI flavor**，不是 `ci.android.com` 通用 GKI。

## 已拉取的 Action-Build 5.15.*

| 路径 | 用途 |
|---|---|
| `patches/bbrv3/*android13-5.15*` `*android14-5.15*` | BBRv3 |
| `patches/ntsync/*5.15*` | ntsync |
| `patches/fix_5.15.legacy` | 5.15.0–5.15.123 旧 C 库 |
| `patches/kpm` `patches/kpn` | KPM/KPN Image 修补 |
| `manifests/oneplus-sm8550/*.xml` | 一加 11 / Ace2 Pro / Ace3 / Open / 12R 全部 `_t/_u/_v/_b` |
| `manifests/oppo-sm8550/*.xml` | Find X6 Pro / Find N3 |
| `lib/ccache` `scripts/*.kts` `ZRAM.zip` | Action-Build CI 资产 |

机型对照：`configs/device-map.md`。Action-Build 原清单：`FILE.md`。

## 本地

```bash
export FILE=oneplus_ace2_pro_b          # 或 oneplus_11_v / oppo_find_x6_pro_v …
export KP_DIR=~/gt5_kernel_ab/kernel_platform
scripts/00-fetch.sh                     # repo sync OEM OGKI
scripts/10-patch.sh                     # YukiSU LKM + 5.15 patches
scripts/20-build.sh                     # oplus_build_kernel.sh kalama gki
scripts/30-package.sh                   # AnyKernel3 Image + kernelsu.ko
scripts/rom-adapt.sh                    # 只换 boot，不动 vendor_boot fstab
```

## GitHub Actions

Workflow **Build Realme GT5 OGKI (YukiSU)**：`FILE` 只列出 SM8550 5.15 一加/OPPO analogue。默认 `oneplus_ace2_pro_b`。`SUSFS_META=-1`（YukiSU 用 Kasumi，禁止 SUSFS）。

## 刷写

```bash
fastboot getvar current-slot
fastboot --set-active=a
fastboot flash boot_a boot.img          # OGKI Image，或刷 AnyKernel3 zip
# 不要刷 Google GKI boot.img
# 不要在未同源构建时刷 vendor_boot（metadata fstab ext4/f2fs 会循环）
```

AnyKernel 设备名：`ossi` `RMX3820` `salami` `corot` `xigua`。

## 明确不做的事

1. 不用 Google 通用 GKI。
2. 不用 `configs/reference/rom_ikconfig.defconfig` 当构建 defconfig。
3. 不把 SukiSU `CONFIG_KSU=y` / SUSFS 打进树。
4. 不在 Action-Build 里虚构真我 FILE；用一加/OPPO 近亲。
