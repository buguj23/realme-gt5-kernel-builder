# Realme GT5 — OGKI + YukiSU

设备 **ossi / RMX3820 / RE5C33**。上游 Action-Build 5.15 OGKI，禁止 Google 通用 GKI。Root：YukiSU LKM `CONFIG_KSU=m`。

已用 `RMX3820_16.0.3.500(CN01)` 全量包校准 `5.15.180`（内核仍是 5.15.180，UTS `…-o-01176-g6333b0dbc8ed`，`/metadata` **f2fs**）。

| 分支 | 官方 uname | ColorOS | 类原生 | `/metadata` |
|---|---|---|---|---|
| `5.15.123` | `5.15.123-android13-8-00760-ga4e8787d5799` | 14.0.0.1120 | lineage-21 / 14 | ext4 |
| `5.15.149` | `5.15.149-android13-8-o-01120-g3337bebe8205` | 15.0.0.320 | lineage-22.2 / 15 | ext4 |
| `5.15.167` | `5.15.167-android13-8-o-01142-g18bd462653c5` | 15.0.0.1400 | lineage-22.2 / 15 | ext4 |
| `5.15.180` | `5.15.180-android13-8-o-01176-g6333b0dbc8ed` | **16.0.3.500** | lineage-23.2 / 16 | **f2fs** |

Actions → **Build Realme GT5 OGKI (YukiSU)** → 选内核版本。`main` 默认 5.15.180；各 `5.15.*` 分支锁定本版本。

## OrangeFox（ossi，无 Ace2 / 一加 11）

Actions → **OrangeFox Recovery (OFRP) CI/CD** → 只选 GT5 内核。`lunch ofox_ossi-eng`。recovery 100MiB header v4，不含内核。

| 分支 | 内核 | ColorOS | fox_ |
|---|---|---|---|
| `OrangeFox-5.15.123` | 5.15.123 | 14.0.0.1120 | 14.1 |
| `OrangeFox-5.15.149` | 5.15.149 | 15.0.0.320 | 14.1 |
| `OrangeFox-5.15.167` | 5.15.167 | 15.0.0.1400 | 14.1 |
| `OrangeFox-5.15.180` | 5.15.180 | 16.0.3.500 | 16.0 |

```bash
git clone -b 5.15.180 https://github.com/buguj23/realme-gt5-kernel-builder.git
```
