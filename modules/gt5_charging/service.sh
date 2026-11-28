#!/system/bin/sh
MODDIR="${0%/*}"
APP_PKG="com.gt5.charging"
SYS_APK="$MODDIR/system/system_ext/app/Gt5ChargingHistory/Gt5ChargingHistory.apk"
APP_FILES="/data/user/0/$APP_PKG/files"
STATE_DIR="/data/adb/gt5_charging"

# Wait for boot completion
while [ "$(getprop sys.boot_completed)" != "1" ]; do
  sleep 2
done
sleep 3

# Ensure the identically-signed APK is also installed as an updated system app in /data/app
# so YukiSU umount_modules=1 never breaks launching com.gt5.charging under normal app UID,
# while /system/system_ext/app/Gt5ChargingHistory keeps FLAG_SYSTEM for Settings -> Battery IA_SETTINGS!
if [ -f "$SYS_APK" ]; then
  cur_path=$(pm path "$APP_PKG" 2>/dev/null | head -n 1)
  case "$cur_path" in
    package:/data/app/*)
      # Already updated in /data/app; re-install only if module APK version changed
      apk_hash=$(md5sum "$SYS_APK" 2>/dev/null | awk '{print $1}')
      prev_hash=$(cat "$STATE_DIR/apk.md5" 2>/dev/null)
      if [ -n "$apk_hash" ] && [ "$apk_hash" != "$prev_hash" ]; then
        pm install -r -g "$SYS_APK" >/dev/null 2>&1 && echo "$apk_hash" > "$STATE_DIR/apk.md5"
      fi
      ;;
    *)
      pm install -r -g "$SYS_APK" >/dev/null 2>&1 && md5sum "$SYS_APK" 2>/dev/null | awk '{print $1}' > "$STATE_DIR/apk.md5"
      ;;
  esac
fi

# Start low-power 150W fast-charging fix & background recorder daemon (single instance)
if [ -f "$STATE_DIR/daemon.pid" ]; then
  old_pid=$(cat "$STATE_DIR/daemon.pid" 2>/dev/null)
  [ -n "$old_pid" ] && kill "$old_pid" 2>/dev/null
fi
nohup sh "$MODDIR/charging_daemon.sh" </dev/null >/dev/null 2>&1 &

# Start 0% CPU event-driven UI command bridge (inotifyd)
(
  while true; do
    if [ -d "$APP_FILES" ] && [ -x "$MODDIR/ui_bridge.sh" ]; then
      sh "$MODDIR/charging_ctl.sh" refresh >/dev/null 2>&1 || true
      /system/bin/inotifyd "$MODDIR/ui_bridge.sh" "$APP_FILES:w" >/dev/null 2>&1
    else
      # Pre-create app files dir if package exists so UI reads data on very first launch
      if [ -d "/data/user/0/$APP_PKG" ]; then
        uid=$(stat -c %u "/data/user/0/$APP_PKG" 2>/dev/null)
        ctx=$(stat -c %C "/data/user/0/$APP_PKG" 2>/dev/null)
        [ -n "$ctx" ] || ctx="u:object_r:app_data_file:s0"
        if [ -n "$uid" ]; then
          mkdir -p "$APP_FILES" 2>/dev/null
          chown "$uid:$uid" "$APP_FILES" 2>/dev/null
          chmod 0771 "$APP_FILES" 2>/dev/null
          chcon "$ctx" "$APP_FILES" 2>/dev/null
        fi
      fi
    fi
    sleep 3
  done
) </dev/null >/dev/null 2>&1 &
