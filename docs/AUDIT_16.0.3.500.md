# 内核与 ROM 审计（16.0.3.500 全量包）

审计对象：`ida_rom/Image`（官方 boot 内核）、`16.0.3.500/images/*.img`、`ida_rom/init`（官方 init）。
工具：IDA Pro 9.4（init 符号级分析）+ `vmlinux-to-elf`（从 Image 恢复 kallsyms）+ IKCONFIG 抽取 + EROFS 实解。

## 1. 官方内核身份

| 项 | 实测值 |
|---|---|
| 格式 | 未压缩 ARM64 Image（magic `ARM\x64` @0x38） |
| 版本串 | `5.15.180-android13-8-o-01176-g6333b0dbc8ed` |
| 编译 | clang 14.0.7 / LLD 14.0.7，`#1 SMP PREEMPT ... 2025-12-12` |
| IKCONFIG | 存在（`IKCFG_ST`@0x1c74720 … `IKCFG_ED`），6996 行 |
| 恢复符号 | `vmlinux-to-elf` 得到 100,093 个 FUNC，`__ksymtab_*` 8,449 个 |
| KSU 痕迹 | `CONFIG_KSU` 0 条、符号表 `kernelsu|ksu_|susfs` 0 条 |

官方配置已落到 `configs/reference/rom_ikconfig.defconfig`（sha256 `91124701704d20d1…`）。

> 修正：该文件此前是 **5.15.200** 的配置且含 `CONFIG_KSU=y` / `CONFIG_OPLUS_SYSTEM_KERNEL_QCOM=y`，与 GT5 16.0.3.500 无关，会误导对照。已替换为上面这份真值。

LKM 前提（官方全部满足）：`MODULES=y` `KALLSYMS_ALL=y` `KPROBES=y` `KRETPROBES=y` `HAVE_SYSCALL_TRACEPOINTS=y` `COMPAT=y`；模块只有两个：`ZSMALLOC=m`、`ZRAM=m`。

## 2. 符号导出（build #8 的直接原因）

Build #8 死在 modpost，6 个符号 `undefined`。在官方内核符号表里逐个核对：

| 符号 | 定义 | 导出 |
|---|---|---|
| `task_work_cancel_match` | 有 | **无** |
| `__tracepoint_sched_process_free` | 有 | **无** |
| `__tracepoint_sched_process_fork` | 有 | **无** |
| `security_validate_transition` | 有 | **无** |
| `audit_log_n_untrustedstring` | 有 | **无** |
| `cap_capable` | 有 | **无** |

三个 OnePlusOSS sm8550 分支（`u_14.0.0_oneplus11`、`v_15.0.0_ace_2_pro`、`b_16.0.0_ace_2_pro`）逐一核对：4 个普通符号都在注释里的同一文件、`exported=0`；两个 tracepoint 在 `kernel/sched/core.c` 的 `CREATE_TRACE_POINTS` 处实例化，且该文件已有 `EXPORT_TRACEPOINT_SYMBOL_GPL(sched_switch)` 等同类导出的先例。

修复：`scripts/integrate-yukisu.sh` 增加 4 条 `exp()` 与一个 `exptp()`。`exptp()` 最终形态是**跨编译单元导出**：往 `kernel/sched/core.c` 追加

```c
extern struct tracepoint __tracepoint_sys_enter;
EXPORT_SYMBOL_GPL(__tracepoint_sys_enter);
```

原因来自两次实跑的对照：写进 `kernel/sched/core.c` 的导出生效（`sched_process_free/fork` 不再报错），写进 `kernel/entry/common.c` 的不生效（`sys_enter` 仍 undefined）——后者只在 `CONFIG_GENERIC_ENTRY` 下参与构建，arm64 不编它。`EXPORT_SYMBOL_GPL` 只需要符号地址，不需要同 TU 定义，因此不必再猜实例化文件。两者均幂等，且会跳过其他编译单元已导出的符号。

## 3. fstab 解析链（IDA：`init`）

`android::fs_mgr::ReadDefaultFstab`（0x30c014）伪代码给出的确定顺序：

