# ROM overlay — Realme GT5 (ossi / RMX3820)

Drop this tree into an Infinity-X / Lineage source:

```
rom/device/realme/ossi          →  device/realme/ossi
rom/device/realme/sm8550-ogki   →  device/realme/sm8550-ogki
rom/vendor/realme/ossi          →  vendor/realme/ossi
```

`lunch infinity_ossi-userdebug` (or `lineage_ossi-userdebug`).

## Kernel

OEM OGKI only (`oplus_build_kernel.sh kalama gki` from Action-Build), never Google
GKI: `BOARD_USES_GENERIC_KERNEL_IMAGE` stays **false**.

`Image`, every `.ko` and `Module.symvers` must come from **one** build. With
`CONFIG_MODVERSIONS=y` the kernel rejects each module whose `module_layout` or
imported-symbol CRC differs, and the first-stage set dies before UFS or FBE keys
exist (`docs/AUDIT_16.0.3.500.md`).

Stage a package (produced by `scripts/kernel-package.sh` in CI, or by
`scripts/20-build.sh` locally):

```bash
python3 scripts/rom-stage-kernel.py \
  --package <kernel-package-dir> \
  --device-tree rom/device/realme/ossi \
  --stock-modules-load <stock modules.load> \
  --stock-modules <dir with stock vendor_boot + vendor_dlkm + system_dlkm .ko>
```

The stager verifies the package with `scripts/kmi.py`, keeps the **stock**
first-stage order (146 entries on 16.0.3.500), and only borrows a module from the
stock pool when every imported symbol CRC matches. It writes
`prebuilt/kernel-modules.mk`, which `BoardConfigOgki.mk` includes.

`scripts/rom-vendor-boot-fix.sh <vendor_boot.img> --stock <stock.img>` re-checks the
ABL envelope (page `0x1000`, kernel `0x8000`, ramdisk `0x1000000`, tags `0x100`,
dtb `0x1f00000`) and the first-stage list after a build; `--check-only` makes it a
gate.

## Filesystem facts (measured on stock 16.0.3.500)

* `/metadata` is **f2fs** — from the stock `vendor_boot` `first_stage_ramdisk/fstab.qcom`.
* `super` logical partitions: `odm` erofs, `system`/`system_ext`/`product` ext4,
  `vendor`/`vendor_dlkm`/`system_dlkm` erofs.
* `boot` header v4 carries no ramdisk; `vendor_boot` carries the first-stage set.
