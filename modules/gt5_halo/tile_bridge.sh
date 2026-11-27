#!/system/bin/sh
# Event-driven inotifyd bridge for com.gt5.halotile Quick Settings Tile
# Invoked by: inotifyd /data/adb/modules/gt5_halo/tile_bridge.sh /data/user/0/com.gt5.halotile/files:w
# Args: $1=EVENTS $2=DIR $3=FILENAME

[ "$3" = "cmd" ] || exit 0

MODDIR="${0%/*}"
CTL="$MODDIR/halo_ctl.sh"
CMD_FILE="$2/$3"
[ -f "$CMD_FILE" ] || exit 0

line=$(head -n 1 "$CMD_FILE" 2>/dev/null | tr -d '\r')
[ -n "$line" ] || exit 0

# Strict allowlist parsing (zero shell eval / injection surface)
set -- $line
action="${1:-}"
arg="${2:-}"

case "$action" in
  on)
    HALO_FROM_TILE=1 sh "$CTL" on >/dev/null 2>&1
    ;;
  off)
    HALO_FROM_TILE=1 sh "$CTL" off >/dev/null 2>&1
    ;;
  toggle)
    HALO_FROM_TILE=1 sh "$CTL" toggle >/dev/null 2>&1
    ;;
  mode)
    case "$arg" in
      always_on|breath|blink|marquee|rainbow)
        HALO_FROM_TILE=1 sh "$CTL" set ENABLED=1 MODE="$arg" >/dev/null 2>&1
        ;;
    esac
    ;;
  br)
    case "$arg" in
      ''|*[!0-9]*) exit 0 ;;
    esac
    [ "$arg" -lt 1 ] && arg=1
    [ "$arg" -gt 100 ] && arg=100
    HALO_FROM_TILE=1 sh "$CTL" set ENABLED=1 \
      LED1_BR="$arg" LED2_BR="$arg" LED3_BR="$arg" LED4_BR="$arg" >/dev/null 2>&1
    ;;
esac
