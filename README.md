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

每条分支含：该版本 `kernel.json`、Action-Build OGKI 构建钉死、`rom/device/realme/ossi`（`lunch infinity_ossi-userdebug`）、官方 boot 头（v4 / os_version 13.0.0）。

```bash
git clone -b 5.15.180 https://github.com/buguj23/realme-gt5-kernel-builder.git
```
