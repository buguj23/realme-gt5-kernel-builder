### AnyKernel3 Ramdisk Mod Script
## Realme GT5 (SM8550) YukiSU + Kasumi Stealth Kernel
## osm0sis @ xda-developers & Antigravity Engineering

### AnyKernel setup
# global properties
properties() { '
kernel.string=Realme GT5 (SM8550) Action-Build OGKI 5.15 + YukiSU LKM
do.devicecheck=0
do.modules=0
do.systemless=0
do.cleanup=1
do.cleanuponabort=0
device.name1=ossi
device.name2=salami
device.name3=xigua
device.name4=corot
device.name5=RMX3820
'; } # end properties

### AnyKernel install
## boot shell variables
BLOCK=boot
IS_SLOT_DEVICE=auto
RAMDISK_COMPRESSION=auto
PATCH_VBMETA_FLAG=auto
NO_MAGISK_CHECK=1

# import functions/variables and setup patching - see for reference (DO NOT REMOVE)
. tools/ak3-core.sh

sync
chmod -R 755 $AKHOME/tools

ui_print "=========================================="
ui_print " Realme GT5 (SM8550) Action-Build OGKI 5.15"
ui_print " YukiSU LKM + Kasumi (CONFIG_KSU=m, no Google GKI)"
ui_print " Analogue: OnePlus Ace2 Pro / OnePlus 11 kalama"
ui_print "=========================================="

split_boot
if [ -f "split_img/ramdisk.cpio" ]; then
    unpack_ramdisk
    write_boot
else
    flash_boot
fi

# =============
# YukiSU & Kasumi LKM 部署
# =============
ui_print "------------------------------------------"
ui_print " 正在部署 YukiSU LKM 与 Kasumi VFS 隐匿环境..."

# 确保尝试挂载 /data
mount /data 2>/dev/null || true

if [ -f "$AKHOME/kernelsu.ko" ]; then
    mkdir -p /data/adb/ksu/ 2>/dev/null
    cp -f "$AKHOME/kernelsu.ko" /data/adb/ksu/kernelsu.ko 2>/dev/null || true
    cp -f "$AKHOME/kernelsu.ko" /data/adb/kernelsu.ko 2>/dev/null || true
    chmod 644 /data/adb/ksu/kernelsu.ko 2>/dev/null || true
    chmod 644 /data/adb/kernelsu.ko 2>/dev/null || true
    ui_print "  [+] kernelsu.ko (YukiSU + Kasumi) 部署成功"
fi

if [ -f "$AKHOME/ksud" ]; then
    mkdir -p /data/adb/ 2>/dev/null
    cp -f "$AKHOME/ksud" /data/adb/ksud 2>/dev/null || true
    chmod 755 /data/adb/ksud 2>/dev/null || true
    ui_print "  [+] ksud (YukiSU Native Daemon) 部署成功"
fi

sync
ui_print "=========================================="
ui_print " 内核及隐匿运行库刷写完毕！"
ui_print " Flashing complete successfully!"
ui_print "=========================================="
