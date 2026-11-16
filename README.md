# Realme GT5 — 官方内核分支

**一个内核一个分支，按具体版本命名。** 只保留官方 150W 包里能对上真我 GT5 的 5.15 内核。

| 分支 | 官方 uname | ColorOS | ROM |
|---|---|---|---|
| `5.15.74` | `5.15.74-android13-8-o-00602-g112553b34a64` | 13.1.1.148 | Android 13 |
| `5.15.94` | `5.15.94-android13-8-o-00718-gdd3c2549102f` | 14.0.0.211 | Android 14 |
| `5.15.123` | `5.15.123-android13-8-00760-ga4e8787d5799` | 14.0.0.1120 | Android 14 |
| `5.15.149` | `5.15.149-android13-8-o-01120-g3337bebe8205` | 15.0.0.320 | Android 15 |
| `5.15.167` | `5.15.167-android13-8-o-01142-g18bd462653c5` | 15.0.0.1400 | Android 15 |
| `5.15.180` | `5.15.180-android13-8-o-01173-g24db146997d1` | 16.0.2.402 | Android 16 |

每条分支的 `rom/` 是对应 Android 版本的 LineageOS **salami + sm8550-common** 类原生树（Ace2 Pro 同 kalama / 2772×1240），改成 ossi/RMX3820：`5.15.74`→lineage-20(A13)，`5.15.94/123`→lineage-21(A14)，`5.15.149/167`→lineage-22.2(A15)，`5.15.180`→lineage-23.2(A16)。`BOARD_USES_GENERIC_KERNEL_IMAGE=false`，`/metadata` ext4。`lunch lineage_ossi-userdebug`。

```bash
git clone -b 5.15.180 https://github.com/buguj23/realme-gt5-kernel-builder.git
```
