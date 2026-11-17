# prebuilt/ — staged kernel package

Filled by `scripts/rom-stage-kernel.py`; not committed (binaries stay in CI
artifacts).

```
prebuilt/Image                                  kernel Image (from the package)
prebuilt/dtbo.img                               only when the package ships one
prebuilt/vendor_ramdisk/lib/modules/*.ko        first-stage set, stock order
prebuilt/vendor_ramdisk/lib/modules/modules.load
prebuilt/vendor_dlkm/lib/modules/*.ko
prebuilt/system_dlkm/lib/modules/*.ko
prebuilt/kernel-modules.mk                      BOARD_* lists consumed by BoardConfig
prebuilt/stage-report.json                      CRC + counts, for the build log
```

Rules:

* Never mix an `Image` with modules from another build — `module_layout` CRC is
  the gate, vermagic is not.
* Never let the ROM's own generated `modules.load` replace the stock list; stock
  16.0.3.500 has 146 first-stage entries, of which the earlier broken build kept 50.
* Never place a Google GKI `Image` here.
* `kernelsu.ko` does not belong here: root is late-loaded by the manager, not by
  the ROM.
