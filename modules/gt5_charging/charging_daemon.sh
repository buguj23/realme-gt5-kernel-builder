#!/system/bin/sh
# Low-power background daemon for GT5 150W Fast Charging Fix & Charging Recorder.
# - Unplugged: lightweight 15s check (feeds shell-temp every 60s, ~0% CPU, zero wakelocks).
# - Plugged in: maintains shell-temp every 10s, syncs screen state to ICharger HAL on change,
#   re-asserts 150W Hyper mode on plug-in, and samples Power(W)/Temp(C)/SOC(%) every >=60s.

MODDIR="${0%/*}"
CTL="$MODDIR/charging_ctl.sh"
STATE_DIR="/data/adb/gt5_charging"
PID_FILE="$STATE_DIR/daemon.pid"

mkdir -p "$STATE_DIR" 2>/dev/null
echo $$ > "$PID_FILE"

prev_wired=-1
prev_screen=-1
tick=0

sh "$CTL" init >/dev/null 2>&1

while true; do
  wired=0
  [ -r /sys/class/power_supply/usb/online ] && wired=$(cat /sys/class/power_supply/usb/online 2>/dev/null)
  [ -z "$wired" ] && wired=0

  st=$(getprop debug.tracing.screen_state 2>/dev/null)
  case "$st" in
    2) cur_screen=1 ;;
    1|3|4) cur_screen=0 ;;
    *) cur_screen=$prev_screen ;;
  esac

  if [ "$wired" -eq 1 ]; then
    # Plug-in transition -> let UFCS/SuperVOOC handshake settle cleanly (4s) on fresh plug-in,
    # then zero-interference verify profile & capture initial post-handshake point
    if [ "$prev_wired" -ne 1 ]; then
      [ "$prev_wired" -eq 0 ] && sleep 4
      sh "$CTL" apply >/dev/null 2>&1
      sh "$CTL" sample_now >/dev/null 2>&1
      prev_wired=1
      prev_screen=$cur_screen
      tick=0
    else
      # Always feed shell-temp every cycle (~10s) so oplus_chg & charger-V5-service see live skin temp
      sh "$CTL" feed_shell >/dev/null 2>&1
      # Sync screen ON/OFF immediately on transition so charging_hyper_mode_config.txt runs when screen turns off
      if [ "$cur_screen" != "$prev_screen" ] && [ "$cur_screen" -ge 0 ]; then
        sh "$CTL" sync_screen >/dev/null 2>&1
        prev_screen=$cur_screen
      fi
      # Sample check (only writes to TSV when >= SAMPLE_INTERVAL or protocol changes; refreshes live JSON every 20s)
      tick=$((tick + 1))
      if [ $((tick % 2)) -eq 0 ]; then
        sh "$CTL" sample >/dev/null 2>&1
      fi
    fi
    sleep 10
  else
    if [ "$prev_wired" -eq 1 ]; then
      # Unplug transition -> close session cleanly
      sh "$CTL" sample >/dev/null 2>&1
      prev_wired=0
      tick=0
    fi
    if [ "$cur_screen" != "$prev_screen" ] && [ "$cur_screen" -ge 0 ]; then
      sh "$CTL" sync_screen >/dev/null 2>&1
      prev_screen=$cur_screen
    fi
    # Feed shell-temp once per minute even while idle so shell_back is never stale (-127C)
    tick=$((tick + 1))
    if [ $((tick % 4)) -eq 0 ]; then
      sh "$CTL" feed_shell >/dev/null 2>&1
    fi
    sleep 15
  fi
done
