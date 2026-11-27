#!/system/bin/sh
# 1. Ensure GT5 factory center punch-hole cutout fabricated overlay stays active across reboots
# 2. ColorOS/Realme UI behavior bridge:
#    Listen to DisplayBrightnessStrategySelector (logd-filtered single tag, 0% CPU idle, <10ms latency).
#    Whenever user toggles Auto-Brightness OFF -> ON (FallbackBrightnessStrategy -> AutomaticBrightnessStrategy
#    outside of a screen-wake transition), immediately clear AOSP's sticky 5-minute ShortTermModel &
#    screen_auto_brightness_adj bias so brightness glides smoothly back to the real ambient lux curve!

while [ "$(getprop sys.boot_completed)" != "1" ]; do
  sleep 2
done
sleep 2

if ! cmd overlay list android 2>/dev/null | grep -q '\[x\] com.android.shell:gt5_center_cutout'; then
  cmd overlay fabricate --target android --name gt5_center_cutout \
    android:string/config_mainBuiltInDisplayCutout string \
    "M -58,0 L -58,138 L 58,138 L 58,0 Z" >/dev/null 2>&1 || true
  cmd overlay enable com.android.shell:gt5_center_cutout >/dev/null 2>&1 || true
fi

(
  while true; do
    wake_ts=0
    logcat -T 1 -v raw -s DisplayBrightnessStrategySelector:I 2>/dev/null | while IFS= read -r line; do
      case "$line" in
        *"ScreenOffBrightnessStrategy"*)
          wake_ts=$(date +%s)
          ;;
        *"from AutomaticBrightnessStrategy to FallbackBrightnessStrategy"*)
          # Explicit Auto OFF while awake -> ensure immediate Auto ON resets bias
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
