#!/system/bin/sh
# Realme GT5 (RMX3820 / AW21012) Awakening Halo Pro 4-Zone Independent Controller v1.1
#
# Reverse-engineered from stock leds_aw210xx.ko:
#   - led_mode=2 (new_always_on_mode):
#       * Global 12-bit gamma PWM from cdev->brightness (0..255 -> 0..4064)
#       * 4 independent per-LED RGB COL registers (0x46..0x51) from /sys/class/leds/{red,green,blue}/color
#   - led_mode=5 (individual_ctl_breath):
#       * 100% autonomous AW21012 hardware breathing (reg 0x82/0x83 = TR1/TON/TF1/TOFF, 0% CPU)
#       * 4 independent per-LED RGB COL registers from /sys/class/leds/{red,green,blue}/color
#   - Legacy modes (cc_mode=1, blink_mode=3, breath_mode=4) ignore color[] and mirror scalar brightness
#     across all 4 LEDs -> therefore ALL 5 modes below drive new_always_on_mode (2) or
#     individual_ctl_breath (5), guaranteeing 100% exact per-LED RGB color, independent brightness,
#     and independent ON/OFF in EVERY mode!

STATE_DIR="/data/adb/gt5_halo"
STATE_FILE="$STATE_DIR/state.env"
ANIM_PID_FILE="$STATE_DIR/anim.pid"
ANIM_GEN_FILE="$STATE_DIR/anim.gen"
LED_BASE="/sys/class/leds"

mkdir -p "$STATE_DIR"

init_default_state() {
  if [ ! -f "$STATE_FILE" ]; then
    cat > "$STATE_FILE" << 'EOF'
ENABLED=0
MODE=always_on
BOOT_RESTORE=1
SCREEN_FOLLOW=0
SPEED=5
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
  # Migrate v1.0 mode names transparently
  case "${MODE:-always_on}" in
    new_always_on_mode|cc_mode) MODE="always_on" ;;
    individual_ctl_breath|breath_mode) MODE="breath" ;;
    blink_mode) MODE="blink" ;;
    horse_race_lamp) MODE="marquee" ;;
    always_on|breath|blink|marquee|rainbow) ;;
    *) MODE="always_on" ;;
  esac
  SPEED="${SPEED:-5}"
}