1. `ReadFstabFromDt()` — 从 device tree 的 `android,fstab`
2. 若存在 `/system/bin/recovery` → 直接用 `/etc/recovery.fstab`，**覆盖后续全部**
3. 否则按后缀候选 `fstab_suffix` → `hardware` → `hardware.platform`（0x210107 处字符串确认为 `hardware`），对每个后缀依次尝试：
   `/odm/etc/fstab.<s>`、`/vendor/etc/fstab.<s>`、`/system/etc/fstab.<s>`、`/first_stage_ramdisk/system/etc/fstab.<s>`、`/fstab.<s>`、`/first_stage_ramdisk/fstab.<s>`

`fs_mgr_get_boot_config`（0x313cd8）解析顺序：DT `<dir>/<key>` → `ro.boot.<key>` → bootconfig → cmdline。

本机实测：

| 事实 | 值 |
|---|---|
| bootconfig | 只有 `androidboot.hardware=qcom` |
| 后缀来源 | `ro.boot.hardware=qcom` → 后缀 **qcom** |
| `/system/bin/recovery` | **不存在**（独立 recovery 分区）→ 不走 recovery.fstab |
| DT `android,fstab` | 只声明 `vendor`（ext4，`wait,slotselect,avb`） |
| ramdisk 根 | `fstab.qcom` 存在（vendor_boot ramdisk） |

结论：`fstab.qcom` **是活的**，但依赖 `androidboot.hardware=qcom` 提供后缀；ROM 侧必须保留该 bootconfig/cmdline 项，否则只剩 DT 的 `vendor` 一个挂载项。14.0.0.1120 与 15/16 的 init 二进制不同（BuildID 不同），但五个搜索路径与两个后缀 key 完全一致。

官方 fstab 对 `system/product/vendor/system_dlkm/vendor_dlkm/odm/my_*` 均给 **ext4 + erofs 双条目**；本仓库 `rom/device/realme/ossi/fstab.default` 对 dlkm 也保留双条目，方向一致。

## 4. 模块加载链与换内核风险

构建产物实测（`AnyKernel3_YukiSU_OGKI_5.15.180` 工件内）：

| 项 | 值 |
|---|---|
| 我们 Image | `5.15.180-android13-10-o-g407e0678311e43` |
| stock Image | `5.15.180-android13-8-o-01176-g6333b0dbc8ed` |
| 我们 kernelsu.ko | `vermagic=5.15.180-android13-10-o-g407e0678311e43 SMP preempt mod_unload modversions aarch64` |

KMI 代次（10 vs 8）与整串 release 都不同。vermagic 比较的是完整 `UTS_RELEASE`，加上 `CONFIG_MODVERSIONS=y` 的符号 CRC，stock `system_dlkm` 的 `zram.ko`/`zsmalloc.ko` 不可能被我们的 Image 接受。工作流已加入构建期 `::warning::KMI mismatch`，并在日志里同时打印 Image banner 与 kernelsu.ko vermagic。

| 事实 | 证据 |
|---|---|
| 清单 | `vendor_boot` ramdisk：`modules.load`、`modules.load.recovery`、`modules.blocklist` |
| 实体 | `system_dlkm/lib/modules/5.15.180-android13-8-o-01176-g6333b0dbc8ed/kernel/{mm/zsmalloc.ko,drivers/block/zram/zram.ko}` |
| 加载点 | `Modprobe::Insmod`（0x304da0）→ `finit_module`；`errno==17`（EEXIST）视为成功 |
| 失败处理 | `FirstStageMain` 中 `Failed to load kernel modules` 与已知 FATAL 的 `Failed to mount required partitions early` 使用同一 severity 常量，且本 init 不含 `, starting console` 分支 |

因此：**只刷 boot Image 而不提供同源 `zram.ko`/`zsmalloc.ko`**，stock 模块会因 vermagic/CRC 不符返回 EINVAL（不是 EEXIST），第一阶段判失败。两条可行路线：

- ROM 构建：`system_dlkm` 与内核同树同编，天然一致（推荐）。
- 仅刷内核（AnyKernel3）：必须同时处理 `vendor_boot` 的 `modules.load`，或改用与 ROM 同源的 `system_dlkm`；否则有 boot loop 风险。

