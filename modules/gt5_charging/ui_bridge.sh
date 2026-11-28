#!/system/bin/sh
# Event-driven inotifyd IPC bridge for com.gt5.charging Settings UI (0% idle CPU, zero root in APK)
# Triggered by: inotifyd /data/adb/modules/gt5_charging/ui_bridge.sh /data/user/0/com.gt5.charging/files:w

[ "$3" = "cmd" ] || exit 0

MODDIR="${0%/*}"
CTL="$MODDIR/charging_ctl.sh"
CMD_FILE="$2/$3"
[ -f "$CMD_FILE" ] || exit 0

line=$(head -n 1 "$CMD_FILE" 2>/dev/null | tr -d '\r')
[ -n "$line" ] || exit 0

set -- $line
action="${1:-}"
arg="${2:-}"

case "$action" in
  refresh)
    sh "$CTL" refresh >/dev/null 2>&1
    ;;
  sample_now)
    sh "$CTL" sample_now >/dev/null 2>&1
    ;;
  set_mode)
    case "$arg" in
      hyper|balanced|cool)
        sh "$CTL" set_mode "$arg" >/dev/null 2>&1
        ;;
    esac
    ;;
  set_interval)
    case "$arg" in
      60|120|300|600)
        sh "$CTL" set_interval "$arg" >/dev/null 2>&1
        ;;
    esac
    ;;
  clear_history)
    sh "$CTL" clear_history >/dev/null 2>&1
    ;;
esac
