# Realme GT5 kernel + ROM builder

**一个内核一个分支。** 下拉分支列表里每一条都是一套完整的 **OEM OGKI 5.15 内核 + ossi ROM 适配**。

Action-Build 没有真我 SKU，全部用同 SoC SM8550 一加/OPPO analogue。
`oplus_build_kernel.sh kalama gki` 的 `gki` 是 OEM OGKI flavor，**不是** Google 通用 GKI。

设备：ossi / RMX3820 / RE5C33。Root：YukiSU LKM `CONFIG_KSU=m`。ROM fstab `/metadata` = **ext4**。

## 分支

| 分支 | Android | Analogue | 说明 |
|---|---|---|---|
| `5.15-oneplus_ace2_pro_b` | 16 | `oneplus_ace2_pro_b` | Ace2 Pro A16 — default GT5 analogue |
| `5.15-oneplus_ace2_pro_v` | 15 | `oneplus_ace2_pro_v` | Ace2 Pro A15 |
| `5.15-oneplus_11_b` | 16 | `oneplus_11_b` | OnePlus 11 A16 salami |
| `5.15-oneplus_11_v` | 15 | `oneplus_11_v` | OnePlus 11 A15 |
| `5.15-oneplus_11_u` | 14 | `oneplus_11_u` | OnePlus 11 A14 |
| `5.15-oneplus_11_t` | 13 | `oneplus_11_t` | OnePlus 11 A13 |
| `5.15-oneplus_ace3_b` | 16 | `oneplus_ace3_b` | Ace 3 A16 |
| `5.15-oneplus_ace3_v` | 15 | `oneplus_ace3_v` | Ace 3 A15 |
| `5.15-oneplus_open_b` | 16 | `oneplus_open_b` | Open A16 |
| `5.15-oneplus_open_v` | 15 | `oneplus_open_v` | Open A15 |
| `5.15-oneplus_12r_b` | 16 | `oneplus_12r_b` | 12R A16 |
| `5.15-oneplus_12r_v` | 15 | `oneplus_12r_v` | 12R A15 |
| `5.15-oppo_find_x6_pro_b` | 16 | `oppo_find_x6_pro_b` | Find X6 Pro A16 ColorOS |
| `5.15-oppo_find_x6_pro_v` | 15 | `oppo_find_x6_pro_v` | Find X6 Pro A15 |
| `5.15-oppo_find_n3_b` | 16 | `oppo_find_n3_b` | Find N3 A16 |
| `5.15-oppo_find_n3_v` | 15 | `oppo_find_n3_v` | Find N3 A15 |

点进对应分支：内核脚本、`kernel.json`、`rom/device/realme/ossi` 都已钉死在那一颗内核上。

```bash
git clone -b 5.15-oneplus_ace2_pro_b https://github.com/buguj23/realme-gt5-kernel-builder.git
```
