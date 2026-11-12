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
