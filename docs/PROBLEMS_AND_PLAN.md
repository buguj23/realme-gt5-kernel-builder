# Realme GT5（ossi / SM8550）ROM + 内核：问题取证与达成方案

版本：2026-11-12
设备：RMX3820 / RE5C33 / ossi（kalama，SM8550）
现场：设备反复重启（realme 标 → 黑屏 → realme 标），偶发落入 fastboot / EDL(9008)。

---

## 0. 摘要

- **不是单一镜像损坏**，而是「构建产物混版 + 分区元数据/fstab 不一致 + 内核与模块 ABI 不兼容」三条链路同时断裂。
- 设备当前所有可刷镜像（fastboot 包、OTA 包）都失败，说明现有产物集合无法组成一个自洽系统。
- 达成"完美 ROM + 内核"的唯一可靠方式：**在同一棵 AOSP 源树内同时构建 ROM、内核与全部内核模块**，并以固定的刷写协议落盘。本文件给出完整方案与 SOP。

---

## 1. 现场时间线与证据

### 1.1 我们做过的操作（按序）

1. 从 fastboot 包容目录刷入：boot / init_boot / dtbo / recovery / vendor_boot / vbmeta* ；
2. 写 `super_empty.img`（bootloader 模式），再在 fastbootd 刷 7 个逻辑分区；
3. 启动失败 → 槽位在 A/B 之间反复回退；
4. 尝试 OTA sideload → 失败（status 7）；
5. 擦除/格式化 metadata、wipe userdata；
6. 刷入 OrangeFox（未签名）→ recovery 不启动；
7. 刷入签名版 OrangeFox / 类原生调试 recovery → 可启动；
8. 对比发现 vendor_boot 与设备原镜像不同（fstab 差异）；
9. 从 OTA 包解出全部 15 个分区镜像，完整刷入 A 槽（同源自洽）→ 仍反复重启。

### 1.2 关键证据

**(a) metadata 挂载失败（recovery 屏幕原文）**
```
ERROR: recovery: [libfs_mgr] Failed to mount /metadata: File exists
ERROR: recovery: [libfs_mgr] Failed to mount for path [/metadata/ota]
ERROR: recovery: Cannot mount /metadata/ota
ERROR: Error applying update: 7 (ErrorCode::kInstallDeviceOpenError)
ERROR: recovery: Error in /sideload/package.zip (status 7)
```

**(b) vendor_boot 内 fstab 差异（设备原镜像 vs 包内镜像，唯一差异文件）**
```
# 设备原始（能启动）:
/dev/block/by-name/metadata  /metadata  ext4  ...
system  /system  ext4 ... wait,slotselect,logical,first_stage_mount

# 包内/OTA/调试 recovery（新构建）:
/dev/block/by-name/metadata  /metadata  f2fs  ...
system  /system  ext4 ... wait,slotselect,avb=vbmeta_system,logical,first_stage_mount,avb_keys=/avb/q-gsi.avbpubkey:...
```
→ 同一设备上出现 **ext4 / f2fs 两代 fstab**，混刷必然挂载失败。

**(c) fastbootd 依赖 recovery**
```
fastboot: error: Failed to boot into userspace fastboot; one or more components might be unbootable.
```
→ OrangeFox/TWRP 不提供 fastbootd；刷入它后 `fastboot reboot fastboot` 必然失败。
→ 能提供 fastbootd 的是 **ROM 自带 recovery** 或 **带 fastbootd 的调试 recovery**。

**(d) 槽位与重试计数**
```
slot-retry-count:a: 1     # 最初仅剩 1 次
slot-retry-count:b: 7     # 后来 B 被写满
slot-unbootable:b: yes    # B 被标记不可引导
current-slot: b / a 交替  # 失败回退导致"反复重启"
```
→ "反复重启"多数是**引导器 A/B 回退重试**，不是系统本身重启循环。

