#!/system/bin/sh
# Realme GT5 (RMX3820 / AW21012) Awakening Halo Pro 4-Zone Independent Controller
# Hardware sysfs: /sys/class/leds/{red,green,blue}/{trigger,color,br,brightness,tr1,ton,tf1,toff,reg}
# Zero mounts, zero background bloat, instant 12-bit PWM (0..4095) + 24-bit RGB per LED (4 zones).

STATE_DIR="/data/adb/gt5_halo"
STATE_FILE="$STATE_DIR/state.env"
LED_BASE="/sys/class/leds"

mkdir -p "$STATE_DIR"

# Default factory-inspired dual-tone cyan/purple preset (OFF by default until toggled ON)
init_default_state() {
  if [ ! -f "$STATE_FILE" ]; then
    cat > "$STATE_FILE" << 'EOF'
ENABLED=0
MODE=new_always_on_mode
BOOT_RESTORE=1
SCREEN_FOLLOW=0
TR1=6
TON=2
TF1=6
TOFF=2
LED1_ON=1
LED1_R=255
LED1_G=26
LED1_B=82
LED1_BR=60
LED2_ON=1
LED2_R=255
LED2_G=26
LED2_B=82
LED2_BR=60
LED3_ON=1
LED3_R=98
LED3_G=10
LED3_B=255
LED3_BR=60
LED4_ON=1
LED4_R=98
LED4_G=10
LED4_B=255
LED4_BR=60
EOF
  fi
}

load_state() {
  init_default_state
  # shellcheck disable=SC1090
  . "$STATE_FILE"
}

save_state() {
  cat > "${STATE_FILE}.tmp" << EOF
ENABLED=${ENABLED:-0}
MODE=${MODE:-new_always_on_mode}
BOOT_RESTORE=${BOOT_RESTORE:-1}
SCREEN_FOLLOW=${SCREEN_FOLLOW:-0}
TR1=${TR1:-6}
TON=${TON:-2}
TF1=${TF1:-6}
TOFF=${TOFF:-2}
LED1_ON=${LED1_ON:-1}
LED1_R=${LED1_R:-255}
LED1_G=${LED1_G:-26}
LED1_B=${LED1_B:-82}
LED1_BR=${LED1_BR:-60}
LED2_ON=${LED2_ON:-1}
LED2_R=${LED2_R:-255}
LED2_G=${LED2_G:-26}
LED2_B=${LED2_B:-82}
LED2_BR=${LED2_BR:-60}
LED3_ON=${LED3_ON:-1}
LED3_R=${LED3_R:-98}
LED3_G=${LED3_G:-10}
LED3_B=${LED3_B:-255}
LED3_BR=${LED3_BR:-60}
LED4_ON=${LED4_ON:-1}
LED4_R=${LED4_R:-98}
LED4_G=${LED4_G:-10}
LED4_B=${LED4_B:-255}
LED4_BR=${LED4_BR:-60}
EOF
  mv -f "${STATE_FILE}.tmp" "$STATE_FILE"
  chmod 600 "$STATE_FILE"
}

clamp() {
  v="$1"; lo="$2"; hi="$3"
  case "$v" in ''|*[!0-9]*) v="$lo" ;; esac
  [ "$v" -lt "$lo" ] && v="$lo"
  [ "$v" -gt "$hi" ] && v="$hi"
  echo "$v"
}

pct_to_br12() {
  # Convert 0..100% brightness into AW21012 12-bit PWM 0..4095
  p=$(clamp "$1" 0 100)
  echo $(( (p * 4095 + 50) / 100 ))
}

hw_off() {
  for c in red green blue; do
    [ -d "$LED_BASE/$c" ] || continue
    printf '0,0,0,0\n' > "$LED_BASE/$c/color" 2>/dev/null || true
    printf '0,0,0,0\n' > "$LED_BASE/$c/br" 2>/dev/null || true
    printf 'none\n'    > "$LED_BASE/$c/trigger" 2>/dev/null || true
    printf '0\n'       > "$LED_BASE/$c/brightness" 2>/dev/null || true
  done
}

