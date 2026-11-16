# SUPERSEDED — 不要按本文刷机

本文记录的是 **5.15.200 + SukiSU/SUSFS 自编译 ROM** 事故：当时自建 vendor_dlkm 缺 drm/wifi，且 CRC 对不上。

**现行安全策略（OGKI + YukiSU LKM）相反：**

- 只替换 `boot`
- **保留** 官方 `vendor_boot` / `vendor_dlkm` / `dtbo` / `init_boot`
- 见 `docs/PHONE_SAFETY.md` 与 `docs/ROM_OTA_MATRIX.md`

下文（缺失 36 模块、必须替换 dlkm）全部作废，照做会黑屏。