**(e) EDL 回退**
```
Bus 001 Device 038: ID 05c6:9008 Qualcomm, Inc. Gobi Wireless Modem (QDL mode)
```
→ 连续启动失败后 ABL 落入 EDL；断电重插 + 音量下+电源 可退出回 fastboot。

**(f) 内核与模块 CRC 不兼容（自建内核）**
```
module_layout: ours=0xd0a49378 rom=0xedfc7a5c
RESULT: INCOMPATIBLE (6571 refs)
```
→ 仅对齐 vermagic 不够，modversions 的 **CRC 由源码结构体/配置决定**。

---

## 2. 根因清单

### 问题 1：fastboot 包是"混版拼装"
包目录时间戳显示不同构建：
```
dtbo 11/11 16:27 | init_boot/vendor_dlkm 11/11 20:07 | boot 11/12 00:23
vendor_boot 11/12 00:59 | system/vendor/odm/product/system_ext 11/12 12:21
vbmeta 11/12 12:23 | super_empty 11/11 19:37
```
且 `vendor_boot` 的 fstab（f2fs）与设备原镜像（ext4）不同 → **组件不同源**。

### 问题 2：metadata 文件系统类型与 fstab 不匹配
- 设备原装为 ext4 构建；后续包/OTA/recovery 为 f2fs 构建。
- 混用 → `/metadata` 挂载 EEXIST/EINVAL → 首阶段初始化失败 → 黑屏/循环；OTA 也会 error 7。
- `fastboot -w` 会按**当前 vendor_boot 的 fstab** 格式化 metadata，进一步放大不一致。

### 问题 3：super 动态分区元数据与槽位操作不规范
- `fastboot flash super super_empty.img` 只写 5KB，必须随后 **resize/create** 再刷逻辑分区；
- 不指定槽位时，fastboot 按 `current-slot` 解析，槽位判断错误会刷到另一槽；
- 失败回退会把另一槽标记 unbootable，造成"永远起不来"。

### 问题 4：第三方 recovery 未签名 / 无 fastbootd
- 未签名 OrangeFox 刷入后不启动；
- OrangeFox 不提供 userspace fastbootd；
- 正确组合：**recovery = 签名版 OrangeFox 或 ROM 原 recovery**；fastbootd 用 ROM recovery。

### 问题 5：内核基线选择与模块 ABI
- 第一版基于 Ace2Pro **5.15.180**（同 SoC BSP），ROM 内是 **5.15.200**（fork@a1403aca）；
- 已切到 5.15.200 并锁定 vermagic `5.15.200-ga1403aca1412-dirty`；
- 但 ROM 内核叠加了 **SukiSU + SUSFS + Re-Kernel**（SUSFS 改 task_struct/super_block 等），
  自建内核（YukiSU LKM 形态）结构布局不同 → `module_layout` 等 CRC 全不一致 → 现有模块无法加载。

### 问题 6：ex-module 无法脱离 ROM 构建体系
缺失 36 个关键模块：`msm_drm / msm_kgsl / msm_video / msm-eva / qca_cld3_kiwi / cnss2 /
btpower / audio *_dlkm / camera / rmnet_* / qcedev / qcrypto` 等。
它们来自 `sm8550-modules/qcom/opensource/*`，由 **Soong** 注入 `DISPLAY_ROOT`、`CONFIG_*` 等参数编译；
裸 kbuild 会因缺 `clk-regmap.h` 等头文件失败。

### 问题 7：recovery 的 adb 授权状态
- 未授权时无法读 `/tmp/recovery.log`；
- 调试 recovery 可 `adb root`（关键取证手段）。

---

## 3. 为什么"所有镜像都启动不了"

1. 混版包 → fstab/metadata 不一致 → 首阶段挂载失败；
2. 失败后引导器回退到另一槽（空/旧），再次失败 → 循环；
3. OTA sideload 因 metadata 挂载失败而在传输后报 error 7（B 槽从未创建，`partition-size:*_b` 报 `Could not open partition` 可证）；
4. 自建内核因 CRC 不兼容，无法与现有模块配套。