hw_apply() {
  load_state
  if [ "${ENABLED:-0}" != "1" ]; then
    hw_off
    return 0
  fi

  case "$MODE" in
    new_always_on_mode|individual_ctl_breath|breath_mode|blink_mode|horse_race_lamp|cc_mode) ;;
    *) MODE="new_always_on_mode" ;;
  esac

  # Compute per-LED effective RGB & 12-bit brightness (if individual LED switch is OFF -> 0)
  for idx in 1 2 3 4; do
    eval "on=\$LED${idx}_ON; r=\$LED${idx}_R; g=\$LED${idx}_G; b=\$LED${idx}_B; p=\$LED${idx}_BR"
    if [ "${on:-1}" = "1" ]; then
      er=$(clamp "$r" 0 255)
      eg=$(clamp "$g" 0 255)
      eb=$(clamp "$b" 0 255)
      ebr=$(pct_to_br12 "$p")
    else
      er=0; eg=0; eb=0; ebr=0
    fi
    eval "ER${idx}=$er; EG${idx}=$eg; EB${idx}=$eb; EBR${idx}=$ebr"
  done

  # If all 4 LEDs are individually off or 0 brightness, power chip down cleanly
  if [ "$((EBR1 + EBR2 + EBR3 + EBR4))" -eq 0 ]; then
    hw_off
    return 0
  fi

  t_tr1=$(clamp "${TR1:-6}" 0 15)
  t_ton=$(clamp "${TON:-2}" 0 15)
  t_tf1=$(clamp "${TF1:-6}" 0 15)
  t_toff=$(clamp "${TOFF:-2}" 0 15)

  for c in red green blue; do
    [ -d "$LED_BASE/$c" ] || continue
    printf '%s\n' "$MODE" > "$LED_BASE/$c/trigger" 2>/dev/null || true
    if [ "$MODE" = "individual_ctl_breath" ] || [ "$MODE" = "breath_mode" ] || [ "$MODE" = "blink_mode" ]; then
      printf '%s\n' "$t_tr1"  > "$LED_BASE/$c/tr1"  2>/dev/null || true
      printf '%s\n' "$t_ton"  > "$LED_BASE/$c/ton"  2>/dev/null || true
      printf '%s\n' "$t_tf1"  > "$LED_BASE/$c/tf1"  2>/dev/null || true
      printf '%s\n' "$t_toff" > "$LED_BASE/$c/toff" 2>/dev/null || true
    fi
  done

  printf '%s,%s,%s,%s\n' "$ER1" "$ER2" "$ER3" "$ER4" > "$LED_BASE/red/color" 2>/dev/null || true
  printf '%s,%s,%s,%s\n' "$EG1" "$EG2" "$EG3" "$EG4" > "$LED_BASE/green/color" 2>/dev/null || true
  printf '%s,%s,%s,%s\n' "$EB1" "$EB2" "$EB3" "$EB4" > "$LED_BASE/blue/color" 2>/dev/null || true

  br_csv="${EBR1},${EBR2},${EBR3},${EBR4}"
  for c in red green blue; do
    printf '%s\n' "$br_csv" > "$LED_BASE/$c/br" 2>/dev/null || true
  done

  # Commit via brightness trigger
  for c in red green blue; do
    printf '255\n' > "$LED_BASE/$c/brightness" 2>/dev/null || true
  done
}

hw_locate() {
  # Flash ONLY one LED (1..4) in bright white for 1.5s, then restore saved state
  target=$(clamp "${1:-1}" 1 4)
  for c in red green blue; do
    printf 'new_always_on_mode\n' > "$LED_BASE/$c/trigger" 2>/dev/null || true
  done
  c1=0; c2=0; c3=0; c4=0
  b1=0; b2=0; b3=0; b4=0
  eval "c${target}=255; b${target}=3500"
  for c in red green blue; do
    printf '%s,%s,%s,%s\n' "$c1" "$c2" "$c3" "$c4" > "$LED_BASE/$c/color" 2>/dev/null || true
    printf '%s,%s,%s,%s\n' "$b1" "$b2" "$b3" "$b4" > "$LED_BASE/$c/br" 2>/dev/null || true
    printf '255\n' > "$LED_BASE/$c/brightness" 2>/dev/null || true
  done
  sleep 1.4
  hw_apply
}