save_state() {
  cat > "${STATE_FILE}.tmp" << EOF
ENABLED=${ENABLED:-0}
MODE=${MODE:-always_on}
BOOT_RESTORE=${BOOT_RESTORE:-1}
SCREEN_FOLLOW=${SCREEN_FOLLOW:-0}
SPEED=${SPEED:-5}
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

stop_anim() {
  rm -f "$ANIM_GEN_FILE"
  if [ -f "$ANIM_PID_FILE" ]; then
    old_pid=$(cat "$ANIM_PID_FILE" 2>/dev/null || true)
    rm -f "$ANIM_PID_FILE"
    if [ -n "$old_pid" ] && [ "$old_pid" != "$$" ]; then
      kill "$old_pid" 2>/dev/null || true
    fi
  fi
}

anim_alive() {
  [ -n "$1" ] && [ "$(cat "$ANIM_GEN_FILE" 2>/dev/null)" = "$1" ]
}

# Pitch-black frame (COL=0mA on all 4 LEDs) without toggling CHIPEN=0 (avoids 2.2ms chip re-init during blink)
hw_blank_frame() {
  for c in red green blue; do
    [ -d "$LED_BASE/$c" ] || continue
    printf '0,0,0,0\n' > "$LED_BASE/$c/color" 2>/dev/null || true
    printf '1\n'       > "$LED_BASE/$c/brightness" 2>/dev/null || true
  done
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

# Write one exact 4-LED frame using hardware new_always_on_mode (led_mode=2).
# Args: r1 g1 b1 br1  r2 g2 b2 br2  r3 g3 b3 br3  r4 g4 b4 br4  [set_trigger:1|0]
# Uses max_br -> global 12-bit gamma PWM (brightness 1..255) and scales each LED's RGB by br_i / max_br
# so colors remain accurate even at low brightness AND disabled/0% LEDs stay 100% OFF!
hw_write_frame() {
  r1=$1; g1=$2; b1=$3; p1=$4
  r2=$5; g2=$6; b2=$7; p2=$8
  r3=$9; g3=${10}; b3=${11}; p3=${12}
  r4=${13}; g4=${14}; b4=${15}; p4=${16}
  set_trig=${17:-1}

  max_p=$p1
  [ "$p2" -gt "$max_p" ] && max_p=$p2
  [ "$p3" -gt "$max_p" ] && max_p=$p3
  [ "$p4" -gt "$max_p" ] && max_p=$p4

  if [ "$max_p" -le 0 ]; then
    hw_off
    return 0
  fi

  # Global 12-bit gamma-mapped brightness (1..255)
  g_pwm=$(( (max_p * 255 + 50) / 100 ))
  [ "$g_pwm" -lt 1 ] && g_pwm=1
  [ "$g_pwm" -gt 255 ] && g_pwm=255

  # Per-LED color scaled by relative brightness (p_i / max_p) -> exact per-LED brightness & true 0 when off
  sr1=$(( (r1 * p1 + max_p / 2) / max_p )); sg1=$(( (g1 * p1 + max_p / 2) / max_p )); sb1=$(( (b1 * p1 + max_p / 2) / max_p ))
  sr2=$(( (r2 * p2 + max_p / 2) / max_p )); sg2=$(( (g2 * p2 + max_p / 2) / max_p )); sb2=$(( (b2 * p2 + max_p / 2) / max_p ))
  sr3=$(( (r3 * p3 + max_p / 2) / max_p )); sg3=$(( (g3 * p3 + max_p / 2) / max_p )); sb3=$(( (b3 * p3 + max_p / 2) / max_p ))
  sr4=$(( (r4 * p4 + max_p / 2) / max_p )); sg4=$(( (g4 * p4 + max_p / 2) / max_p )); sb4=$(( (b4 * p4 + max_p / 2) / max_p ))

  if [ "$set_trig" = "1" ]; then
    for c in red green blue; do
      printf 'new_always_on_mode\n' > "$LED_BASE/$c/trigger" 2>/dev/null || true
    done
  fi

  printf '%s,%s,%s,%s\n' "$sr1" "$sr2" "$sr3" "$sr4" > "$LED_BASE/red/color" 2>/dev/null || true
  printf '%s,%s,%s,%s\n' "$sg1" "$sg2" "$sg3" "$sg4" > "$LED_BASE/green/color" 2>/dev/null || true
  printf '%s,%s,%s,%s\n' "$sb1" "$sb2" "$sb3" "$sb4" > "$LED_BASE/blue/color" 2>/dev/null || true

  for c in red green blue; do
    printf '%s\n' "$g_pwm" > "$LED_BASE/$c/brightness" 2>/dev/null || true
  done
}

# Hardware autonomous 4-LED breathing (led_mode=5: individual_ctl_breath, 0% CPU)
# Uses color[0..3] scaled by LED_BR/100 (0 when LED OFF) -> exact per-LED color, peak brightness & ON/OFF!
hw_apply_breath() {
  t_tr1=$(clamp "${TR1:-6}" 0 15)
  t_ton=$(clamp "${TON:-2}" 0 15)
  t_tf1=$(clamp "${TF1:-6}" 0 15)
  t_toff=$(clamp "${TOFF:-2}" 0 15)

  for idx in 1 2 3 4; do
    eval "on=\$LED${idx}_ON; r=\$LED${idx}_R; g=\$LED${idx}_G; b=\$LED${idx}_B; p=\$LED${idx}_BR"
    if [ "${on:-1}" = "1" ] && [ "${p:-0}" -gt 0 ]; then
      er=$(( (r * p + 50) / 100 ))
      eg=$(( (g * p + 50) / 100 ))
      eb=$(( (b * p + 50) / 100 ))
      # Ensure non-zero channels don't round down to 0 at 1%
      [ "$r" -gt 0 ] && [ "$er" -eq 0 ] && er=1
      [ "$g" -gt 0 ] && [ "$eg" -eq 0 ] && eg=1
      [ "$b" -gt 0 ] && [ "$eb" -eq 0 ] && eb=1
    else
      er=0; eg=0; eb=0
    fi
    eval "ER${idx}=$er; EG${idx}=$eg; EB${idx}=$eb"
  done

  if [ "$((ER1+EG1+EB1+ER2+EG2+EB2+ER3+EG3+EB3+ER4+EG4+EB4))" -eq 0 ]; then
    hw_off
    return 0
  fi

  for c in red green blue; do
    printf 'individual_ctl_breath\n' > "$LED_BASE/$c/trigger" 2>/dev/null || true
    printf '%s\n' "$t_tr1"  > "$LED_BASE/$c/tr1"  2>/dev/null || true
    printf '%s\n' "$t_ton"  > "$LED_BASE/$c/ton"  2>/dev/null || true
    printf '%s\n' "$t_tf1"  > "$LED_BASE/$c/tf1"  2>/dev/null || true
    printf '%s\n' "$t_toff" > "$LED_BASE/$c/toff" 2>/dev/null || true
  done

  printf '%s,%s,%s,%s\n' "$ER1" "$ER2" "$ER3" "$ER4" > "$LED_BASE/red/color" 2>/dev/null || true
  printf '%s,%s,%s,%s\n' "$EG1" "$EG2" "$EG3" "$EG4" > "$LED_BASE/green/color" 2>/dev/null || true
  printf '%s,%s,%s,%s\n' "$EB1" "$EB2" "$EB3" "$EB4" > "$LED_BASE/blue/color" 2>/dev/null || true

  for c in red green blue; do
    printf '255\n' > "$LED_BASE/$c/brightness" 2>/dev/null || true
  done
}

set_rainbow_rgb() {
  eval "RR$1=$2; RG$1=$3; RB$1=$4"
}

# Frame-accurate animation worker for blink / marquee / rainbow (strictly honors per-LED ON/OFF, RGB & brightness!)
run_anim_loop() {
  mode="$1"
  my_gen="$2"
  load_state

  # Compute active per-LED targets
  for idx in 1 2 3 4; do
    eval "on=\$LED${idx}_ON; r=\$LED${idx}_R; g=\$LED${idx}_G; b=\$LED${idx}_B; p=\$LED${idx}_BR"
    if [ "${on:-1}" = "1" ] && [ "${p:-0}" -gt 0 ]; then
      eval "AR${idx}=$r; AG${idx}=$g; AB${idx}=$b; AP${idx}=$p"
    else
      eval "AR${idx}=0; AG${idx}=0; AB${idx}=0; AP${idx}=0"
    fi
  done

  if [ "$((AP1 + AP2 + AP3 + AP4))" -eq 0 ]; then
    hw_off
    exit 0
  fi

  # Speed 1 (slow) .. 10 (fast) -> step sleep in seconds
  spd=$(clamp "${SPEED:-5}" 1 10)
  case "$spd" in
    1)  step="0.90" ;;
    2)  step="0.72" ;;
    3)  step="0.56" ;;
    4)  step="0.44" ;;
    5)  step="0.34" ;;
    6)  step="0.26" ;;
    7)  step="0.20" ;;
    8)  step="0.15" ;;
    9)  step="0.11" ;;
    10) step="0.08" ;;
  esac

  trap 'exit 0' TERM INT

  if [ "$mode" = "blink" ]; then
    # Frame 0 (ON) was already drawn synchronously by hw_apply
    on_ms=$(( ( ${TON:-2} + 2 ) * 120 ))
    off_ms=$(( ( ${TOFF:-2} + 2 ) * 120 ))
    on_s=$(printf '%d.%03d' $((on_ms/1000)) $((on_ms%1000)))
    off_s=$(printf '%d.%03d' $((off_ms/1000)) $((off_ms%1000)))
    while true; do
      sleep "$on_s"
      anim_alive "$my_gen" || exit 0
      hw_blank_frame
      sleep "$off_s"
      anim_alive "$my_gen" || exit 0
      hw_write_frame "$AR1" "$AG1" "$AB1" "$AP1" "$AR2" "$AG2" "$AB2" "$AP2" \
                     "$AR3" "$AG3" "$AB3" "$AP3" "$AR4" "$AG4" "$AB4" "$AP4" 0
    done
  elif [ "$mode" = "marquee" ]; then
    # Cycle sequentially ONLY through enabled LEDs (disabled LEDs stay 100% OFF!)
    # Each LED shines in its own configured color & brightness!
    active_list=""
    [ "$AP1" -gt 0 ] && active_list="$active_list 1"
    [ "$AP2" -gt 0 ] && active_list="$active_list 2"
    [ "$AP3" -gt 0 ] && active_list="$active_list 3"
    [ "$AP4" -gt 0 ] && active_list="$active_list 4"
    # First active LED was drawn synchronously by hw_apply; sleep then step starting from next
    skip_first=1
    while true; do
      for cur in $active_list; do
        if [ "$skip_first" = "1" ]; then
          skip_first=0
          sleep "$step"
          continue
        fi
        anim_alive "$my_gen" || exit 0
        p1=0; p2=0; p3=0; p4=0
        eval "p${cur}=\$AP${cur}"
        hw_write_frame "$AR1" "$AG1" "$AB1" "$p1" "$AR2" "$AG2" "$AB2" "$p2" \
                       "$AR3" "$AG3" "$AB3" "$p3" "$AR4" "$AG4" "$AB4" "$p4" 0
        sleep "$step"
      done
    done
  elif [ "$mode" = "rainbow" ]; then
    # 12-step smooth rainbow palette, phase-shifted across the 4 zones;
    # disabled LEDs stay 100% OFF and active LEDs honor their individual brightness!
    set -- \
      "255 0 0"     "255 128 0"   "255 255 0"   "128 255 0" \
      "0 255 0"     "0 255 128"   "0 255 255"   "0 128 255" \
      "0 0 255"     "128 0 255"   "255 0 255"   "255 0 128"
    # Step 0 was drawn synchronously by hw_apply; start loop from step 1 after $step
    idx=1
    while true; do
      sleep "$step"
      anim_alive "$my_gen" || exit 0
      i1=$(( (idx % 12) + 1 ))
      i2=$(( ((idx + 3) % 12) + 1 ))
      i3=$(( ((idx + 6) % 12) + 1 ))
      i4=$(( ((idx + 9) % 12) + 1 ))
      eval "c1=\${$i1}; c2=\${$i2}; c3=\${$i3}; c4=\${$i4}"
      # shellcheck disable=SC2086
      set_rainbow_rgb 1 $c1; set_rainbow_rgb 2 $c2; set_rainbow_rgb 3 $c3; set_rainbow_rgb 4 $c4
      hw_write_frame "$RR1" "$RG1" "$RB1" "$AP1" "$RR2" "$RG2" "$RB2" "$AP2" \
                     "$RR3" "$RG3" "$RB3" "$AP3" "$RR4" "$RG4" "$RB4" "$AP4" 0
      idx=$(( (idx + 1) % 12 ))
    done
  fi
}

