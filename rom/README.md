# ROM overlay — Realme GT5 (ossi / RMX3820)

This tree is dropped into an Infinity-X / Lineage source:

```
rom/device/realme/ossi          →  device/realme/ossi
rom/device/realme/sm8550-ogki   →  device/realme/sm8550-ogki
rom/vendor/realme/ossi          →  vendor/realme/ossi
```

`lunch infinity_ossi-userdebug` or `lunch lineage_ossi-userdebug`.

Kernel is **Action-Build OEM OGKI** (`oplus_build_kernel.sh kalama gki`) from this
branch's `kernel.json` `file` analogue. `BOARD_USES_GENERIC_KERNEL_IMAGE` is **false**.

`/metadata` is **ext4** (device-original). Lineage sm8550-common uses f2fs here and
that mixed with GT5's ext4 metadata is a confirmed boot-loop.
