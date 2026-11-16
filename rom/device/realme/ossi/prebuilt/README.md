Drop this branch's OGKI `Image` here after `scripts/20-build.sh`:

```
cp $KP_DIR/.../Image rom/device/realme/ossi/prebuilt/Image
```

BoardConfig picks it up via `TARGET_PREBUILT_KERNEL`. Never place a Google GKI Image here.

`kernelsu.ko` does not belong here: the ROM is not what loads it. ksud late-load
reads `<kmi>_kernelsu.ko` from its embedded assets, then `/data/adb/ksu/kernelsu.ko`
(where AnyKernel3 puts it), `/data/adb/ksu/bin/kernelsu.ko`, `/data/local/tmp/kernelsu.ko`.
