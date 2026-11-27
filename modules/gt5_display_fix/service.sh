#!/system/bin/sh
# Realme GT5 (RMX3820) Display, Auto-Brightness, HDR & Pixelworks X7 Boot Service
# 1. Keeps factory center punch-hole cutout fabricated overlay active across reboots.
# 2. Dedicated <10ms ColorOS-style Auto-Brightness bias reset watcher (isolated from other watchers).
# 3. Applies saved Pixelworks X7 / Color Gamut / System HDR / Panel DC state on boot.
# 4. Starts zero-CPU-idle App Auto-Scene & Screen-Wake Gamut Guard daemon.

MODDIR="${0%/*}"

while [ "$(getprop sys.boot_completed)" != "1" ]; do
  sleep 2
done
sleep 2

# 1. Center punch-hole cutout guard
if ! cmd overlay list android 2>/dev/null | grep -q '\[x\] com.android.shell:gt5_center_cutout'; then
  cmd overlay fabricate --target android --name gt5_center_cutout \
    android:string/config_mainBuiltInDisplayCutout string \
    "M -58,0 L -58,138 L 58,138 L 58,0 Z" >/dev/null 2>&1 || true
  cmd overlay enable com.android.shell:gt5_center_cutout >/dev/null 2>&1 || true
fi

# 2. Dedicated Auto-Brightness OFF -> ON instant bias reset watcher
(
  while true; do
    wake_ts=0
    logcat -T 1 -v raw -s DisplayBrightnessStrategySelector:I 2>/dev/null | while IFS= read -r line; do
      case "$line" in
        *"ScreenOffBrightnessStrategy"*)
          wake_ts=$(date +%s)
          ;;
        *"from AutomaticBrightnessStrategy to FallbackBrightnessStrategy"*)
          wake_ts=0
          ;;
        *"from FallbackBrightnessStrategy to AutomaticBrightnessStrategy"*)
          now=$(date +%s)
          if [ "$((now - wake_ts))" -gt 2 ]; then
            settings put system screen_auto_brightness_adj 0 >/dev/null 2>&1 || true
            cmd display reset-brightness-configuration >/dev/null 2>&1 || true
          fi
          ;;
      esac
    done
    sleep 2
  done
) </dev/null >/dev/null 2>&1 &

# 3. Restore Pixelworks X7 + Gamut + System HDR + Panel hardware state
if [ -f "$MODDIR/display_ctl.sh" ]; then
  sh "$MODDIR/display_ctl.sh" boot_apply >/dev/null 2>&1 || true
fi

# 4. Start event-driven App Auto-Scene & Screen-Wake Gamut Guard
if [ -f "$MODDIR/scene_daemon.sh" ]; then
  sh "$MODDIR/scene_daemon.sh" >/dev/null 2>&1 &
fi
