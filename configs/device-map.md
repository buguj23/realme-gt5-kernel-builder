# Realme GT5 × Action-Build 5.15 OGKI analogues

Action-Build workflow_dispatch 没有真我 SKU。真我 GT5（ossi / RMX3820 / RE5C33，SM8550 kalama）
使用同 SoC 的一加 / OPPO OGKI 清单作为上游。

构建命令（所有 SM8550 清单 README 相同）：

```
./kernel_platform/oplus/build/oplus_build_kernel.sh kalama gki
```

这里的 `gki` 是 **OEM OGKI 构建 flavor**，不是 Google `ci.android.com` 通用 GKI。

| FILE（Action-Build） | Android | common revision | 与 GT5 关系 |
|---|---|---|---|
| `oneplus_ace2_pro_b` | 16 | `oneplus/sm8550_b_16.0.0_ace_2_pro` | **默认。** 同 kalama / ColorOS，AnyKernel 已含 corot |
| `oneplus_ace2_pro_v` | 15 | `oneplus/sm8550_v_15.0.0_ace_2_pro` | A15 ROM |
| `oneplus_11_b` | 16 | `oneplus/sm8550_b_16.0.0_oneplus_11` | salami，同平台 |
| `oneplus_11_v` | 15 | `oneplus/sm8550_v_15.0.0_oneplus11` | A15 |
| `oneplus_11_u` | 14 | `oneplus/sm8550_u_*_oneplus11` | A14 5.15 |
| `oneplus_11_t` | 13 | `oneplus/sm8550_t_*` | A13 5.15 |
| `oneplus_ace3_{v,b}` | 15/16 | sm8550 ace3 | 同 SoC |
| `oneplus_open_{v,b}` | 15/16 | sm8550 open | 同 SoC |
| `oneplus_12r_{v,b}` | 15/16 | sm8550 12r | 同 SoC |
| `oppo_find_x6_pro_{v,b}` | 15/16 | Appendix `oppo/sm8550` | ColorOS 近亲 |
| `oppo_find_n3_{v,b}` | 15/16 | Appendix `oppo/sm8550` | 同 SoC |

清单文件已 vendored：`manifests/oneplus-sm8550/`、`manifests/oppo-sm8550/`。
5.15 补丁已从 Action-Build 拉取：`patches/bbrv3/*5.15*`、`patches/ntsync/*5.15*`、`patches/fix_5.15.legacy`。
