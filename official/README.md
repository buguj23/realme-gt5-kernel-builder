# Official Realme GT5 150W partition dump

Source zip: `GT5 150W.zip` (boot / dtbo / init_boot / recovery / vbmeta per ColorOS).

These are **OEM OGKI** kernels. Every version reports KMI `android13-5.15` even on ColorOS 14/15/16. Boot header `os_version` is always **13.0.0** (kernel ABI, not userspace). `boot.img` is header v4, **kernel only** (ramdisk_size=0); first-stage ramdisk lives in `init_boot`.

| ColorOS | Linux | vermagic suffix | os_patch | build analogue |
|---|---|---|---|---|
| 13.1.1.148 | 5.15.74 | android13-8-o-00602-g112553b34a64 | 2023-10 | oneplus_11_t |
| 14.0.0.120 | 5.15.94 | android13-8-o-00700-gfb14979bfc60 | 2023-11 | oneplus_11_u |
| 14.0.0.211 | 5.15.94 | android13-8-o-00718-gdd3c2549102f | 2024-02 | oneplus_11_u |
| 14.0.0.1120 | 5.15.123 | android13-8-00760-ga4e8787d5799 | 2024-10 | oneplus_11_u |
| 15.0.0.320 | 5.15.149 | android13-8-o-01120-g3337bebe8205 | 2024-11 | oneplus_ace2_pro_v |
| 15.0.0.1300 | 5.15.167 | android13-8-o-01140-g043e86cdd499 | 2025-08 | oneplus_ace2_pro_v |
| 15.0.0.1400 | 5.15.167 | android13-8-o-01142-g18bd462653c5 | 2025-09 | oneplus_ace2_pro_v |
| 16.0.2.402 | 5.15.180 | android13-8-o-01173-g24db146997d1 | 2025-12 | oneplus_ace2_pro_b |

Partition sizes (all builds): boot 192MiB, dtbo 24MiB, init_boot 8MiB, recovery 100MiB, vbmeta 12KiB.

Stock `vbmeta` uses flags=0. ROM builds sign and verify their own AVB chain and use the matching stock DTB and DTBO. For 16.0.3.500, the extracted kernel SHA-256 has been measured. The four whole-image hashes still requiring that OTA are recorded as `null`. The pinned payload metadata hash is listed in `kernels.json`.

```bash
scripts/import-official.sh "/path/to/GT5 150W.zip"
# stages official/stock/<coloros>/{boot,dtbo,init_boot,vbmeta,recovery}.img  (gitignored)
```
