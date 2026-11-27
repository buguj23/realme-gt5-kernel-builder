#!/system/bin/sh
MODDIR="${0%/*}"
CTL="$MODDIR/halo_ctl.sh"
STATE_FILE="/data/adb/gt5_halo/state.env"

# Wait for sysfs & boot_completed
while [ "$(getprop sys.boot_completed)" != "1" ]; do
  sleep 2
done
sleep 2

# Ensure AW21012 exists
[ -d /sys/class/leds/red ] || exit 0

# Initialize default state if first boot
sh "$CTL" status >/dev/null 2>&1 || true

# Apply or keep cleanly OFF according to saved state
if [ -f "$STATE_FILE" ]; then
  # shellcheck disable=SC1090
  . "$STATE_FILE"
  if [ "${BOOT_RESTORE:-1}" = "1" ] && [ "${ENABLED:-0}" = "1" ]; then
    sh "$CTL" hw_apply_only >/dev/null 2>&1
  else
    sh "$CTL" hw_off_only >/dev/null 2>&1
  fi
fi

# Event-driven 0% CPU Quick Settings Tile bridge (inotifyd -> tile_bridge.sh)
TILE_DIR="/data/user/0/com.gt5.halotile/files"
(
  while true; do
    if [ -d "$TILE_DIR" ] && [ -x "$MODDIR/tile_bridge.sh" ]; then
      sh "$CTL" sync_tile >/dev/null 2>&1 || true
      /system/bin/inotifyd "$MODDIR/tile_bridge.sh" "$TILE_DIR:w" >/dev/null 2>&1
    fi
    sleep 3
  done
) </dev/null >/dev/null 2>&1 &

# Optional ultra-light screen-follow monitor (active only when SCREEN_FOLLOW=1 && ENABLED=1)
last_awake=""
while true; do
  if [ -f "$STATE_FILE" ]; then
    # shellcheck disable=SC1090
    . "$STATE_FILE"
    if [ "${ENABLED:-0}" = "1" ] && [ "${SCREEN_FOLLOW:-0}" = "1" ]; then
      if dumpsys power 2>/dev/null | grep -q "mWakefulness=Awake"; then
        cur_awake="1"
      else
        cur_awake="0"
      fi
      if [ "$cur_awake" != "$last_awake" ]; then
        last_awake="$cur_awake"
        if [ "$cur_awake" = "1" ]; then
          sh "$CTL" hw_apply_only >/dev/null 2>&1
        else
          sh "$CTL" hw_off_only >/dev/null 2>&1
        fi
      fi
      sleep 2
      continue
    fi
  fi
  last_awake=""
  sleep 5
done &
