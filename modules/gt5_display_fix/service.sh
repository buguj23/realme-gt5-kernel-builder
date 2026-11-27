#!/system/bin/sh
# Ensure GT5 factory center punch-hole cutout fabricated overlay stays active across reboots
# (Lives in /data/resource-cache/*.frro so all processes including webview_zygote can read it cleanly)

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