`kernelsu.ko` 不走这条路：`ksud` late-load 依次取内嵌资源、`/data/adb/ksu/kernelsu.ko`、`/data/adb/ksu/bin/kernelsu.ko`、`/data/local/tmp/kernelsu.ko`（`userspace/ksud/src/late_load.cpp`），boot patch 场景才会把它塞进 ramdisk。此前 `device.mk` 里 `vendor_dlkm/lib/modules/kernelsu.ko` 的拷贝、对应 sepolicy 标签、以及 `write /sys/module/kernelsu/parameters/enable 1`（YukiSU 无该参数）都不在任何加载路径上，已删除。

## 5. ROM ELF 清点（odm + vendor）

| 项 | 值 |
|---|---|
| 文件总数 | odm 2696 / vendor 3504 |
| ELF 架构 | aarch64 2110、arm32 1367、Hexagon(EM 164) 53、EM 94 15 |
| ELF 类型 | DYN 3512、EXEC 30 |
| setuid | 无 |
| 32 位实例 | `vendor/lib` 918 项、含显示 HAL `vendor.pixelworks.hardware.display@1.x.so`（32 位） |

交叉结论：32 位 HAL 存在 → 内核必须保留 `CONFIG_COMPAT`。官方 `COMPAT=y`；三个分支的 OEM `gki_defconfig` 均 `CONFIG_COMPAT=y`，本仓库 overlay 未覆盖 → 保持成立。

异常与误报：

- `odm/lib64/libAncHumanRetain.so` 实为 **32 位 ARM 库放在 lib64**（官方打包瑕疵，不影响我们）。
- `vendor/firmware/dpAP_{full,mini,modemssr}.mbn` 仅以 ELF 魔数开头，实为 modem 固件，不是 ELF（e_type=0），不计为缺陷。

## 6. 构建矩阵实证（本轮）

四个版本并行构建后的产物核对：

| run 输入 | 产物名 | Image 实际版本 | KMI |
|---|---|---|---|
| 5.15.180 | `...(5.15.180)` | `5.15.180-android13-10-o-g407e0678…` | android13-10 |
| 5.15.167 | `...(5.15.167)` | `5.15.167-android13-4-o-g42ebb4fd…` | android13-4 |
| 5.15.149（修复前） | `...(5.15.167)` | `5.15.167-android13-8-o-g124e2301…` | android13-8 |
| 5.15.149（修复后） | `...(5.15.149)` | `5.15.149-android13-6-o-g9cf837fc…` | android13-6 |
| 5.15.123 | 见 §2 | — | — |

两条问题：

1. **149 实际建成 167**：`FILE→版本` 映射把 `RESUBLEVEL=149` 写进 `$GITHUB_ENV`，但版本步骤又用 `${{ github.event.inputs.RESUBLEVEL }}`（默认空串）覆盖同名变量，于是走「保持默认」。已改为「显式输入优先，否则用映射值」；重跑产物确为 `5.15.149-android13-6-…`。
2. **KMI 代次随之变化**：5.15.149 从 8 变 6，5.15.167 为 4，5.15.180 为 10，而 stock 16.0.3.500 是 **android13-8**。vermagic 必须与目标 ROM 的 `system_dlkm` 完全一致，所以按 ROM 选分支比按 SUBLEVEL 选更重要。

## 7. 本轮改动


| 文件 | 改动 |
|---|---|
| `scripts/integrate-yukisu.sh` | 导出 modpost 拒绝的 6 个符号；新增 `exptp()`（tracepoint 专用、幂等） |
| `configs/reference/rom_ikconfig.defconfig` | 由 5.15.200（含 `CONFIG_KSU=y`）替换为 16.0.3.500 的 5.15.180 真值 |
| `.github/workflows/build-kernel-gt5.yml` | 构建期打印 Image banner / ko vermagic；KMI 与 stock 不符时 `::warning::`；SUBLEVEL 映射回退 |
| `rom/device/realme/ossi/{device.mk,init.ossi.rc,sepolicy/vendor/file_contexts,prebuilt/README.md}` | 删除 `vendor_dlkm/lib/modules/kernelsu.ko` 及其标签、无效的 `enable` sysfs 写入 |

验证方式：本地假树跑 `exp()/exptp()`，确认追加正确、二次执行不重复、已导出符号被跳过；四个版本各触发一次 CI 实跑。
