#!/usr/bin/env bash
# Deploy & configure the 6-layer YukiSU stealth architecture over ADB + ksud
# Supports both flashed ROM (normal reboot) and zero-flash Sticky DSU (--directlkm-boot IMG).
#
# Architecture (per realme_gt5_infinity_and_stealth_master_guide):
#   Layer 1: YukiSU (LKM) + built-in Kasumi/Kagami zero-mount VFS + UTS View GKI spoof
#   Layer 2: YukiZygisk (standalone kernel Zygisk; disables built-in YukiZygisk first)
#   Layer 3: TEESimulator-RS + Specter (Boot Spoofing ON, ROM Cleaner ON, ADB Lock OFF, PIF)
#   Layer 4: Yukari (Binder service filter) + FuseHide (Standalone Zygisk MediaProvider isolation)
#   Layer 5: HMA-OSS (Zygisk edition + Specter HMA config sync + Vold Isolation)
#   Layer 6: Vector v2.2+ (Golden minimal scope: zero banking/gov/anti-cheat apps checked)
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

stage_push() {
  echo "=== Pushing 6-layer modules & APKs to /sdcard/Download/yuki_6layers/ ==="
  "${ADB[@]}" shell "mkdir -p /sdcard/Download/yuki_6layers"
  for pat in \
    "YukiSU_*.apk" \
    "YukiZygisk-*.zip" \
    "TEESimulator-RS-*.zip" \
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

  echo "=== Batch 1 (Layer 2 + Layer 3): YukiZygisk + TEESimulator-RS + Specter ==="
  for pat in "YukiZygisk-*.zip" "TEESimulator-RS-*.zip" "specter-*.zip"; do
    local base
    base=$(basename "$(find_file "$pat")")
    echo "  installing $base..."
    run_root "$ksud module install '/sdcard/Download/yuki_6layers/$base'"
  done
}

run_stage2() {
  local ksud
  ksud=$(check_ksud)
  echo "=== Batch 2 (Layer 4 + Layer 5 + Layer 6): Yukari + FuseHide + HMA-OSS + Vector ==="
  for pat in "Yukari*.zip" "FuseHide-*.zip" "HMA-OSS-ZYGISK-*.zip" "Vector-*.zip"; do
    local base
    base=$(basename "$(find_file "$pat")")
    echo "  installing $base..."
    run_root "$ksud module install '/sdcard/Download/yuki_6layers/$base'"
  done
  local fuse_apk
  fuse_apk=$(find_file "FuseHide_*.apk")
  "${ADB[@]}" install -r "$fuse_apk" >/dev/null || true
}

run_config() {
  echo "=== Phase 5: Configure Mainland China Captive Portal + Specter + HMA-OSS ==="
  run_root '
    # Switch Android NetworkMonitor captive-portal URLs to Mainland China reachable endpoints
    settings put global captive_portal_mode 1
    settings put global captive_portal_http_url http://connect.rom.miui.com/generate_204
    settings put global captive_portal_https_url https://connect.rom.miui.com/generate_204
    settings put global captive_portal_fallback_url http://connectivitycheck.qualcomm.cn/generate_204
    settings put global captive_portal_other_fallback_urls http://connect.rom.miui.com/generate_204

    CFG=/data/adb/specter/config/val
    mkdir -p "$CFG"
    printf 1 > "$CFG/toggle_prop_handler.val"
    printf 1 > "$CFG/toggle_boot_state_props.val"
    printf 1 > "$CFG/toggle_bootmode_spoof.val"
    printf 1 > "$CFG/toggle_boot_hash.val"
    printf 1 > "$CFG/toggle_rom_fingerprint.val"
    printf 1 > "$CFG/toggle_rom_fingerprint_names.val"
    printf 1 > "$CFG/toggle_rom_fingerprint_prefix.val"
    printf 1 > "$CFG/toggle_rom_fingerprint_build_type.val"
    printf 1 > "$CFG/toggle_pif_props.val"
    printf 0 > "$CFG/toggle_adb_disabler.val"
    printf 1 > "$CFG/toggle_action_hma.val"
    if [ -f /data/adb/modules/specter/features/keybox.sh ]; then
      sh /data/adb/modules/specter/features/keybox.sh || true
    fi
    if [ -f /data/adb/modules/specter/features/widevine.sh ]; then
      sh /data/adb/modules/specter/features/widevine.sh || true
    fi
    if [ -f /data/adb/modules/specter/features/hma.sh ]; then
      sh /data/adb/modules/specter/features/hma.sh || true
    fi
    # Enable Vold Isolation in HMA-OSS config if present
    for hma_cfg in /data/misc/hide_my_applist*/config.json; do
      [ -f "$hma_cfg" ] || continue
      if grep -q "\"voldIsolation\"" "$hma_cfg"; then
        sed -i "s/\"voldIsolation\"[[:space:]]*:[[:space:]]*false/\"voldIsolation\": true/g" "$hma_cfg" || true
      fi
    done
    # Install bundled manager APKs from HMA-OSS and Vector modules if not installed
    for apk in /data/adb/modules/hma_oss_zygisk/manager.apk /data/adb/modules/zygisk_vector/manager.apk; do
      [ -f "$apk" ] && pm install -r "$apk" >/dev/null 2>&1 || true
    done
  '
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
  echo "NOTE: Keep Vector v2.2 on GOLDEN MINIMAL SCOPE (only non-sensitive apps like WeChat/QQ/UI tweaks; NEVER check banking/gov/anti-cheat apps!)."
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