> 结论：当前设备上**不存在一套完整且彼此自洽的镜像集合**。必须先"归一"，再谈启动。

---

## 4. 达成"完美 ROM + 内核"的方案（推荐）

### 4.1 单一源树（Single Source of Truth）
在 ROM 的 AOSP 树内完成全部构建：

```
AOSP/device/oneplus/sm8550-common      # 设备树（ossi）
AOSP/kernel/oneplus/sm8550             # 内核 common：fork@a1403aca（含本次补丁）
AOSP/kernel/oneplus/sm8550-modules     # 16.0 分支（oplus 驱动）
AOSP/... qcom/opensource/*-kernel      # ex-module（display/graphics/video/wlan/bt/audio/camera/dataipa/securemsm）
```

命令：
```bash
source build/envsetup.sh && lunch infinity_ossi-userdebug
m bacon            # 产出单一自洽的 OTA zip
# 或分步：
m bootimage vendor_bootimage vendor_dlkmimage system_dlkmimage recoveryimage
```

**禁止**：从不同构建目录拼装 fastboot 包；时间戳不一致的镜像不得混用。

### 4.2 内核集成（在源树内打补丁）
统一补丁集（本仓库 `scripts/10-patch.sh` 可直接复用）：
- YukiSU LKM + Kasumi（CONFIG_KSU=m）
- Re-Kernel（drivers/rekernel）
- MidAS ghost-task（kernel/pid.c）
- ZRAM lz4kd + lz4k_oplus
- 容器配置（namespaces/cgroup/squashfs/overlayfs/ipset…）
- 内核符号导出（SELinux/BTF/kallsyms/path/VFS，47 项）
- `.scmversion = -ga1403aca1412-dirty`（与 ROM 内核 vermagic 一致）

配置基线：**ROM 内核内嵌 IKCONFIG**（`configs/gki_defconfig.rom`），保证与 ROM 驱动生态一致。

### 4.3 模块完整性校验（发布门槛）
```bash
scripts/40-verify-crc.py  out/dist/Module.symvers  out/vendor_dlkm/modules
# 必须输出 COMPATIBLE，否则禁止产出刷机包
```
同时校验：
```bash
# 缺失模块清单（应与 ROM 模块列表全量匹配）
comm -23 rom_modules.txt built_modules.txt
```

### 4.4 刷写 SOP（标准作业程序）
```bash
# 0) 备份
adb shell su -c 'dd if=/dev/block/by-name/boot_a of=/sdcard/boot_a.img'
# 1) 确认槽位与解锁状态
fastboot getvar current-slot unlocked slot-retry-count:a
fastboot --set-active=a
# 2) 物理分区（bootloader）
fastboot flash boot_a boot.img
fastboot flash init_boot_a init_boot.img
fastboot flash dtbo_a dtbo.img
fastboot flash vendor_boot_a vendor_boot.img
fastboot flash vbmeta_a vbmeta.img          # flags=3（禁用校验）
fastboot flash vbmeta_system_a vbmeta_system.img
fastboot flash vbmeta_vendor_a vbmeta_vendor.img
fastboot flash recovery_a recovery.img       # 需支持 fastbootd
# 3) super 元数据（bootloader，写 empty 后必须 resize）
fastboot flash super super_empty.img
fastboot reboot fastboot
# 4) 逻辑分区（fastbootd，逐分区 resize + flash）
for p in system system_ext product vendor odm system_dlkm vendor_dlkm; do
  fastboot resize-logical-partition ${p}_a $(stat -c%s $p.img)
  fastboot flash ${p}_a $p.img
done
# 5) metadata 必须与 vendor_boot 的 fstab 一致（ext4 或 f2fs 二选一）
#    由 ROM 自带 recovery 的 “Wipe data/factory reset” 完成格式化最稳
fastboot reboot
```

