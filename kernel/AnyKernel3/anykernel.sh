### AnyKernel3 Ramdisk Mod Script
## Realme GT5 (SM8550 / RMX3820) — 5.15.149 OEM OGKI
## osm0sis @ xda-developers

### AnyKernel setup
properties() { '
kernel.string=Realme GT5 (SM8550) 5.15.149 OEM OGKI
do.devicecheck=1
do.modules=0
do.systemless=0
do.cleanup=1
do.cleanuponabort=0
device.name1=ossi
device.name2=RMX3820
device.name3=RE5C33
device.name4=kalama
device.name5=
'; }

### AnyKernel install
BLOCK=boot
IS_SLOT_DEVICE=auto
RAMDISK_COMPRESSION=auto
PATCH_VBMETA_FLAG=auto
NO_MAGISK_CHECK=1

. tools/ak3-core.sh

sync
chmod -R 755 "$AKHOME/tools"

ui_print "=========================================="
ui_print " Realme GT5 (RMX3820) 5.15.149 OEM OGKI"
ui_print " Source: realme_gt5_v (android13-5.15 gen 8)"
ui_print "=========================================="

split_boot
if [ -f "split_img/ramdisk.cpio" ]; then
    unpack_ramdisk
    write_boot
else
    flash_boot
fi

if [ -f "$AKHOME/kernelsu.ko" ]; then
    ui_print "------------------------------------------"
    ui_print " Staging YukiSU LKM (kernelsu.ko)..."
    mount /data 2>/dev/null || true
    mkdir -p /data/adb/ksu 2>/dev/null || true
    cp -f "$AKHOME/kernelsu.ko" /data/adb/ksu/kernelsu.ko 2>/dev/null || true
    chmod 644 /data/adb/ksu/kernelsu.ko 2>/dev/null || true
    ui_print "  [+] /data/adb/ksu/kernelsu.ko staged"
    ui_print "  [i] Flash patched init_boot.img via YukiSU Manager to activate LKM on GKI 2.0."
else
    ui_print "  [i] Pure-OGKI kernel flashed cleanly (use official YukiSU LKM or custom init_boot)."
fi

sync
ui_print "=========================================="
ui_print " Flashing completed successfully!"
ui_print "=========================================="
