Drop this branch's OGKI `Image` and `kernelsu.ko` here after `scripts/20-build.sh`:

```
cp $KP_DIR/.../Image rom/device/realme/ossi/prebuilt/Image
cp $KP_DIR/.../kernelsu.ko rom/device/realme/ossi/prebuilt/kernelsu.ko
```

BoardConfig picks them up via `TARGET_PREBUILT_KERNEL`. Never place a Google GKI Image here.
