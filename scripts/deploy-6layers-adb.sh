#!/usr/bin/env bash
# Deploy & configure the 6-layer YukiSU stealth architecture over ADB + ksud
# Supports both flashed ROM (normal reboot) and zero-flash Sticky DSU (--directlkm-boot IMG).
#
# Architecture (live-verified on GT5 Infinity-X 3.12 Sticky DSU, Chunqiu 4.6.3: 1 GSI-inherent item only):
#   Layer 1: YukiSU v1.9.0 DirectLKM + built-in Kasumi/Kagami + UTS View GKI spoof + kernel_umount
#            + ksud umount for Vector dex2oat{32,64} + YukiSU Manager "默认卸载模块" ON
#   Layer 2: YukiZygisk v0.5.0+ (anonymous_memory=true, yukilinker=true, denylist_mode=1 Skip+unmount)
#   Layer 3: OhMyKeymint v1.3.0+ (replaces TEESimulator-RS; brand="realme") + Specter v2.0.0
#            (non-destructive mode: disable resetprop/crom_props toggles to prevent Property Modified)
#   Layer 4: Yukari (Binder service filter) + FuseHide (Standalone Zygisk MediaProvider isolation)
#   Layer 5: HMA-OSS (Zygisk edition) + fgetpriority v0.0.4 (eliminates 隐藏应用列表生效(2))
#   Layer 6: Vector v2.2+ ENABLED (Golden minimal scope: disable "卸载模块" ONLY for apps needing Xposed)
set -euo pipefail

SERIAL=""
PACK_DIR=""
DIRECTLKM_BOOT=""
UTS_RELEASE="5.15.149-android13-8-o-01120-g3337bebe8205"
UTS_VERSION="#1 SMP PREEMPT Sat Sep 7 12:30:09 UTC 2024"
STAGE="all"

usage() {
  cat <<'EOF'
Usage: deploy-6layers-adb.sh --pack-dir DIR [--serial ID] [--directlkm-boot IMG] [--stage all|stage1|stage2|config|verify]
EOF
}

while (( $# > 0 )); do
  case "$1" in
    --serial) SERIAL=$2; shift 2 ;;
    --pack-dir) PACK_DIR=$2; shift 2 ;;
    --directlkm-boot) DIRECTLKM_BOOT=$2; shift 2 ;;
    --uts-release) UTS_RELEASE=$2; shift 2 ;;
    --uts-version) UTS_VERSION=$2; shift 2 ;;
    --stage) STAGE=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

[ -n "$PACK_DIR" ] && [ -d "$PACK_DIR" ] || { echo "FAIL: --pack-dir DIR required" >&2; exit 2; }
ADB=(adb)
FB=(fastboot)
if [ -n "$SERIAL" ]; then
  ADB+=( -s "$SERIAL" )
  FB+=( -s "$SERIAL" )
fi

find_file() {
  local pat="$1"
  local match
  match=$(find "$PACK_DIR" -maxdepth 1 -type f -iname "$pat" | sort | head -n 1)
  [ -n "$match" ] || { echo "FAIL: missing $pat in $PACK_DIR" >&2; exit 1; }
  echo "$match"
}

run_root() {
  local cmd="$1"
  printf '%s\n' "$cmd" | "${ADB[@]}" shell "/system/bin/su -c sh"
}

