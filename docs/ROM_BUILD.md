# ROM Build Guide (`5.15.149` / `RMX3820_15.0.0.320`)

Builds AOSP-based ROM (`Project Infinity-X 15` / `lineage-22.2` dependencies, API `35`, `PRODUCT_SHIPPING_API_LEVEL := 33`) against verified `RMX3820_15.0.0.320(CN01)` stock inputs and a clean **Pure-OGKI** kernel package.

## Architecture Modes (`BoardConfigOgki.mk`)

1. **Prebuilt OGKI (`OGKI_BUILD_MODE=prebuilt`, default)**:
   - Consumes a verified schema-2 `kernel-package.tar.zst` (`Image`, `Module.symvers`, `modules/*.ko`) produced by `scripts/kernel-package.sh` (or GitHub Actions `Build Realme GT5 OGKI (5.15.149)`).
   - `scripts/rom-stage-kernel.py` checks imports, providers, vermagic, disables legacy DT fstab nodes on matching stock DTBs (`dtb[1..4]`), and emits `prebuilt/kernel-modules.mk`.
2. **Inline Source Build (`OGKI_BUILD_MODE=inline`)**:
   - Compiles `kernel/oneplus/sm8550` (`gki_defconfig`, `CONFIG_OPLUS_DEVICE_DTBS=y`) alongside the 25 out-of-tree `TARGET_KERNEL_EXT_MODULES` groups.
   - Zero `CONFIG_KSU` flags are injected into ROM source builds.

> In both modes, keep the ROM kernel completely unrooted (`Pure-OGKI`), verify boot first, then cross-compile `YukiSU` (`CONFIG_KSU=m`) out-of-tree against the exact `Module.symvers` + `.config` + `vmlinux` if custom LKM is desired and inject into `init_boot.img`.

## End-to-End Local Build

```bash
# 1. Inspect stock OTA images extracted via payload-dumper-go + payload_metadata.bin
python3 scripts/branch-facts.py --stock /path/to/stock_15.0.0.320 --label 5.15.149

# 2. Extract kernel-package built from realme_gt5_v (Pure-OGKI recommended for ROM)
mkdir -p ~/gt5_work/pkgs/5.15.149
tar --zstd -xf out/artifacts/kernel-package/kernel-package.tar.zst -C ~/gt5_work/pkgs/5.15.149

# 3. Pre-flight check stock payload, DTB/DTBO, OEM keys, LP layout, and kernel KMI
scripts/rom-build-local.sh --check-only --src ~/gt5-rom/5.15.149 --branch 5.15.149 \
  --pkg ~/gt5_work/pkgs/5.15.149 --stock-images /path/to/stock_15.0.0.320

# 4. Sync, select blobs, generate vendor tree, compile, and verify OTA + AVB chain
scripts/rom-build-local.sh --sync --src ~/gt5-rom/5.15.149 --branch 5.15.149 \
  --pkg ~/gt5_work/pkgs/5.15.149 --stock-images /path/to/stock_15.0.0.320
```

## Key Verified `15.0.0.320` Facts

- `payload_metadata.bin` SHA-256: `3FQtS2u21MJg0xzEH5sM5u7KxPaoFK0EKeqqmza5V60=` (`partial: true`, `virtual_ab: true`)
- `qti_dynamic_partitions` size: `14491320320`
- First-stage modules in `vendor_boot`: `145` entries in `modules.load` (`144` unique `.ko`s); Recovery: `438` (`435` unique)
- `vendor_dlkm`: `ext4`, `378` modules; `system_dlkm`: `ext4`, `2` modules (`zram.ko`, `zsmalloc.ko`)
- `metadata` mount filesystem: `f2fs`
- `extract-files.py` SDK `35` shims: includes `vendor.oplus.hardware.charger-V5-service` (`libbase_shim.so`), `fingerprint@2.1-service_uff` (`libshims_aidl_fingerprint_v2.oplus.so`), `libwfdservice.so`, `libwfdnative.so`.
