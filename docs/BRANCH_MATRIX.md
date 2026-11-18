# 分支矩阵（逐分支实测，2026-11-17）

四条分支各自对应一份完整 OTA。下表全部由 `scripts/branch-facts.py` 从
`payload.bin` 解出的镜像直接测得，不可跨分支照抄。

| 分支 | OTA / 构建指纹 | uname | Android / API | SPL | 一阶段 | recovery | vendor_dlkm | system_dlkm | `module_layout` |
|---|---|---|---|---|---|---|---|---|---|
| `5.15.123` | `14.0.0.1120` `T.1a73b78-941b-1` | `5.15.123-android13-8-00760-ga4e8787d5799` | 14 / 34 | 2024-10 | **134** | 403 | **345** | 2 | `0x0222dd63` |
| `5.15.149` | `15.0.0.320` `T.1b22798_7579-6758f` | `5.15.149-android13-8-o-01120-g3337bebe8205` | 15 / 35 | 2024-11 | **145** | 438 | **378** | 2 | `0x0222dd63` |
| `5.15.167` | `15.0.0.1400` `T.1fc6783-2-f6d31` | `5.15.167-android13-8-o-01142-g18bd462653c5` | 15 / 35 | 2025-09 | **145** | 440 | **380** | 2 | `0x0222dd63` |
| `5.15.180` | `16.0.3.500` CN01 | `5.15.180-android13-8-o-01176-g6333b0dbc8ed` | 16 / 36 | 2026-02 | **146** | 445 | **385** | 2 | `0x0222dd63` |

另有第五份 OTA（`T.1f182dd_1-4888b`，2025-08）也是 `5.15.167-android13-8-o-01140-g043e86cdd499`：
同分支的更早固件版本，不作为 `5.15.167` 的基线，旧机若停在该版本可继续用同分支内核。

## 四分支一致的事实

* `module_layout` CRC 全部 **`0x0222dd63`** —— 四套原厂 `vendor_dlkm` 模块
  （345/378/380/385 个）与 `system_dlkm`（各 2 个）逐一核对，无一例外。
  这解释了为什么同一套 OGKI 构建方法能为四条分支产出可加载的内核。
* 四份原厂 fstab 的 `/metadata` 均为 **f2fs**。两个 DLKM 文件系统从对应 OTA 的实际镜像识别，当前工作区待补齐这些镜像复验。
* `boot` 头 v4、`os_version` 均为 `13.0.0`（KMI 版本，不是 Android 版本）。

## 必须逐分支处理的事实

| 项 | 为什么不能共用 |
|---|---|
| 一阶段 `modules.load` | 134 / 145 / 145 / 146 项，顺序与集合都不同；用错分支的清单会缺 UFS/FBE 模块 |
| `vendor_dlkm` 模块集合 | 345 / 378 / 380 / 385 个 |
| SPL → `BOOT_SECURITY_PATCH` | 2024-10 / 2024-11 / 2025-09 / 2026-02 |
| ROM 平台 SDK | 34 / 35 / 35 / 36 |
| 内核包 | 必须由**该分支**的 `Build Realme GT5 OGKI (KSU)` 运行产出 |

## 每分支的校验命令

```bash
# 采集该分支 OTA 的事实
python3 scripts/branch-facts.py --stock <ota-img-dir> --label <branch> --json facts.json
# 内核包必须与该分支的 CRC 和一阶段清单一致
python3 scripts/branch-compare.py --facts facts.json --package <kernel-package>
# 有 ROM 产物后比对整包
python3 scripts/branch-compare.py --facts facts.json --deliver <rom-out-dir>
```

`branch-compare.py` 在旧交付包（16.0.3.500）上会同时报出：`os_version` 16.0.0 vs
13.0.0、一阶段 50 vs 146、`system_dlkm` CRC `0xedfc7a5c` vs `0x0222dd63`。

## `module_layout` 相同 ≠ 符号级兼容

四分支的 `module_layout` 都是 `0x0222dd63`，但**不能**因此把任一分支的模块挪给另一分支用。
实测：拿 `16.0.3.500` 内核的符号表去配 `14.0.0.1120` 的首阶段模块，暂存器拒绝了三项：

```
phy-qcom-ufs-qmp-v4-kalama.ko : 7 symbol mismatches
  (ufs_qcom_phy_dump_regs, ufs_qcom_phy_write_tbl, get_ufs_qcom_phy, ...)
phy-qcom-ufs-qrbtc-sdm845.ko  : 3 symbol mismatches
qcom_dma_heaps.ko             : 1 symbol mismatch (register_mtrack_debugger)
```

同一分支也应以暂存时的逐符号校验结果为准。因此：

* 内核包必须由**该分支**工作流产出，`Module.symvers` 随之成套；
* `scripts/rom-stage-kernel.py` 的借用只在**本分支符号表**下通过才成立；
* 跨分支搬 .ko 会在 `load_module` 阶段被 `-ENOEXEC` 拒绝。

