# Realme GT5 (`5.15.149` OGKI) — Project Infinity-X 3.12 (Android 16) Treble GSI Builder

Dedicated **`infinity-x-3.12`** branch focusing **100% on Project Infinity-X 3.12 (Android 16 QPR2 / `bp4a`) Treble GSI (`infinity_gsi_arm64`)** running on top of Realme GT5 (`RMX3820` / `RE5C33`) stock firmware **`RMX3820_15.0.0.320(CN01)`** and its verified **`5.15.149` OGKI / YukiSU-LKM** kernel (`module_layout = 0x0222dd63`).

> **Scope notice**: This branch intentionally excludes `ossi` full-ROM staging/device trees. For the historical Android 15 / Infinity-X 2.9 `ossi` full-ROM branch, see branch [`5.15.149`](../../tree/5.15.149).

## Verified Baseline (`5.15.149` Kernel + Infinity-X `3.12` GSI)

| Item | Value |
|---|---|
| Target ROM / GSI | **Project Infinity-X 3.12** (`ProjectInfinity-X/manifest` branch **`16`**, Android 16 QPR2 / `bp4a`) |
| GSI Lunch Target | `infinity_gsi_arm64-bp4a-user` (default, clean SELinux) or `infinity_gsi_arm64-bp4a-userdebug` |
| Stock Vendor Baseline | `RMX3820_15.0.0.320(CN01)` (`RMX3820_11.F.06_2060_202411241938`, Android 15 / API 35, SPL `2024-11-05`) |
| Kernel Baseline | `5.15.149-android13-8-o-01120-g3337bebe8205` (`android13-5.15` GKI gen `8`, `module_layout = 0x0222dd63`, **3260 / 3260** stock module CRCs matched) |
| Kernel Root Modes | `Pure-OGKI` (zero built-in root) or `YukiSU-LKM` (`Rouyashiki/YukiSU`, out-of-tree `CONFIG_KSU=m`) |
| Banned Kernel Options | `CONFIG_KSU=y`, `SUSFS`, `KPM`, `FakeConfig`, OnePlus analogue manifests (`0xbb266e1e`) |

## Built-in Infinity-X 3.12 GSI Fixes, Localization & Anti-Detection

All source-level GSI patches live in [`scripts/rom-patch-source.py`](scripts/rom-patch-source.py) and are reversibly staged by [`scripts/rom-build-gsi.sh`](scripts/rom-build-gsi.sh):

1. **Upstream Infinity-X 16 GSI Fixes**:
   - Fixes `vendor/infinity/build/target/product/infinity_gsi_arm64.mk` (`lineage_generic_target.mk` → `infinity_generic_target.mk`, `PRODUCT_NAME := infinity_gsi_arm64`, `building_lineage_gsi=true`).
   - Guards `system_ext_userdebug_plat_sepolicy.cil` in `device/generic/common/gsi_system_ext.mk` so **`user` builds never ship `userdebug` SELinux policy** (eliminates `shell -> su` and `adbd -> adbroot` SELinux policy detections).
   - Disables `permissive backuptool;` in `device/lineage/sepolicy/common/private/backuptool.te` for strict Android 16 `user` build SELinux compliance.
2. **Realme GT5 (`RMX3820_15.0.0.320`) Hardware & ColorOS 15 Vendor Compatibility**:
   - **ColorOS `property_contexts` TrieBuilder fix**: strips all `ro.vendor.*` / `vendor.*` / `persist.vendor.*` / `ro.odm.*` entries from `system_ext_property_contexts` and verifies 0 duplicates with [`scripts/gsi_verify.py`](scripts/gsi_verify.py).
   - **OPLUS Phoenix 250s watchdog disarm**: writes `NATIVE_INIT_POST_FS` / `ANDROID_BOOT_COMPLETED` / `PHOENIX_BOOT_COMPLETED` to `/proc/phoenix` via `init.gsi.rc` with Enforcing `proc_phoenix` SELinux rules.
   - **Optical UDFPS + Fingerprint feature**: exposes `android.hardware.fingerprint.xml` in `/system_ext/etc/permissions/` and applies OPLUS/OPPO optical UDFPS Z-order (`0x41000005` dim / `0x41000033` touched) in `UdfpsExtension.cpp`.
   - **Factory Auto-Brightness Curve**: applies Realme GT5 ColorOS `15.0.0.320` lux→nits overlay from [`gsi/overlay/gt5/`](gsi/overlay/gt5/frameworks/base/core/res/res/values/config.xml).
   - **Mainland China Captive Portal**: switches `NetworkStack` default HTTP/HTTPS validation URLs (`values` + `values-mcc460`) to `connect.rom.miui.com/generate_204` and `connectivitycheck.qualcomm.cn/generate_204` with `config_no_sim_card_uses_neighbor_mcc=true`.
