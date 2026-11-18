# ROM 质量对照：RMX3820_16.0.3.500(CN01) 全量包

来源：`真我_GT5_150W_16.0.3.500_全量包.zip`（AB OTA `payload.bin`）。

## 官方实测

| 项 | 全量包 | 本分支修正前 |
|---|---|---|
| 设备 | RMX3820 / RE5C33 / 工程 22635 | 正确 |
| Android / SDK | 16 / 36 | 正确 |
| 内核 | **仍是 5.15.180** `…-o-01176-g6333b0dbc8ed` | `…-o-01173-g24db146997d1`（16.0.2.402） |
| boot | v4 kernel-only，os_version **13.0.0**，os_patch **2026-02** | os_patch 2025-12 |
| init_boot | v4 ramdisk only 8MiB | 正确 |
| recovery | v4 **kernel_size=0** 100MiB | OFRP exclude-kernel 正确 |
| vbmeta | flags=**0** 12KiB | 旧 ROM 配置使用 flags=3 |
| **metadata** | **f2fs** | 曾误改为 ext4（混刷会挂载失败） |
| userdata | f2fs + `resize,fscompress` | 缺这两项 |
| fingerprint | `realme/RMX3820/RE5C33:16/BP2A.250605.015/T.5727b50-35127b2-34d6407:user/release-keys` | 曾用 16.0.2.402 当 incremental |
| security_patch | 2026-02-01 | 2025-12 |
| vendor_boot cmdline | `video=vfb:640x400,… nosoftlockup bootconfig buildvariant=user` | 仅 nosoftlockup |
| 动态分区 | 含 my_product/my_stock/… oplus 逻辑分区 | Lineage fstab 未列 |

## 结论

- 分支名 `5.15.180` 仍正确（SUBLEVEL 未涨）。
- 类原生必须跟这份 vendor_boot 的 **metadata=f2fs**，不能用 ext4。
- 指纹 / 安全补丁必须用全量包 `post-build`，不能拿 ColorOS 三位版本号当 incremental。
- 16.0.3.500 ROM 构建校验同版本原厂 DTB、DTBO 和 init_boot 输入。构建输出的 AVB 保持验证开启，交付时校验完整信任链。
