# Realme GT5 (`realme_gt5_v`) Manifest

- Manifest source: `DestoryG/kernel_manifest` branch `realme/sm8550` (`realme_gt5_v.xml`)
- Upstream kernel/vendor sources: `realme-kernel-opensource/realme_GT5-AndroidV-{common,kernel,vendor}-source` (`master`, Linux `5.15.149`)
- Target platform: `kalama` (`SM8550`), `android13-5.15`, KMI generation `8`, `module_layout = 0x0222dd63`
- Toolchain: Hermetic Clang `r450784e` (`14.0.7`)

Full vendor build (DTBs + DLKMs):
```bash
LTO=thin SYSTEM_DLKM_RE_SIGN=0 BUILD_SYSTEM_DLKM=0 KMI_SYMBOL_LIST_STRICT_MODE=0 \
  ./kernel_platform/oplus/build/oplus_build_kernel.sh kalama gki
```