### 4.5 回滚与救援
- 保留：`boot_a / vendor_boot_a / dtbo_a / init_boot_a / vbmeta*` 原始镜像；
- 落入 EDL(9008)：断电重插 + 音量下+电源 可回 fastboot；
- 彻底救援：官方全量包（8.4GB OTA）经 stock recovery sideload 恢复官方基线，再装自建 ROM。

---

## 5. 关于"内核是 180？"

- 第一版内核：`5.15.180-gdc4a4a133fda`（Ace2Pro BSP，与原厂 GT5 同版），用于快速验证；
- ROM 内实际内核：`5.15.200-ga1403aca1412-dirty`（fork@a1403aca + SukiSU/SUSFS/Re-Kernel）；
- 第二版内核：已切到 **5.15.200**，vermagic 精确对齐（`.scmversion`），但 **CRC 仍不兼容**（见 1.2f）；
- 因此"内核版本号对上了"≠"模块能用"。必须同源构建（4.1/4.2）。

---

## 6. 下一步（按优先级）

1. **恢复可启动状态**：优先使用官方全量包恢复基线（最快、最确定），再装自建 ROM；
2. 在**同一源树**内重建 ROM + 内核 + 全部模块（4.1/4.2）；
3. 用 4.3 的 CRC/模块清单校验作为**发布门槛**；
4. 按 4.4 SOP 刷写，刷前备份、刷后验证 `uname -r` 与 `lsmod`；
5. 若继续自建内核，必须同时产出配套的 `vendor_boot`（首阶段模块）、`vendor_dlkm`、`system_dlkm`，**三者与内核同构**。

---

## 附录 A：本次产出（已归档）

| 文件 | 说明 |
|---|---|
| `~/gt5_kernel_ab/kernel_platform/out200/dist/Image` | 5.15.200-ga1403aca1412-dirty 内核（YukiSU/Re-Kernel/MidAS/lz4kd） |
| `~/gt5_infinity_workspace/kernel_deliver/` | boot/vendor_boot/vendor_dlkm/system_dlkm 打包产物 |
| `~/gt5_infinity_workspace/kernel_flash_backup/` | 设备原始分区备份 |
| `~/gt5_infinity_workspace/rom_check/ota_all/` | OTA 全量 15 个分区镜像 |
| `~/gt5_infinity_workspace/recovery_fix/` | 可用（签名）OrangeFox 与类原生调试 recovery |

## 附录 B：刷写检查表

- [ ] `fastboot getvar unlocked` = yes
- [ ] `fastboot getvar current-slot` 与目标槽一致
- [ ] `slot-retry-count` > 0
- [ ] vendor_boot 的 fstab metadata 类型与 metadata 分区实际类型一致
- [ ] super 为空时先 `flash super super_empty.img`，再逐分区 `resize`
- [ ] 刷完 `fastboot getvar partition-size:<part>_a` 非 0
- [ ] 首启前 metadata 已按 fstab 格式化
- [ ] 内核与模块 CRC 校验 COMPATIBLE

---

# 第二部分：上游 / 缺失 / 检查 / 错误点（细化）

## 7. 应使用的上游（精确到仓库、分支、提交）

### 7.1 内核（common，5.15.200）
| 项 | 值 |
|---|---|
| 仓库 | `https://github.com/himanshusaini010/kernel_oneplus_sm8550` |
| 分支 | `16.0` |
| 提交 | `a1403aca1412a58085fa438eb386a111efe90e29` |
| 版本 | `5.15.200-ga1403aca1412-dirty`（与该提交 + 未提交修改一致） |
| 说明 | 该 fork 是 ROM 内实际内核的来源（vermagic 的 `ga1403aca1412` 与之吻合）。OnePlusOSS 官方 `android_kernel_common_oneplus_sm8550` 的 `16.0.0_*` 分支为 5.15.180/197，**不是** ROM 内核。 |

