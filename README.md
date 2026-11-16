# Realme GT5 — 官方内核分支

**一个内核一个分支。** 只保留官方 150W 包里适配真我 GT5 的内核。

| 分支 | 官方 uname | ColorOS | 类原生 |
|---|---|---|---|
| `5.15.123` | `5.15.123-android13-8-00760-ga4e8787d5799` | 14.0.0.1120 | lineage-21 / Android 14 |
| `5.15.149` | `5.15.149-android13-8-o-01120-g3337bebe8205` | 15.0.0.320 | lineage-22.2 / Android 15 |
| `5.15.167` | `5.15.167-android13-8-o-01142-g18bd462653c5` | 15.0.0.1400 | lineage-22.2 / Android 15 |
| `5.15.180` | `5.15.180-android13-8-o-01173-g24db146997d1` | 16.0.2.402 | lineage-23.2 / Android 16 |

ROM：LineageOS **salami + sm8550-common**（Ace2 Pro 同 kalama / 2772×1240），改成 ossi/RMX3820。
`BOARD_USES_GENERIC_KERNEL_IMAGE=false`，`/metadata` ext4。`lunch lineage_ossi-userdebug`。

```bash
git clone -b 5.15.180 https://github.com/buguj23/realme-gt5-kernel-builder.git
```

## OrangeFox（OGKI 对齐）

| 分支 | 内核 | ColorOS | fox_ |
|---|---|---|---|
| `OrangeFox-5.15.123` | 5.15.123 | 14.0.0.1120 | 14.1 |
| `OrangeFox-5.15.149` | 5.15.149 | 15.0.0.320 | 14.1 |
| `OrangeFox-5.15.167` | 5.15.167 | 15.0.0.1400 | 14.1 |
| `OrangeFox-5.15.180` | 5.15.180 | 16.0.2.402 | 16.0 |
