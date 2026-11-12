#!/usr/bin/env bash
# 30-package.sh — produce flashable images from the build output.
#   boot.img          : Image + header v4 (os 16.0.0 / 2026-09)
#   vendor_boot.img   : ROM vendor_boot + our first-stage modules (same header fields)
#   vendor_dlkm.img   : flat /lib/modules with our modules (+kernelsu/rekernel)
#   system_dlkm.img   : /lib/modules/android16-5.15 with our zram/zsmalloc
set -euo pipefail
KP_DIR=${KP_DIR:-$HOME/gt5_kernel_ab/kernel_platform}
DIST=$KP_DIR/out200/dist
ROM=${ROM:-$HOME/gt5_infinity_workspace/rom_check}
OUT=${OUT:-$HOME/gt5_infinity_workspace/kernel_deliver}
STRIP=${STRIP:-llvm-strip}
MKBOOTIMG="python3 $KP_DIR/tools/mkbootimg/mkbootimg.py"

mkdir -p "$OUT" "$OUT/mods"
# 1. modules: strip debug info (ROM modules are stripped as well)
cp "$DIST"/*.ko "$OUT/mods/"
for f in "$OUT"/mods/*.ko; do $STRIP --strip-debug "$f" || true; done

# 2. boot.img
$MKBOOTIMG --header_version 4 --kernel "$DIST/Image" \
           --os_version 16.0.0 --os_patch_level 2026-09 -o "$OUT/boot.img"

# 3. vendor_boot.img (reuse the ROM header fields)
rm -rf "$OUT/vb"; mkdir -p "$OUT/vb"
( cd "$OUT/vb" && lz4 -dc "$ROM/vbu/vendor_ramdisk00" | cpio -id --quiet )
for ko in "$OUT"/mods/*.ko; do cp "$ko" "$OUT/vb/lib/modules/"; done
find "$OUT/vb/lib/modules" -name '*.ko' | while read -r f; do
    [ -f "$OUT/mods/$(basename "$f")" ] || rm -f "$f"
done
( cd "$OUT/vb" && find . -print0 | cpio --null -o -H newc --quiet ) > "$OUT/ramdisk.cpio"
lz4 -l -12 -f "$OUT/ramdisk.cpio" "$OUT/ramdisk.lz4" >/dev/null 2>&1
unpack_bootimg --boot_img "$ROM/vendor_boot.img" --out /tmp/vbhdr >/dev/null 2>&1
$MKBOOTIMG --header_version 4 --base 0x00000000 \
           --vendor_ramdisk "$OUT/ramdisk.lz4" --dtb /tmp/vbhdr/dtb \
           --vendor_bootconfig /tmp/vbhdr/bootconfig \
           --vendor_cmdline "nosoftlockup bootconfig" --pagesize 4096 \
           --kernel_offset 0x00008000 --ramdisk_offset 0x01000000 \
           --tags_offset 0x00000100 --dtb_offset 0x01f00000 \
           --vendor_boot "$OUT/vendor_boot.img"

# 4. vendor_dlkm.img
rm -rf "$OUT/vd"; mkdir -p "$OUT/vd/lib/modules"
cp "$OUT"/mods/*.ko "$OUT/vd/lib/modules/"
cp "$ROM"/vdlkm/modules/modules.{alias,dep,softdep,blocklist,load} "$OUT/vd/lib/modules/" 2>/dev/null || true
mke2fs -q -t ext4 -b 4096 -L vendor_dlkm -d "$OUT/vd" "$OUT/vendor_dlkm.img" 200M

# 5. system_dlkm.img
rm -rf "$OUT/sd"; mkdir -p "$OUT/sd"
debugfs -R "rdump /lib $OUT/sd" "$ROM/../rom_check/system_dlkm.img" 2>/dev/null || true
[ -d "$OUT/sd/lib/modules/android16-5.15" ] || mkdir -p "$OUT/sd/lib/modules/android16-5.15"
cp "$OUT"/mods/zram.ko "$OUT"/mods/zsmalloc.ko "$OUT/sd/lib/modules/android16-5.15/"
printf 'zram\n' > "$OUT/sd/lib/modules/android16-5.15/modules.load"
mke2fs -q -t ext4 -b 4096 -L system_dlkm -d "$OUT/sd" "$OUT/system_dlkm.img" 8M

ls -lh "$OUT"/*.img