### 7.2 厂商模块源码
| 项 | 值 |
|---|---|
| 仓库 | `https://github.com/himanshusaini010/android_kernel_oneplus_sm8550-modules` |
| 分支 | `16.0` |
| 内容 | `oplus/kernel/*`（charger/touchpanel/vibrator/device_info/dfr/dft/boot/secure…）与 `qcom/opensource/*`（audio-kernel、bt-kernel、camera-kernel、wlan、display-drivers、graphics-kernel、video-driver、dataipa、datarmnet、mm-drivers、mmrm-driver、securemsm-kernel、eva-kernel） |

### 7.3 设备树（ROM 侧）
| 项 | 值 |
|---|---|
| 目录 | `device/oplus/sm8550-common`（工作区参考副本：`reference_sm8550_common/`） |
| 关键变量 | `TARGET_KERNEL_SOURCE := kernel/oneplus/sm8550`；`TARGET_KERNEL_EXT_MODULE_ROOT := kernel/oneplus/sm8550-modules`；`PREBUILT_DTB_DTBO_DIR := device/oneplus/sm8550-kernel` |
| 依赖声明 | `lineage.dependencies` 指向 `android_kernel_oneplus_sm8550`、`-devicetrees`、`-modules` |

### 7.4 构建系统（GKI/kleaf）
| 项 | 值 |
|---|---|
| 来源 | OnePlusOSS kernel_platform manifest（本机 `kernel_platform/` 已含 build/ 与 prebuilts/） |
| 关键文件 | `common/build.config.gki.aarch64`、`common/arch/arm64/configs/gki_defconfig`、`build/kernel/build.sh` |
| 编译器 | `prebuilts/clang/host/linux-x86/clang-r450784e`（clang 14.0.7） |

### 7.5 ROM
| 项 | 值 |
|---|---|
| 项目 | Project Infinity-X 3.12 ossi（GAPPS, UNOFFICIAL） |
| 现有产物 | `Project_Infinity-X-3.12-ossi-11.11.2026-GAPPS-UNOFFICIAL.zip`（2.4GB，A/B OTA，AOSP testkey） |
| 发布源 | `https://sourceforge.net/projects/infinity-x/files/ossi/16/gapps/`（zip 内 json 记录） |

---

## 8. 缺失清单（必须补齐才可能"完美"）

### 8.1 本地缺失：完整 ROM 构建树
工作区只有 `device/`、`vendor/`、`prebuilts/` 片段；缺 `build/`、`frameworks/`、`system/`、`packages/`、`external/`、`art/`、`bionic/` 等——**无法本地 `m bacon`**。

### 8.2 缺失的内核模块（36 个，ROM 的 `vendor_dlkm` 中存在，自建缺失）
```
msm_drm msm_kgsl msm_video msm-eva
qca_cld3_kiwi_v2 cnss2 cnss_nl cnss_plat_ipc_qmi_svc cnss_prealloc cnss_utils
bt_fm_slim btpower radio-i2c-rtc6226-qca
adsp_loader_dlkm audio_pkt_dlkm audio_prm_dlkm audpkt_ion_dlkm
lpass_cdc_tx_macro_dlkm lpass_cdc_va_macro_dlkm lpass_cdc_wsa_macro_dlkm lpass_cdc_wsa2_macro_dlkm
machine_dlkm q6_dlkm pinctrl_lpi_dlkm stub_dlkm swr_dmic_dlkm swr_haptics_dlkm wcd938x_slave_dlkm
camera nxp-nci qcedev-mod_dlkm qcrypto-msm_dlkm
rmnet_aps rmnet_offload rmnet_perf rmnet_perf_tether rmnet_sch rmnet_shs rmnet_wlan
ipa_clientsm ipanetm hdmi_dlkm tz_log_dlkm oplus_audio_tfa98xx_v6
```
来源：`sm8550-modules/qcom/opensource/{display-drivers,graphics-kernel,video-driver,eva-kernel,wlan,bt-kernel,audio-kernel,camera-kernel,dataipa,datarmnet,securemsm-kernel}`。