3. **Custom-ROM / LineageOS Anti-Detection (`yokeshiq` patches rebased to Android 16)**:
   - **`bionic/libc/bionic/custom_rom_hide.cpp`**: expands Infinity-X 16's built-in `custom_rom_hide` with system-app allowlist (`SystemUI`, `Settings`, `Launcher3`, `Shell`, `org.lineageos.*`), `/data/resource-cache/*lineage*` idmap blocking, `/etc/selinux/` probe blocking (`ROM detected (a)`), `readdir` dirent filtering (`lineage`, `addon.d`, `hwservice_contexts`, `platform-infinity`), `*/etc/sysconfig/*.xml` `org.lineageos.*` `<install-in-user-type>` filtering (`LineageOS detected (17)`), and full `lineage` / `ro.modversion` / `ro.cm.*` / `ro.infinity.*` property hiding.
   - **`frameworks/base` (12 Java files)**: hides Lineage assets, services, system properties, Settings keys, protected broadcasts, packages, ContentProviders, permissions, system features, and `getInitialNonStoppedSystemPackages` (`LineageOS detected (18)`) from non-allowlisted third-party apps.
   - **Drop `ro.modversion`**: removes `ro.modversion` from `vendor/infinity/config/version.mk` and migrates `Updater` (`Constants.java`) to `ro.infinity.build.version`.
4. **Unified Simplified Chinese (`zh-rCN`) Localization**:
   - [`gsi/translations/zh-rCN/`](gsi/translations/zh-rCN/) combines our verified Infinity-X translations + [`yokeshiq/infinity_chinese_translations`](https://github.com/yokeshiq/infinity_chinese_translations) (**20 packages, 8,997 entries**).
   - At build time, `patch_infinity_zh_cn_translations()` filters against both upstream `values-zh-rCN/*.xml` (zero `aapt2` duplicates) and default `values/*.xml` (zero missing-default-value warnings across Android versions).

## Quick Start

### 1. Sync Project Infinity-X 3.12 (`16`) Source Tree

```bash
bash scripts/rom-sync.sh \
  --dir ~/gt5-gsi/infinity-x-3.12 \
  --manifest https://github.com/ProjectInfinity-X/manifest \
  --branch 16
```

### 2. Build & Verify Treble GSI (`user` Vanilla or GApps)

```bash
# Default: user build, Vanilla, yokeshiq anti-detection ON, zh-rCN ON, auto RAM-safe jobs
bash scripts/rom-build-gsi.sh \
  --src ~/gt5-gsi/infinity-x-3.12 \
  --output ~/gt5-gsi-out

# Optional GApps or userdebug variant:
bash scripts/rom-build-gsi.sh \
  --src ~/gt5-gsi/infinity-x-3.12 \
  --output ~/gt5-gsi-out-gapps \
  --variant user \
  --gapps true
```

### 3. Build 5.15.149 OGKI / YukiSU-LKM Kernel (Unchanged KMI `0x0222dd63`)

```bash
kernel/build-kernel-local.sh --fetch --patch --mode YukiSU-LKM
```

## GitHub Actions Workflows

- [`.github/workflows/build-infinity-gsi.yml`](.github/workflows/build-infinity-gsi.yml) — Build & verify Project Infinity-X 3.12 Treble GSI (`user`/`userdebug`, Vanilla/GApps, optional source sync & cache restore, publishes to release `infinity-x-3.12-gsi-arm64-dsu`).
- [`.github/workflows/seed-gitea-mirrors.yml`](.github/workflows/seed-gitea-mirrors.yml) — Seed Infinity-X `16` Gitea/LFS bare repositories (`infinity-16-gitea-seed`) for fast domestic CN runner syncs.
- [`.github/workflows/build-kernel-gt5.yml`](.github/workflows/build-kernel-gt5.yml) — Build `Pure-OGKI` / `YukiSU-LKM` `5.15.149` kernels (`module_layout = 0x0222dd63`).
- [`.github/workflows/cleanup.yml`](.github/workflows/cleanup.yml) — Workflow run & cache cleanup.

## Documentation

- [**Infinity-X 3.12 (Android 16) GSI Build, Localization & Anti-Detection Guide**](docs/GSI_3_12_BUILD.md)
- [GSI Assets Overview (`gsi/overlay/gt5` & `gsi/translations/zh-rCN`)](gsi/README.md)
- [YukiSU `CONFIG_KSU=m` Adaptation Guide](docs/YUKISU_GUIDE.md)
- [KMI & Kernel Verification](docs/ROM_KMI.md)
- [Upstream Lineage & Design Contracts](docs/UPSTREAM.md)