hw_apply() {
  stop_anim
  load_state
  if [ "${ENABLED:-0}" != "1" ]; then
    hw_off
    return 0
  fi

  for idx in 1 2 3 4; do
    eval "on=\$LED${idx}_ON; r=\$LED${idx}_R; g=\$LED${idx}_G; b=\$LED${idx}_B; p=\$LED${idx}_BR"
    if [ "${on:-1}" = "1" ] && [ "${p:-0}" -gt 0 ]; then
      eval "FR${idx}=\$(clamp \"\$r\" 0 255); FG${idx}=\$(clamp \"\$g\" 0 255); FB${idx}=\$(clamp \"\$b\" 0 255); FP${idx}=\$(clamp \"\$p\" 0 100)"
    else
      eval "FR${idx}=0; FG${idx}=0; FB${idx}=0; FP${idx}=0"
    fi
  done

  if [ "$((FP1 + FP2 + FP3 + FP4))" -eq 0 ]; then
    hw_off
    return 0
  fi

  case "$MODE" in
    always_on)
      hw_write_frame "$FR1" "$FG1" "$FB1" "$FP1" "$FR2" "$FG2" "$FB2" "$FP2" \
                     "$FR3" "$FG3" "$FB3" "$FP3" "$FR4" "$FG4" "$FB4" "$FP4" 1
      ;;
    breath)
      hw_apply_breath
      ;;
    blink|marquee|rainbow)
      # Draw frame 0 synchronously so chip activates immediately & WebUI readback sees CHIP(0x01)
      if [ "$MODE" = "blink" ]; then
        hw_write_frame "$FR1" "$FG1" "$FB1" "$FP1" "$FR2" "$FG2" "$FB2" "$FP2" \
                       "$FR3" "$FG3" "$FB3" "$FP3" "$FR4" "$FG4" "$FB4" "$FP4" 1
      elif [ "$MODE" = "marquee" ]; then
        first_led=1
        for i in 1 2 3 4; do
          eval "fp=\$FP$i"
          if [ "$fp" -gt 0 ]; then first_led=$i; break; fi
        done
        mp1=0; mp2=0; mp3=0; mp4=0
        eval "mp${first_led}=\$FP${first_led}"
        hw_write_frame "$FR1" "$FG1" "$FB1" "$mp1" "$FR2" "$FG2" "$FB2" "$mp2" \
                       "$FR3" "$FG3" "$FB3" "$mp3" "$FR4" "$FG4" "$FB4" "$mp4" 1
      elif [ "$MODE" = "rainbow" ]; then
        hw_write_frame 255 0 0 "$FP1" 128 255 0 "$FP2" 0 255 255 "$FP3" 128 0 255 "$FP4" 1
      fi
      # Write generation token BEFORE spawning so child can never race on startup
      gen="$$.$(cut -d' ' -f1 /proc/uptime 2>/dev/null || date +%s)"
      printf '%s\n' "$gen" > "$ANIM_GEN_FILE"
      nohup sh "$0" _anim "$MODE" "$gen" </dev/null >/dev/null 2>&1 &
      printf '%s\n' "$!" > "$ANIM_PID_FILE"
      ;;
    *)
      hw_write_frame "$FR1" "$FG1" "$FB1" "$FP1" "$FR2" "$FG2" "$FB2" "$FP2" \
                     "$FR3" "$FG3" "$FB3" "$FP3" "$FR4" "$FG4" "$FB4" "$FP4" 1
      ;;
  esac
}

hw_locate() {
  stop_anim
  target=$(clamp "${1:-1}" 1 4)
  p1=0; p2=0; p3=0; p4=0
  eval "p${target}=85"
  hw_write_frame 255 255 255 "$p1" 255 255 255 "$p2" 255 255 255 "$p3" 255 255 255 "$p4" 1
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
  printf '"speed":%s,' "$SPEED"
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
  _anim)
    run_anim_loop "${1:-marquee}" "${2:-}"
    ;;
  status)
    print_status_json
    ;;
  apply)
    hw_apply
    print_status_json
    ;;
  off)
    stop_anim
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
      stop_anim
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
            always_on|breath|blink|marquee|rainbow) MODE="$v" ;;
          esac ;;
        SPEED)
          SPEED=$(clamp "$v" 1 10) ;;
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
    stop_anim
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