### 8.3 缺失/不可用的构建产物
- 与 12:21 系统镜像**同源**的 `vendor_boot`（包内是 f2fs 版，设备原装是 ext4 版）；
- 原厂 `super.img`（或原始 dynamic partition 元数据），本机只有 `super_empty.img`；
- SM8550 firehose programmer（EDL 刷写需要，本机无）；
- 签名版 OrangeFox 之外的第三方 recovery（未签名版无法启动）。

---

## 9. 检查清单（命令级，任何发布前必须全绿）

### 9.1 镜像自洽性
```bash
# 1) 所有镜像必须来自同一次构建：对比构建时间/哈希，不要在包目录里混用
sha256sum boot.img vendor_boot.img system.img vendor.img odm.img product.img system_ext.img \
          system_dlkm.img vendor_dlkm.img vbmeta*.img
# 2) vendor_boot 的 fstab 与 metadata 实际文件系统必须一致
#    （解包 vendor_ramdisk00 → system/etc/fstab.default，查 by-name/metadata 的 type）
# 3) 内核与模块的 vermagic 必须一致
strings Image | grep -m1 '5\.15\.'
modinfo vendor_dlkm/modules/*.ko | grep vermagic | sort -u
```
### 9.2 模块 ABI（发布门槛）
```bash
# 必须 0 mismatch，否则禁止出包
scripts/40-verify-crc.py out/Module.symvers out/vendor_dlkm/modules
# 模块覆盖度：与 ROM 清单做差集，必须为空
comm -23 rom_modules.txt built_modules.txt
```
### 9.3 super / 分区
```bash
fastboot getvar current-slot
fastboot getvar slot-retry-count:a slot-retry-count:b
fastboot getvar partition-size:system_a partition-size:system_b
# super 元数据魔数（offset 4096）应为 30 50 4c 41（"0PLA"）
adb shell "dd if=/dev/block/by-name/super bs=4096 skip=1 count=1 | od -An -tx1 -N8"
```
### 9.4 刷写前
```bash
fastboot getvar unlocked        # 必须 yes
fastboot getvar secure          # 参考值（不决定解锁）
# 备份：boot_a/vendor_boot_a/dtbo_a/init_boot_a/vbmeta*
```
### 9.5 启动后
```bash
adb shell getprop sys.boot_completed
adb shell uname -r
adb shell lsmod | head
adb shell dmesg | grep -iE "avb|verity|metadata|panic"
```

---

## 10. 已知错误点（逐条：现象 → 证据 → 正确做法）

1. **混版 fastboot 包**
   - 现象：刷完即黑屏/循环。
   - 证据：包内文件时间戳跨 11/11 16:27 → 11/12 12:23；vendor_boot 与设备原镜像 fstab 不同。
   - 正确：一次构建产出一个包；`super_empty.img` 必须与系统镜像同源。

2. **metadata 文件系统与 fstab 不匹配（ext4 vs f2fs）**
   - 现象：`Failed to mount /metadata: File exists` → `Cannot mount /metadata/ota` → OTA `ErrorCode::kInstallDeviceOpenError` (status 7)。
   - 证据：设备原 vendor_boot fstab=ext4；包/OTA/recovery fstab=f2fs。
   - 正确：先用**与目标 ROM 同源**的 recovery 格式化 metadata 为目标类型，再刷同源镜像。

3. **super 刷写方式错误**
   - 现象：逻辑分区不存在或启动失败（`Could not open partition`）。
   - 证据：`fastboot flash super super_empty.img` 后未 `resize/create` 就刷；或槽位不对。
   - 正确：bootloader 写 `super_empty` → `fastboot reboot fastboot` → 每个逻辑分区 `resize-logical-partition` → `flash`。

4. **槽位与重试**
   - 现象：反复重启（realme 标→黑屏→realme 标）。
   - 证据：`slot-retry-count:a=1`、`slot-unbootable:b=yes`、`current-slot` 在 a/b 间跳变。
   - 正确：`fastboot --set-active=a` 复位重试；刷写时显式带 `_a`；失败后不要反复试同一槽。

