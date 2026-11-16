# 真我 GT5 手机安全分层（官方全量包实测）

对象：RMX3820 / RE5C33 / 工程 22635。依据五份官方 CN 全量包 + 仓库现状。
**不保证**「随便刷都没事」。保证的是：按本文件做，不会再踩已经核实过的砖点。

## L0 身份

五份包 `product_name=RMX3820` `pre-device=RE5C33` `oplus_separate_soft=22635`。
别的机型（Ace2 Pro salami / 一加 11）同 SoC 不等于可刷。

## L1 引导链 / AVB

| 项 | 官方实测 |
|---|---|
| 槽位 | A/B。失败会减 `slot-retry-count`，到 0 切槽或 EDL 9008 |
| vbmeta | 12KiB，flags=**0**（校验开） |
| 自定义 boot | 必须关 vbmeta 校验（flags=3 或 AK3 `PATCH_VBMETA_FLAG=auto`），**不要换公钥文件** |
| 解锁 | `fastboot getvar unlocked=yes` 才允许写 boot |

## L2 第一阶段挂载（vendor_boot fstab）

五份官方 `fstab.qcom` **字节级相同**（sha256 前 16 位 `4c896bf8133d5f67`）。

- `/metadata` = **f2fs**（14.0.0.1120 起就不是 ext4）
- `/data` = f2fs + FBE wrappedkey + `resize,fscompress`
- `fastboot -w` 按**当前** vendor_boot 格式化 metadata；fstab 与盘上类型不一致 → 循环

仓库 overlay 已全部改为 f2fs。仍**禁止**格式化 metadata/userdata 来「试试」。

## L3 内核 ↔ dtbo ↔ init_boot

分区大小五份一样（boot 192MiB / init_boot 8MiB / dtbo 24MiB），**内容哈希全部不同**。同大小 ≠ 可互换。

| ColorOS | 内核 | 禁止搭配 |
|---|---|---|
| 14.0.0.1120 | 5.15.123 `…ga4e8787d5799` | 任何 149/167/180 的 dtbo/init_boot |
| 15.0.0.320 | 5.15.149 `…g3337bebe8205` | 其它行 |
| 15.0.0.1300 | 5.15.167 `…g043e86cdd499` | **1400 的 5.15.167 分支产物** |
| 15.0.0.1400 | 5.15.167 `…g18bd462653c5` | 1300 的 vendor_dlkm/dtbo |
| 16.0.3.500 | 5.15.180 `…g6333b0dbc8ed` | 16.0.2.402 的 dtbo/init_boot |

boot 头 `os_version=13.0.0` 是 KMI，不是系统 Android 版本。

## L4 闭源驱动 / vendor_dlkm

显示、GPU、Wi-Fi、音频、相机、IPA 都在**官方 vendor_dlkm + vendor_boot ramdisk**。
AnyKernel3 `do.modules=0`，zip 里只有 Image + kernelsu.ko 时**不会**覆盖这些分区。

旧 `COMPATIBILITY.md`「必须替换 vendor_dlkm」针对的是 **5.15.200 + SUSFS 那次事故**，与现在 OGKI+LKM 路径相反。按那份做会黑屏。

## L5 super / my_* / FBE

官方 super 含 `my_product/my_stock/my_heytap/…`。自编译 Lineage 没有这些逻辑分区。
刷自编译 super / `super_empty` / 在 fastbootd 里 resize 逻辑分区 = 上次循环+EDL 的路径。
**本仓库安全策略：不编、不刷 system/vendor/odm/product/super/userdata。**

## L6 Recovery

官方 recovery：100MiB、header v4、**kernel_size=0**（用 boot 的内核）。
OrangeFox 同样 exclude kernel。OFRP **没有 fastbootd**。未签名 recovery 可能直接不启动。

## L7 本仓库实际会写什么

| 产物 | 写入 |
|---|---|
| AnyKernel3 zip | **只 `boot` 分区**（v4 无 ramdisk 走 `flash_boot`，不调用会碰 vendor_dlkm 的 `write_boot`） |
| `rom-adapt.sh` | 生成 boot.img + 复制**同版本官方** dtbo/init_boot + vbmeta flags=3。FLASH.txt **只刷 boot/dtbo/init_boot/vbmeta** |
| OrangeFox zip | 只 recovery 分区 |

## L8 刷机前 / 失败回滚

刷之前在电脑保留**当前 ColorOS 那一行**的官方 `boot.img`（`ota_probe/` 或全量包解出）。

失败（realme 标循环、fastboot、9008）：

1. 断电，音量下+电源进 fastboot（9008 则先断电重插）
2. `fastboot flash boot 官方boot.img`（当前 ColorOS 那份）
3. 不要 `fastboot -w`，不要 `flash super`

## L9 允许的操作

手机已是上表某一行官方 ColorOS → 只刷该行 AnyKernel3。
DS / Re-Kernel / ZRAM 按 Action-Build 原选项使用，不额外关。