print_status_json() {
  load_state
  hw_reg20=$(grep '^reg:0x20=' "$LED_BASE/red/reg" 2>/dev/null | head -n 1 | cut -d= -f2)
  [ -z "$hw_reg20" ] && hw_reg20="unknown"
  hw_trig=$(grep -oE '\[[^]]+\]' "$LED_BASE/red/trigger" 2>/dev/null | tr -d '[]')
  [ -z "$hw_trig" ] && hw_trig="none"
  printf '{'
  printf '"enabled":%s,' "$ENABLED"
  printf '"mode":"%s",' "$MODE"
  printf '"boot_restore":%s,' "$BOOT_RESTORE"
  printf '"screen_follow":%s,' "$SCREEN_FOLLOW"
  printf '"tr1":%s,"ton":%s,"tf1":%s,"toff":%s,' "$TR1" "$TON" "$TF1" "$TOFF"
  printf '"hw_reg20":"%s","hw_trigger":"%s",' "$hw_reg20" "$hw_trig"
  printf '"leds":['
  printf '{"id":1,"on":%s,"r":%s,"g":%s,"b":%s,"br":%s},' "$LED1_ON" "$LED1_R" "$LED1_G" "$LED1_B" "$LED1_BR"
  printf '{"id":2,"on":%s,"r":%s,"g":%s,"b":%s,"br":%s},' "$LED2_ON" "$LED2_R" "$LED2_G" "$LED2_B" "$LED2_BR"
  printf '{"id":3,"on":%s,"r":%s,"g":%s,"b":%s,"br":%s},' "$LED3_ON" "$LED3_R" "$LED3_G" "$LED3_B" "$LED3_BR"
  printf '{"id":4,"on":%s,"r":%s,"g":%s,"b":%s,"br":%s}'  "$LED4_ON" "$LED4_R" "$LED4_G" "$LED4_B" "$LED4_BR"
  printf ']}\n'
}

cmd="${1:-status}"
shift 2>/dev/null || true

case "$cmd" in
  status)
    print_status_json
    ;;
  apply)
    hw_apply
    print_status_json
    ;;
  off)
    load_state
    ENABLED=0
    save_state
    hw_off
    print_status_json
    ;;
  on)
    load_state
    ENABLED=1
    save_state
    hw_apply
    print_status_json
    ;;
  toggle)
    load_state
    if [ "${ENABLED:-0}" = "1" ]; then
      ENABLED=0
      save_state
      hw_off
    else
      ENABLED=1
      save_state
      hw_apply
    fi
    print_status_json
    ;;
  set)
    load_state
    for kv in "$@"; do
      k="${kv%%=*}"
      v="${kv#*=}"
      case "$k" in
        ENABLED|BOOT_RESTORE|SCREEN_FOLLOW|LED1_ON|LED2_ON|LED3_ON|LED4_ON)
          eval "$k=\$(clamp \"\$v\" 0 1)" ;;
        MODE)
          case "$v" in
            new_always_on_mode|individual_ctl_breath|breath_mode|blink_mode|horse_race_lamp|cc_mode) MODE="$v" ;;
          esac ;;
        TR1|TON|TF1|TOFF)
          eval "$k=\$(clamp \"\$v\" 0 15)" ;;
        LED1_R|LED1_G|LED1_B|LED2_R|LED2_G|LED2_B|LED3_R|LED3_G|LED3_B|LED4_R|LED4_G|LED4_B)
          eval "$k=\$(clamp \"\$v\" 0 255)" ;;
        LED1_BR|LED2_BR|LED3_BR|LED4_BR)
          eval "$k=\$(clamp \"\$v\" 0 100)" ;;
      esac
    done
    save_state
    hw_apply
    print_status_json
    ;;
  locate)
    hw_locate "${1:-1}"
    print_status_json
    ;;
  hw_off_only)
    hw_off
    ;;
  hw_apply_only)
    hw_apply
    ;;
  *)
    echo "Usage: $0 {status|on|off|toggle|apply|set KEY=VAL...|locate 1..4}" >&2
    exit 2
    ;;
esac