wait_for_boot() {
  echo "[wait] waiting for ADB device & sys.boot_completed=1..."
  "${ADB[@]}" wait-for-device
  for _ in $(seq 1 90); do
    if [ "$("${ADB[@]}" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; then
      sleep 5
      return 0
    fi
    sleep 2
  done
  echo "FAIL: timed out waiting for boot_completed" >&2
  exit 1
}

reboot_device() {
  if [ -n "$DIRECTLKM_BOOT" ]; then
    echo "[reboot] Sticky DSU mode: enabling gsi_tool + fastboot boot $DIRECTLKM_BOOT"
    "${ADB[@]}" shell "gsi_tool enable" >/dev/null 2>&1 || true
    "${ADB[@]}" reboot bootloader
    for _ in $(seq 1 30); do
      if "${FB[@]}" devices 2>/dev/null | grep -q "fastboot"; then
        break
      fi
      sleep 1
    done
    "${FB[@]}" boot "$DIRECTLKM_BOOT"
  else
    echo "[reboot] Normal reboot..."
    "${ADB[@]}" reboot
  fi
  wait_for_boot
}

check_ksud() {
  local out
  out=$(run_root 'KSUD=/data/adb/ksud; [ -x /data/adb/ksu/bin/ksud ] && KSUD=/data/adb/ksu/bin/ksud; [ -x "$KSUD" ] && echo "$KSUD" || echo MISSING' | tr -d '\r')
  if [ -z "$out" ] || [ "$out" = "MISSING" ]; then
    echo "FAIL: ksud root not accessible via adb shell. Please grant Shell (com.android.shell) root in YukiSU Manager first!" >&2
    exit 1
  fi
  echo "$out"
}

find_optional_file() {
  local pat="$1"
  find "$PACK_DIR" -maxdepth 1 -type f -iname "$pat" | sort | head -n 1 || true
}

stage_push() {
  echo "=== Pushing 6-layer modules & APKs to /sdcard/Download/yuki_6layers/ ==="
  "${ADB[@]}" shell "mkdir -p /sdcard/Download/yuki_6layers"
  local keymint_pat="OhMyKeymint-*.zip"
  if [ -z "$(find_optional_file "$keymint_pat")" ]; then
    keymint_pat="TEESimulator-RS-*.zip"
  fi
  for pat in \
    "YukiSU_*.apk" \
    "YukiZygisk-*.zip" \
    "$keymint_pat" \
    "specter-*.zip" \
    "Yukari*.zip" \
    "FuseHide-*.zip" \
    "FuseHide_*.apk" \
    "HMA-OSS-ZYGISK-*.zip" \
    "Vector-*.zip"; do
    local f
    f=$(find_file "$pat")
    "${ADB[@]}" push "$f" "/sdcard/Download/yuki_6layers/$(basename "$f")" >/dev/null
    echo "  pushed $(basename "$f")"
  done
  local fgp
  fgp=$(find_optional_file "fgetpriority*.zip")
  if [ -n "$fgp" ]; then
    "${ADB[@]}" push "$fgp" "/sdcard/Download/yuki_6layers/$(basename "$fgp")" >/dev/null
    echo "  pushed $(basename "$fgp")"
  fi
}

run_stage1() {
  local ksud
  ksud=$(check_ksud)
  echo "=== Layer 1: YukiSU + built-in Kasumi/Kagami + UTS View ==="
  # Enable kernel-level stealth features (some like kasumi activate via kagami/on boot)
  for feat in unshare_mnt selinux_hide kernel_umount hide_bootloader kasumi; do
    run_root "$ksud feature set-save $feat 1 2>&1 || true"
  done
  # Configure Kagami + Kasumi zero-mount stealth backend
  run_root "$ksud kagami config merge-json '{\"kasumi_enabled\":true,\"enable_stealth\":true,\"enable_mount_hide\":true,\"enable_overlay_xattr_hide\":true,\"enable_statfs_spoof\":true,\"enable_maps_spoof\":true}' 2>&1 || true"
  run_root "$ksud kagami kasumi enable 2>&1 || true"
  # Disable built-in YukiZygisk before installing standalone YukiZygisk (strict mutual exclusion!)
  run_root "$ksud feature set-save yukizygisk 0"
  # Configure & enable global UTS View to official Qualcomm GKI release & version
  run_root "$ksud uts-view set-global --release '$UTS_RELEASE' --version '$UTS_VERSION'"
  run_root "$ksud uts-view enable-global"
  run_root "$ksud uts-view status"
  run_root "$ksud feature list"

  echo "=== Batch 1 (Layer 2 + Layer 3): YukiZygisk + OhMyKeymint/TEESimulator + Specter ==="
  local keymint_pat="OhMyKeymint-*.zip"
  if [ -z "$(find_optional_file "$keymint_pat")" ]; then
    keymint_pat="TEESimulator-RS-*.zip"
  fi
  for pat in "YukiZygisk-*.zip" "$keymint_pat" "specter-*.zip"; do
    local base
    base=$(basename "$(find_file "$pat")")
    echo "  installing $base..."
    run_root "$ksud module install '/sdcard/Download/yuki_6layers/$base'"
  done
}

run_stage2() {
  local ksud
  ksud=$(check_ksud)
  echo "=== Batch 2 (Layer 4 + Layer 5 + Layer 6): Yukari + FuseHide + HMA-OSS + fgetpriority + Vector ==="
  for pat in "Yukari*.zip" "FuseHide-*.zip" "HMA-OSS-ZYGISK-*.zip" "Vector-*.zip"; do
    local base
    base=$(basename "$(find_file "$pat")")
    echo "  installing $base..."
    run_root "$ksud module install '/sdcard/Download/yuki_6layers/$base'"
  done
  local fgp
  fgp=$(find_optional_file "fgetpriority*.zip")
  if [ -n "$fgp" ]; then
    local fgp_base
    fgp_base=$(basename "$fgp")
    echo "  installing $fgp_base..."
    run_root "$ksud module install '/sdcard/Download/yuki_6layers/$fgp_base'"
  fi
  local fuse_apk
  fuse_apk=$(find_file "FuseHide_*.apk")
  "${ADB[@]}" install -r "$fuse_apk" >/dev/null || true
}

run_config() {
  local ksud
  ksud=$(check_ksud)
  echo "=== Phase 5: Configure China Captive Portal + YukiZygisk + OMK + Specter + Vector umount + HMA-OSS ==="
  run_root "
    # Switch Android NetworkMonitor captive-portal URLs to Mainland China reachable endpoints
    settings put global captive_portal_mode 1
    settings put global captive_portal_http_url http://connect.rom.miui.com/generate_204
    settings put global captive_portal_https_url https://connect.rom.miui.com/generate_204
    settings put global captive_portal_fallback_url http://connectivitycheck.qualcomm.cn/generate_204
    settings put global captive_portal_other_fallback_urls http://connect.rom.miui.com/generate_204

    # Configure YukiZygisk v0.5.0+: anonymous memory + yukilinker + Skip & unmount on denylist
    if [ -x /data/adb/modules/yukizygisk/bin/yzctl ]; then
      /data/adb/modules/yukizygisk/bin/yzctl config set anonymous_memory true yukilinker true denylist_mode 1 || true
    fi

    # Register Vector dex2oat bind-mounts in YukiSU kernel umount table (prevents Mount loophole + Found LSPHook)
    $ksud umount add /apex/com.android.art/bin/dex2oat32 -f 2 2>&1 || true
    $ksud umount add /apex/com.android.art/bin/dex2oat64 -f 2 2>&1 || true
    $ksud umount save 2>&1 || true
    if [ -f /data/adb/ksu/.umount ]; then
      grep -vE '^---|^[{}]' /data/adb/ksu/.umount > /data/adb/ksu/.umount.tmp && mv /data/adb/ksu/.umount.tmp /data/adb/ksu/.umount
    fi

    # Specter non-destructive config: let ROM bionic/frameworks patches + YukiSU hide_bootloader + OMK handle props/TEE
    # (enabling Specter crom_props/rom_fingerprint/prop_handler deletes ro.build.fingerprint & triggers Property Modified)
    CFG=/data/adb/specter/config/val
    mkdir -p \"\$CFG\"
    printf 0 > \"\$CFG/toggle_prop_handler.val\"
    printf 0 > \"\$CFG/toggle_boot_state_props.val\"
    printf 0 > \"\$CFG/toggle_bootmode_spoof.val\"
    printf 1 > \"\$CFG/toggle_boot_hash.val\"
    printf 0 > \"\$CFG/toggle_rom_fingerprint.val\"
    printf 0 > \"\$CFG/toggle_rom_fingerprint_names.val\"
    printf 0 > \"\$CFG/toggle_rom_fingerprint_prefix.val\"
    printf 0 > \"\$CFG/toggle_rom_fingerprint_build_type.val\"
    printf 0 > \"\$CFG/toggle_custom_rom_props.val\"
    printf 0 > \"\$CFG/toggle_pif_props.val\"
    printf 0 > \"\$CFG/toggle_adb_disabler.val\"
    printf 1 > \"\$CFG/toggle_action_hma.val\"
    if [ -f /data/adb/modules/specter/features/keybox.sh ]; then
      sh /data/adb/modules/specter/features/keybox.sh || true
    fi
    if [ -f /data/adb/modules/specter/features/hma.sh ]; then
      sh /data/adb/modules/specter/features/hma.sh || true
    fi

    # Align OhMyKeymint device brand with vendor (realme RMX3820) when GSI ro.product.brand=generic
    if [ -f /data/misc/keystore/omk/config.toml ]; then
      sed -i 's/^brand = \"generic\"/brand = \"realme\"/' /data/misc/keystore/omk/config.toml || true
    fi

    # Install bundled manager APKs from HMA-OSS and Vector modules if not installed
    for apk in /data/adb/modules/hma_oss_zygisk/manager.apk /data/adb/modules/zygisk_vector/manager.apk; do
      [ -f \"\$apk\" ] && pm install -r \"\$apk\" >/dev/null 2>&1 || true
    done
  "
}

run_verify() {
  local ksud
  ksud=$(check_ksud)
  echo "=== Final 6-Layer Stealth Verification ==="
  run_root "
    echo '--- uname -a (UTS View) ---'
    uname -a
    echo '--- SELinux ---'
    getenforce
    echo '--- Verified Boot & Build Props (Specter) ---'
    for p in ro.boot.verifiedbootstate ro.boot.flash.locked ro.boot.vbmeta.device_state ro.build.type ro.build.tags ro.debuggable; do
      echo \"\$p=\$(getprop \$p)\"
    done
    echo '--- Active Modules ---'
    $ksud module list 2>/dev/null || ls -1 /data/adb/modules
    echo '--- /proc/mounts leak check (ksu/magisk/overlay/modules) ---'
    grep -iE 'ksu|magisk|adb/modules|debug_ramdisk' /proc/mounts || echo 'CLEAN (0 leaked mount entries)'
    echo '--- Specter config ---'
    head -n 1 /data/adb/specter/config/val/*.val 2>/dev/null || true
  "
  echo "NOTE 1: In YukiSU Manager -> Settings, enable '默认卸载模块' (Unmount modules by default) so YukiZygisk skips & unmounts dex2oat for sensitive/detector apps!"
  echo "NOTE 2: Keep Vector v2.2 on GOLDEN MINIMAL SCOPE: disable '卸载模块' ONLY for apps needing Xposed hooks (e.g. WeChat/QQ) and MediaProvider (com.android.providers.media.module for FuseHide)."
}

case "$STAGE" in
  stage1) stage_push; run_stage1; reboot_device ;;
  stage2) run_stage2; reboot_device ;;
  config) run_config; reboot_device; run_verify ;;
  verify) run_verify ;;
  all)
    stage_push
    run_stage1
    reboot_device
    run_stage2
    reboot_device
    run_config
    reboot_device
    run_verify
    ;;
  *) echo "Unknown --stage: $STAGE" >&2; exit 2 ;;
esac