## 闭源 Blob 清单（逐分支生成，可复现）

清单不是手写的：`scripts/rom-select-blobs.py` 会挂载该分支 OTA 的
`vendor/odm/system_ext/product/system/my_product` 镜像，逐条 `stat()` 上游
`device/oneplus/sm8550-common` 清单，保留存在的条目（含 `;SYMLINK=`、
`;MODULE_SUFFIX=` 注解），再补入本机实际存在、但平台清单没有的 Oplus HAL
（`*/bin/hw/*oplus*`、`*/lib*/hw/*oplus*`、`*/lib*/*oplus*.so`、vintf manifest、
oplus init rc、oplus permission xml）。

16.0.3.500 实测：

| 分区 | 平台清单 | 本机存在 |
|---|---|---|
| vendor | 1044 | 1044 |
| odm | 137 | 128 |
| system_ext | 111 | 111 |
| product | 7 | 2 |
| system / my_product | 8 | 0（A16 已移除 Hotword/ostatslog 映射项） |

产出：`proprietary-files.txt` 1285 条平台项 + 349 条 Oplus 补充；`extract-files.py`
对 1634 个文件跑完后生成 `ossi-vendor.mk`（1549 项）、`Android.bp`（30359 行）。
缺失的 22 条均为该机型确实不带（contexthub、esim 等）。

复现：

```bash
python3 scripts/rom-select-blobs.py --base-list proprietary-files.txt \
  --images <ota-img-dir> --label <branch> \
  --out proprietary-files.txt --materialize <dump-dir>
# 然后在源码树的 device/realme/ossi 下按分支选择平台 SDK
OSSI_PLATFORM_SDK=36 ./extract-files.py <dump-dir>
```

### 四分支 Blob 提取结果

| 分支 | 平台清单保留 | Oplus 补充 | ossi-vendor.mk | Android.bp |
|---|---|---|---|---|
| `5.15.123` (14.0.0.1120) | 1235 | 330 | 1500 行 | 29149 行 |
| `5.15.149` (15.0.0.320) | 1266 | 347 | 1541 行 | 29911 行 |
| `5.15.167` (15.0.0.1400) | 1266 | 346 | 1540 行 | 29903 行 |
| `5.15.180` (16.0.3.500) | 1285 | 349 | 1560 行 | 30359 行 |

每个分支的清单由**该分支自己的 OTA** 生成，不可互换：A14 的 5.15.123 少 50 条平台项、
Oplus HAL 少 19 条，正是跨版本 HAL 变更的体现。

## 板级配置补齐（非内核部分）

从同 SoC 的 `device/oneplus/sm8550-common/BoardConfigCommon.mk` 取用、并**排除所有
GKI/内核项**后补入 `BoardConfigOgki.mk`：

- 音频：`AUDIO_FEATURE_ENABLED_*`（DLKM / AGM / PAL / SSR / SVA / proxy…）、
  `BOARD_USES_ALSA_AUDIO`、`TARGET_PROVIDES_{AUDIO_HAL,LIBAGM,LIBAR_PAL}`、
  `BOARD_SUPPORTS_{SOUND_TRIGGER,OPENSOURCE_STHAL}`
- 属性与文件标签：`TARGET_{ODM,PRODUCT,SYSTEM_EXT,VENDOR}_PROP`、
  `TARGET_FS_CONFIG_GEN := device/oneplus/sm8550-common/config.fs`
- 安全策略：`include hardware/oplus/sepolicy/qti/SEPolicy.mk`（与
  `device/qcom/sepolicy_vndr` 并列）
- WiFi：`WIFI_FEATURE_HOSTAPD_11AX`、`WIFI_HIDL_FEATURE_{AWARE,DUAL_INTERFACE}`、
  `WIFI_HIDL_UNIFIED_SUPPLICANT_SERVICE_RC_ENTRY`、`..._PRIVATE_LIB_EVENT`
- DTB：`BOARD_USES_QCOM_MERGE_DTBS_SCRIPT`
- 分区保留：`BOARD_PRODUCTIMAGE_MINIMAL_PARTITION_RESERVED_SIZE := false`、
  `-include vendor/lineage/config/BoardConfigReservedSize.mk`

**未采用**其 `BOARD_USES_GENERIC_KERNEL_IMAGE := true`、`TARGET_KERNEL_*`、
`BOARD_*_KERNEL_MODULES*`。DLKM 分区文件系统取自对应原厂镜像。

## 逐分支暂存校验

初版暂存结果使用平铺模块池和较弱的门禁。当前构建按启动阶段与分区校验，完整原厂输入和 schema 2 内核包就绪后重新验证。三个 A14/A15 OTA 的组名为 `qti_dynamic_partitions`，组配额为 `14491320320` 字节。A16 的组名及配额以匹配原厂 payload 和 LP 布局为准。
