# `gsi/` — Project Infinity-X 3.12 (Android 16) Treble GSI Assets

This directory holds device-safe Treble GSI overlays and Simplified Chinese (`zh-rCN`) localization banks consumed by [`scripts/rom-build-gsi.sh`](../scripts/rom-build-gsi.sh) and [`scripts/rom-patch-source.py`](../scripts/rom-patch-source.py).

## Contents

- **`overlay/gt5/frameworks/base/core/res/res/values/config.xml`**
  - Realme GT5 (`RMX3820_15.0.0.320`) factory auto-brightness lux-to-nits curve (`config_autoBrightnessLevels` & `config_autoBrightnessDisplayValuesNits`), copied into `device/generic/common/overlay_gt5_brightness` during GSI builds so auto-brightness behaves smoothly on the GT5 AMOLED panel without modifying `/vendor`.
- **`translations/zh-rCN/<package>/res/values-zh-rCN/infinity_zh_cn_extra.xml`**
  - Unified Simplified Chinese localization bank covering **20 packages (8,997 entries)**, combining:
    - Our curated Infinity-X `zh-rCN` translations (`InfinitySuite`, `SystemUI`, `Settings`, `Launcher3`, `framework-res`)
    - [`yokeshiq/infinity_chinese_translations`](https://github.com/yokeshiq/infinity_chinese_translations) (including `OmniJaws`, `AxQuickLook`, `ThemeStore`, `Sandbox`, `PersonalContext`, `Updater`, `OmniStyle`, `FaceUnlock`, `AppLocker`, etc.)
  - Filtered automatically at build time against each package's default `values/*.xml` and upstream `values-zh-rCN/*.xml` so `aapt2` produces zero duplicate-resource or missing-default-value warnings/errors.