5. **第三方 recovery 未签名 / 不支持 fastbootd**
   - 现象：刷入后不启动；`fastboot reboot fastboot` 报 "components unbootable"。
   - 正确：使用**签名版** `OrangeFox-GT5-TouchFixed-Signed.img`；需要 fastbootd 时用 ROM 自带 recovery。

6. **内核模块 ABI 不兼容（核心问题）**
   - 现象：自建内核启动到首阶段即失败/黑屏；或模块无法加载。
   - 证据：`module_layout` CRC 不同；6571 处 CRC 不匹配。
   - 原因：ROM 内核 = fork@a1403aca + **SukiSU + SUSFS + Re-Kernel**（SUSFS 改 `task_struct/super_block`）；自建内核为 YukiSU LKM 形态，结构布局不同。
   - 正确：**在同一源树、同一补丁集、同一配置**下产出内核与全部模块；vermagic 只是第一道门，CRC 才是加载判据。

7. **ex-module 不能裸 kbuild**
   - 现象：`display-drivers` 编译失败（缺 `clk-regmap.h`）。
   - 原因：依赖 msm-kernel 头文件与 Soong 注入的 `DISPLAY_ROOT` / `CONFIG_DRM_MSM=m` 等。
   - 正确：在 ROM 树内由 Soong 编译（`Android.bp` 的 `kernel_module`）。

8. **GKI 模块清单 / KMI 严格模式**
   - 现象：`ERROR: modules list out of date`、`Differences between ksymtab and symbol list detected`。
   - 正确：新增 `kernelsu.ko/rekernel.ko` 后同步 `common/android/gki_aarch64_modules`；自建内核发布时设 `KMI_SYMBOL_LIST_STRICT_MODE=0`（或正式更新 KMI 列表）。

9. **模块签名工具链不兼容**
   - 现象：`sign-file: OpenSSL 1.1.1 (compatible; BoringSSL) only supports SHA1 signing`。
   - 正确：`CONFIG_MODULE_SIG_ALL=n`（保留 SIG=y，不强制签名）；或升级 `scripts/sign-file.c` 以支持 OpenSSL 3 + SHA512。

10. **CONFIG_KSU=y 与 YukiSU(=m) 冲突**
    - 现象：ROM 配置里 `CONFIG_KSU=y`（SukiSU 内建），YukiSU Kconfig 要求 `=m`。
    - 正确：二选一——沿用内建 SukiSU（不改内核），或以 YukiSU LKM 替换（必须同源重编全部模块）。

11. **defconfig 校验阻断构建**
    - 现象：`check_defconfig` 失败。
    - 正确：`sed -i 's/check_defconfig//' common/build.config.gki`（自建内核场景）。

12. **EDL 回退**
    - 现象：`05c6:9008`，USB 无 adb/fastboot。
    - 正确：断电重插 + 音量下+电源 回 fastboot；彻底救援用官方全量包 sideload。

---

## 11. 判定表：什么情况下才算"完美"

| 维度 | 通过标准 |
|---|---|
| 镜像同源 | 所有分区镜像来自同一构建（时间戳/哈希可追溯）|
| fstab 一致 | vendor_boot 的 metadata 类型 == 实际格式化类型 |
| super 正确 | 逻辑分区全部存在且尺寸 ≥ 镜像，元数据魔数合法 |
| 内核同构 | vermagic 一致 **且** CRC 校验 0 mismatch **且** 模块覆盖度 100% |
| 引导健康 | 连续 3 次正常启动，`slot-retry-count` 不递减，无 EDL 回退 |
| 功能完整 | 显示/GPU/WiFi/BT/音频/相机/移动数据/传感器全部可用 |
| 可回滚 | 每步有备份，能在 10 分钟内回到已知良好状态 |
