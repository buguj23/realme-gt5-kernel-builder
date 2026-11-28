#!/system/bin/sh
STATE_DIR="/data/adb/gt5_charging"
if [ -f "$STATE_DIR/daemon.pid" ]; then
  kill "$(cat "$STATE_DIR/daemon.pid" 2>/dev/null)" 2>/dev/null
fi
pm uninstall com.gt5.charging >/dev/null 2>&1 || true
rm -rf "$STATE_DIR"
