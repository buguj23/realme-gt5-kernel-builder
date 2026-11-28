#!/system/bin/sh
# GT5 (RMX3820 / 22635) 150W SuperVOOC Fast-Charging Fix & Telemetry/History Engine
# Strictly uses verified safe sysfs allowlist ONLY (never wildcard-reads /sys/class/oplus_chg/*).

MODDIR="${0%/*}"
STATE_DIR="/data/adb/gt5_charging"
CFG_FILE="$STATE_DIR/config.env"
TSV_FILE="$STATE_DIR/sessions.tsv"
META_FILE="$STATE_DIR/active_session.env"
LIVE_LOCAL="$STATE_DIR/live.json"
HIST_LOCAL="$STATE_DIR/history.json"
APP_PKG="com.gt5.charging"
APP_FILES="/data/user/0/$APP_PKG/files"
ICHARGER_SVC="vendor.oplus.hardware.charger.ICharger/default"

mkdir -p "$STATE_DIR" 2>/dev/null

# Default configuration
CHARGE_MODE="hyper"      # hyper | balanced | cool
SAMPLE_INTERVAL=60       # seconds (>= 60: 60, 120, 300, 600)

load_config() {
  if [ -f "$CFG_FILE" ]; then
    # shellcheck disable=SC1090
    . "$CFG_FILE"
  fi
  case "$CHARGE_MODE" in
    hyper|balanced|cool) ;;
    *) CHARGE_MODE="hyper" ;;
  esac
  case "$SAMPLE_INTERVAL" in
    60|120|300|600) ;;
    *) SAMPLE_INTERVAL=60 ;;
  esac
}

save_config() {
  cat > "$CFG_FILE.tmp" <<EOF
CHARGE_MODE=$CHARGE_MODE
SAMPLE_INTERVAL=$SAMPLE_INTERVAL
EOF
  mv -f "$CFG_FILE.tmp" "$CFG_FILE"
  chmod 0644 "$CFG_FILE"
}

safe_read() {
  [ -r "$1" ] && cat "$1" 2>/dev/null | tr -d '\r\n' || echo ""
}

safe_int() {
  v=$(safe_read "$1")
  case "$v" in
    ''|*[!0-9-]*) echo "${2:-0}" ;;
    *) echo "$v" ;;
  esac
}

# Cache thermal zone paths once per invocation/file
TZ_CACHE="$STATE_DIR/tz_cache.env"
init_thermal_zones() {
  if [ -f "$TZ_CACHE" ]; then
    # shellcheck disable=SC1090
    . "$TZ_CACHE"
    if [ -r "${TZ_SHELL_BACK:-/nonexistent}/temp" ] && [ -r "${TZ_BATT:-/nonexistent}/temp" ]; then
      return 0
    fi
  fi
  TZ_SKIN=""
  TZ_BATT=""
  TZ_BATT_CON=""
  TZ_SHELL_FRONT=""
  TZ_SHELL_FRAME=""
  TZ_SHELL_BACK=""
  for z in /sys/class/thermal/thermal_zone*; do
    [ -r "$z/type" ] || continue
    t=$(cat "$z/type" 2>/dev/null)
    case "$t" in
      skin-msm-therm) TZ_SKIN="$z" ;;
      battery) TZ_BATT="$z" ;;
      batt0_con_therm_adc) TZ_BATT_CON="$z" ;;
      shell_front) TZ_SHELL_FRONT="$z" ;;
      shell_frame) TZ_SHELL_FRAME="$z" ;;
      shell_back) TZ_SHELL_BACK="$z" ;;
    esac
  done
  cat > "$TZ_CACHE" <<EOF
TZ_SKIN=$TZ_SKIN
TZ_BATT=$TZ_BATT
TZ_BATT_CON=$TZ_BATT_CON
TZ_SHELL_FRONT=$TZ_SHELL_FRONT
TZ_SHELL_FRAME=$TZ_SHELL_FRAME
TZ_SHELL_BACK=$TZ_SHELL_BACK
EOF
}

# 1. Shell temperature bridge (replaces ColorOS horae feeding /proc/shell-temp)
feed_shell_temp() {
  init_thermal_zones
  batt_mc=30000
  if [ -n "$TZ_BATT" ] && [ -r "$TZ_BATT/temp" ]; then
    batt_mc=$(safe_int "$TZ_BATT/temp" 30000)
  else
    bt=$(safe_int /sys/class/power_supply/battery/temp 300)
    batt_mc=$((bt * 100))
  fi

  skin_mc=$batt_mc
  if [ -n "$TZ_SKIN" ] && [ -r "$TZ_SKIN/temp" ]; then
    s=$(safe_int "$TZ_SKIN/temp" 0)
    if [ "$s" -gt 5000 ] && [ "$s" -lt 75000 ]; then
      skin_mc=$s
    fi
  fi

  con_mc=$batt_mc
  if [ -n "$TZ_BATT_CON" ] && [ -r "$TZ_BATT_CON/temp" ]; then
    c=$(safe_int "$TZ_BATT_CON/temp" 0)
    if [ "$c" -gt 5000 ] && [ "$c" -lt 75000 ]; then
      con_mc=$c
    fi
  fi

  # Calibrated shell skin model (closely mirrors ColorOS horae weighting)
  shell_back=$(( (45 * skin_mc + 40 * batt_mc + 15 * con_mc) / 100 ))
  [ "$shell_back" -lt 10000 ] && shell_back=10000
  [ "$shell_back" -gt 58000 ] && shell_back=58000
  shell_front=$((shell_back - 300))
  shell_frame=$((shell_back + 200))

  if [ -w /proc/shell-temp ]; then
    printf '0 %d\n' "$shell_front" > /proc/shell-temp 2>/dev/null
    printf '1 %d\n' "$shell_frame" > /proc/shell-temp 2>/dev/null
    printf '2 %d\n' "$shell_back" > /proc/shell-temp 2>/dev/null
  fi
}

# Parse Parcel hex return value from `service call` (second 32-bit word)
parse_parcel_int() {
  awk '
    /Parcel\(/ {
      gsub(/[()'\'']/, "", $0)
      for (i = 1; i <= NF; i++) {
        if ($i ~ /^[0-9a-fA-F]{8}$/) {
          c++
          if (c == 2) {
            print strtonum("0x" $i)
            exit
          }
        }
      }
    }
  '
}

# Fallback hex->dec without gawk strtonum (Android toybox/bionic awk compatible)
parse_parcel_hex_to_dec() {
  hex=$(sed -n 's/.*Parcel([[:space:]]*[0-9a-fA-F]\{8\}[[:space:]]*\([0-9a-fA-F]\{8\}\).*/\1/p' | head -n 1)
  if [ -n "$hex" ]; then
    printf '%d\n' "0x$hex" 2>/dev/null || echo "-1"
  else
    echo "-1"
  fi
}

icharger_get_custom_mode() {
  service call "$ICHARGER_SVC" 22 2>/dev/null | parse_parcel_hex_to_dec
}

icharger_get_smart_mode() {
  service call "$ICHARGER_SVC" 57 2>/dev/null | parse_parcel_hex_to_dec
}

get_screen_on() {
  # Android SurfaceFlinger Display.STATE_OFF=1, Display.STATE_ON=2, DOZE=3/4
  st=$(getprop debug.tracing.screen_state 2>/dev/null)
  case "$st" in
    2) echo "1" ;;
    1|3|4) echo "0" ;;
    *)
      if dumpsys power 2>/dev/null | grep -q 'mWakefulness=Awake'; then
        echo "1"
      else
        echo "0"
      fi
      ;;
  esac
}

sync_screen_status() {
  sc=$(get_screen_on)
  # Verified via charger-V5-service disassembly & live logcat:
  # notifyScreenStatus(0) = screen OFF -> starts 150W scale_chg hyper thread
  # notifyScreenStatus(1) = screen ON  -> stops screen-off scale_chg thread
  service call "$ICHARGER_SVC" 78 i32 "$sc" >/dev/null 2>&1
  echo "$sc" > "$STATE_DIR/last_screen_state"
}

apply_charge_mode() {
  load_config
  feed_shell_temp

  # Always ensure charging is enabled and slow_chg is cleared
  [ -w /sys/class/oplus_chg/battery/mmi_charging_enable ] && echo 1 > /sys/class/oplus_chg/battery/mmi_charging_enable 2>/dev/null
  [ -w /sys/class/oplus_chg/battery/slow_chg_en ] && echo "0,0,0,0" > /sys/class/oplus_chg/battery/slow_chg_en 2>/dev/null

  batt_temp_d1=$(safe_int /sys/class/power_supply/battery/temp 300)

  case "$CHARGE_MODE" in
    hyper)
      # 150W Hyper Speed Charge Mode (loads /odm/firmware/fastchg/22635/charging_hyper_mode_config.txt: 40.5C ceiling)
      service call "$ICHARGER_SVC" 88 i32 3 i32 1 >/dev/null 2>&1
      # Disable BCC Life Mode anode cap (smart_charge_mode=0 -> sends bcc_current=0 to voocphy)
      service call "$ICHARGER_SVC" 94 s16 "0" >/dev/null 2>&1
      # Clear stale cool_down ONLY when battery is safely below 38.5C (never bypass >=40.5C hardware thermal step-down)
      if [ "$batt_temp_d1" -lt 385 ] && [ -w /sys/class/oplus_chg/battery/cool_down ]; then
        echo 0 > /sys/class/oplus_chg/battery/cool_down 2>/dev/null
      fi
      ;;
    balanced)
      # Stock balanced thermal table (36.0C ceiling) + BCC life mode ON
      service call "$ICHARGER_SVC" 88 i32 3 i32 0 >/dev/null 2>&1
      service call "$ICHARGER_SVC" 94 s16 "1" >/dev/null 2>&1
      if [ "$batt_temp_d1" -lt 355 ] && [ -w /sys/class/oplus_chg/battery/cool_down ]; then
        echo 0 > /sys/class/oplus_chg/battery/cool_down 2>/dev/null
      fi
      ;;
    cool)
      # Low-heat battery protection (~35-40W cap via Cool_Down_Oplus_Curve level 14 = 4000mA)
      service call "$ICHARGER_SVC" 88 i32 3 i32 0 >/dev/null 2>&1
      service call "$ICHARGER_SVC" 94 s16 "1" >/dev/null 2>&1
      [ -w /sys/class/oplus_chg/battery/cool_down ] && echo 14 > /sys/class/oplus_chg/battery/cool_down 2>/dev/null
      ;;
  esac

  sync_screen_status
}

# Read comprehensive live telemetry into shell variables
read_telemetry() {
  init_thermal_zones
  T_TS=$(date +%s)

  # Parse battery_log_content (safe single read)
  # Fields (1-indexed after leading empty field from leading comma):
  # $2=batt_temp $3=shell_temp $4=vbat_mv $5=vbat_min_mv $6=ibat_ma $9=batt_soc $10=ui_soc
  # $11=wired_online $12=charge_type $13=ibus_ma $14=vbus_mv $16=led_on $24=cool_down $30=subboard_temp
  blc=$(safe_read /sys/class/oplus_chg/battery/battery_log_content)
  if [ -n "$blc" ]; then
    eval "$(echo "$blc" | awk -F, '{
      printf "T_BATT_TEMP=%d; T_KERNEL_SHELL=%d; T_VBAT_MV=%d; T_VBAT_MIN_MV=%d; T_IBAT_MA=%d; T_SOC=%d; T_WIRED=%d; T_IBUS_MA=%d; T_VBUS_MV=%d; T_LED_ON=%d; T_COOL_DOWN=%d; T_SUB_TEMP=%d;",
        ($2+0), ($3+0), ($4+0), ($5+0), ($6+0), ($10+0), ($11+0), ($13+0), ($14+0), ($16+0), ($24+0), ($30+0)
    }')"
  else
    T_BATT_TEMP=$(safe_int /sys/class/power_supply/battery/temp 300)
    T_KERNEL_SHELL=-2740
    T_VBAT_MV=$(( $(safe_int /sys/class/power_supply/battery/voltage_now 4000000) / 1000 ))
    T_VBAT_MIN_MV=$T_VBAT_MV
    T_IBAT_MA=$(safe_int /sys/class/power_supply/battery/current_now 0)
    T_SOC=$(safe_int /sys/class/power_supply/battery/capacity 0)
    T_WIRED=$(safe_int /sys/class/power_supply/usb/online 0)
    T_IBUS_MA=$(( $(safe_int /sys/class/power_supply/usb/current_now 0) / 1000 ))
    T_VBUS_MV=$(( $(safe_int /sys/class/power_supply/usb/voltage_now 0) / 1000 ))
    T_LED_ON=$(get_screen_on)
    T_COOL_DOWN=$(safe_int /sys/class/oplus_chg/battery/cool_down 0)
    T_SUB_TEMP=$T_BATT_TEMP
  fi

  # Also verify against standard power_supply nodes
  T_STATUS=$(safe_read /sys/class/power_supply/battery/status)
  [ -z "$T_STATUS" ] && T_STATUS="Unknown"
  ps_soc=$(safe_int /sys/class/power_supply/battery/capacity -1)
  [ "$ps_soc" -ge 0 ] && T_SOC=$ps_soc
  ps_temp=$(safe_int /sys/class/power_supply/battery/temp -999)
  # Use battery power_supply temp (0.1C) if valid, else gauge batt_temp
  if [ "$ps_temp" -gt -200 ] && [ "$ps_temp" -lt 850 ]; then
    T_BATT_TEMP=$ps_temp
  fi
  ps_usb_online=$(safe_int /sys/class/power_supply/usb/online 0)
  [ "$ps_usb_online" -eq 1 ] && T_WIRED=1
  ps_vbus_uv=$(safe_int /sys/class/power_supply/usb/voltage_now 0)
  ps_ibus_ua=$(safe_int /sys/class/power_supply/usb/current_now 0)
  T_USB_TYPE=$(safe_read /sys/class/power_supply/usb/type)
  [ -z "$T_USB_TYPE" ] && T_USB_TYPE="Unknown"

  [ "$T_VBUS_MV" -le 0 ] && [ "$ps_vbus_uv" -gt 0 ] && T_VBUS_MV=$((ps_vbus_uv / 1000))
  if [ "$T_IBUS_MA" -le 0 ] && [ "$ps_ibus_ua" -gt 0 ]; then
    T_IBUS_MA=$((ps_ibus_ua / 1000))
  fi
  [ "$T_IBUS_MA" -lt 0 ] && T_IBUS_MA=0

  # Real fed shell_back temperature (0.1C)
  shell_mc=0
  [ -n "$TZ_SHELL_BACK" ] && shell_mc=$(safe_int "$TZ_SHELL_BACK/temp" 0)
  if [ "$shell_mc" -gt 0 ] && [ "$shell_mc" -lt 80000 ]; then
    T_SHELL_TEMP=$((shell_mc / 100))
  else
    T_SHELL_TEMP=$T_BATT_TEMP
  fi

  # Fast-charge protocol & adapter telemetry
  T_VOOC_ING=$(safe_int /sys/class/oplus_chg/battery/voocchg_ing 0)
  T_PPS_ING=$(safe_int /sys/class/oplus_chg/battery/ppschg_ing 0)
  T_PPS_PWR=$(safe_int /sys/class/oplus_chg/battery/ppschg_power 0)
  T_FAST_CHG=$(safe_int /sys/class/oplus_chg/battery/fast_charge 0)
  T_FAST_TYPE=$(safe_int /sys/class/oplus_chg/usb/fast_chg_type 0)
  T_ADAPTER_PWR=$(safe_int /sys/class/oplus_chg/common/adapter_power 0)
  T_CPA_PWR=$(safe_int /sys/class/oplus_chg/common/cpa_power 0)
  T_UI_PWR=$(safe_int /sys/class/oplus_chg/common/ui_power 0)
  T_DEVICE_PWR=$(safe_int /sys/class/oplus_chg/common/device_power 150000)
  T_BCC_CUR=$(safe_int /sys/class/oplus_chg/battery/bcc_current 0)
  T_MMI_EN=$(safe_int /sys/class/oplus_chg/battery/mmi_charging_enable 1)
  T_SOH=$(safe_int /sys/class/oplus_chg/battery/battery_soh 0)
  T_FCC=$(safe_int /sys/class/oplus_chg/battery/battery_fcc 0)
  T_DESIGN=$(safe_int /sys/class/oplus_chg/battery/design_capacity 5200)
  T_CC=$(safe_int /sys/class/oplus_chg/battery/battery_cc 0)

  # Dual-cell 2S pack voltage (RMX3820 has 2S cells: vbat_mv + vbat_min_mv)
  if [ "$T_VBAT_MV" -gt 0 ] && [ "$T_VBAT_MIN_MV" -gt 0 ]; then
    T_VPACK_MV=$((T_VBAT_MV + T_VBAT_MIN_MV))
  else
    T_VPACK_MV=$((T_VBAT_MV * 2))
  fi

  # Battery charging current (Oplus gauge: negative ibat_ma = charging into battery)
  T_CHG_MA=0
  if [ "$T_IBAT_MA" -lt 0 ]; then
    T_CHG_MA=$((-T_IBAT_MA))
  fi

  # Physical power calculation (mW)
  T_PBATT_MW=0
  T_PUSB_MW=0
  T_POWER_MW=0
  if [ "$T_WIRED" -eq 1 ]; then
    [ "$T_CHG_MA" -gt 0 ] && T_PBATT_MW=$(( (T_VPACK_MV * T_CHG_MA) / 1000 ))
    [ "$T_VBUS_MV" -gt 0 ] && [ "$T_IBUS_MA" -gt 0 ] && T_PUSB_MW=$(( (T_VBUS_MV * T_IBUS_MA) / 1000 ))

    if [ "$T_VOOC_ING" -eq 1 ] || [ "$T_PPS_ING" -eq 1 ]; then
      # Direct charge pump: take max(2S battery pack power, VBUS input power)
      if [ "$T_PBATT_MW" -ge "$T_PUSB_MW" ]; then
        T_POWER_MW=$T_PBATT_MW
      else
        T_POWER_MW=$T_PUSB_MW
      fi
    elif [ "$T_PBATT_MW" -gt 0 ]; then
      # Active normal charging: take max(battery charge power, USB input power)
      if [ "$T_PUSB_MW" -gt "$T_PBATT_MW" ]; then
        T_POWER_MW=$T_PUSB_MW
      else
        T_POWER_MW=$T_PBATT_MW
      fi
    else
      # Full or trickle pass-through
      T_POWER_MW=$T_PUSB_MW
    fi
  fi

  # Protocol display label
  T_PROTO="未充电"
  if [ "$T_WIRED" -eq 1 ]; then
    if [ "$T_VOOC_ING" -eq 1 ]; then
      pwr_w=0
      [ "$T_UI_PWR" -gt 0 ] && pwr_w=$((T_UI_PWR >= 1000 ? T_UI_PWR / 1000 : T_UI_PWR))
      [ "$pwr_w" -eq 0 ] && [ "$T_ADAPTER_PWR" -gt 0 ] && pwr_w=$((T_ADAPTER_PWR >= 1000 ? T_ADAPTER_PWR / 1000 : T_ADAPTER_PWR))
      [ "$pwr_w" -eq 0 ] && [ "$T_CPA_PWR" -gt 0 ] && pwr_w=$((T_CPA_PWR >= 1000 ? T_CPA_PWR / 1000 : T_CPA_PWR))
      if [ "$pwr_w" -ge 140 ]; then
        T_PROTO="SuperVOOC 150W"
      elif [ "$pwr_w" -gt 0 ]; then
        T_PROTO="SuperVOOC ${pwr_w}W"
      else
        T_PROTO="SuperVOOC 闪充"
      fi
    elif [ "$T_PPS_ING" -eq 1 ]; then
      if [ "$T_PPS_PWR" -gt 0 ]; then
        T_PROTO="PPS ${T_PPS_PWR}W"
      else
        T_PROTO="PPS 快充"
      fi
    else
      case "$T_USB_TYPE" in
        *PD*|*PPS*) T_PROTO="USB-PD" ;;
        *UFCS*) T_PROTO="UFCS 融合快充" ;;
        *HVDCP*|*QC*) T_PROTO="QC 快充" ;;
        *DCP*) T_PROTO="标准快充 (DCP)" ;;
        *CDP*) T_PROTO="USB 电脑快充 (CDP)" ;;
        *USB*|*SDP*) T_PROTO="USB 5V" ;;
        *) T_PROTO="有线充电" ;;
      esac
    fi
    if [ "$T_STATUS" = "Full" ] && [ "$T_CHG_MA" -eq 0 ]; then
      T_PROTO="${T_PROTO} · 已充满"
    fi
  fi
}

# Sync JSON files into app's private files dir with exact UID & SELinux MLS context
sync_to_app() {
  [ -d "$APP_FILES" ] || return 0
  app_uid=$(stat -c %u "/data/user/0/$APP_PKG" 2>/dev/null)
  [ -n "$app_uid" ] || return 0
  app_ctx=$(stat -c %C "/data/user/0/$APP_PKG" 2>/dev/null)
  [ -n "$app_ctx" ] || app_ctx="u:object_r:app_data_file:s0"

  for pair in "$LIVE_LOCAL:live.json" "$HIST_LOCAL:history.json"; do
    src="${pair%:*}"
    dst="$APP_FILES/${pair#*:}"
    if [ -f "$src" ]; then
      cp -f "$src" "$dst.tmp" 2>/dev/null || continue
      chown "$app_uid:$app_uid" "$dst.tmp" 2>/dev/null
      chmod 0640 "$dst.tmp" 2>/dev/null
      chcon "$app_ctx" "$dst.tmp" 2>/dev/null
      mv -f "$dst.tmp" "$dst" 2>/dev/null
    fi
  done
}

write_live_json() {
  load_config
  read_telemetry
  ic_custom=$(icharger_get_custom_mode)
  ic_smart=$(icharger_get_smart_mode)
  screen_on=$(get_screen_on)

  cat > "$LIVE_LOCAL.tmp" <<EOF
{
  "ts": $T_TS,
  "wired": $T_WIRED,
  "status": "$T_STATUS",
  "protocol": "$T_PROTO",
  "power_mw": $T_POWER_MW,
  "pbatt_mw": $T_PBATT_MW,
  "pusb_mw": $T_PUSB_MW,
  "soc": $T_SOC,
  "batt_temp_d1": $T_BATT_TEMP,
  "shell_temp_d1": $T_SHELL_TEMP,
  "kernel_shell_d1": $T_KERNEL_SHELL,
  "subboard_temp_d1": $T_SUB_TEMP,
  "vbat_mv": $T_VBAT_MV,
  "vpack_mv": $T_VPACK_MV,
  "ibat_ma": $T_IBAT_MA,
  "chg_ma": $T_CHG_MA,
  "vbus_mv": $T_VBUS_MV,
  "ibus_ma": $T_IBUS_MA,
  "vooc_ing": $T_VOOC_ING,
  "pps_ing": $T_PPS_ING,
  "cool_down": $T_COOL_DOWN,
  "bcc_current": $T_BCC_CUR,
  "mmi_en": $T_MMI_EN,
  "soh": $T_SOH,
  "fcc": $T_FCC,
  "design_cap": $T_DESIGN,
  "cycle_count": $T_CC,
  "device_power": $T_DEVICE_PWR,
  "adapter_power": $T_ADAPTER_PWR,
  "charge_mode": "$CHARGE_MODE",
  "sample_interval": $SAMPLE_INTERVAL,
  "icharger_custom_mode": $ic_custom,
  "icharger_smart_mode": $ic_smart,
  "screen_on": $screen_on,
  "led_on": $T_LED_ON
}
EOF
  mv -f "$LIVE_LOCAL.tmp" "$LIVE_LOCAL"
  chmod 0644 "$LIVE_LOCAL"
  sync_to_app
}

# Build history.json from sessions.tsv (last 30 sessions, max 720 pts/session)
rebuild_history_json() {
  if [ ! -s "$TSV_FILE" ]; then
    echo '{"sessions":[]}' > "$HIST_LOCAL"
    chmod 0644 "$HIST_LOCAL"
    sync_to_app
    return 0
  fi

  # Prune TSV if it ever grows past 6000 lines (~100 hours at 1-min interval)
  lines=$(wc -l < "$TSV_FILE" 2>/dev/null)
  if [ "${lines:-0}" -gt 6000 ]; then
    tail -n 4500 "$TSV_FILE" > "$TSV_FILE.tmp" && mv -f "$TSV_FILE.tmp" "$TSV_FILE"
  fi

  awk -F'\t' '
    function esc(s) {
      gsub(/\\/, "\\\\", s)
      gsub(/"/, "\\\"", s)
      return s
    }
    NF >= 11 {
      sid = $1
      ts = $2 + 0
      pmw = $3 + 0
      td1 = $4 + 0
      sd1 = $5 + 0
      soc = $6 + 0
      vp = $7 + 0
      ib = $8 + 0
      vb = $9 + 0
      iu = $10 + 0
      pr = $11
      if (!(sid in seen)) {
        seen[sid] = 1
        order[++n_sess] = sid
        s_start[sid] = ts
        s_start_soc[sid] = soc
        s_peak_mw[sid] = pmw
        s_sum_mw[sid] = 0
        s_max_t[sid] = td1
        s_sum_t[sid] = 0
        s_cnt[sid] = 0
        s_proto[sid] = pr
      }
      c = ++s_cnt[sid]
      if (c <= 720) {
        pt_ts[sid, c] = ts
        pt_mw[sid, c] = pmw
        pt_t[sid, c] = td1
        pt_st[sid, c] = sd1
        pt_soc[sid, c] = soc
        pt_pr[sid, c] = pr
      }
      s_end[sid] = ts
      s_end_soc[sid] = soc
      if (pmw > s_peak_mw[sid]) s_peak_mw[sid] = pmw
      s_sum_mw[sid] += pmw
      if (td1 > s_max_t[sid]) s_max_t[sid] = td1
      s_sum_t[sid] += td1
      # Prefer fast-charge protocol label for session headline if ever triggered
      if (index(pr, "SuperVOOC") > 0 || index(pr, "PPS") > 0 || index(pr, "PD") > 0 || index(pr, "UFCS") > 0) {
        if (index(s_proto[sid], "SuperVOOC") == 0) s_proto[sid] = pr
      }
    }
    END {
      printf "{\"sessions\":["
      start_i = n_sess - 29
      if (start_i < 1) start_i = 1
      first_s = 1
      # Output newest session first
      for (i = n_sess; i >= start_i; i--) {
        sid = order[i]
        cnt = s_cnt[sid]
        if (cnt < 1) continue
        if (!first_s) printf ","
        first_s = 0
        avg_mw = int(s_sum_mw[sid] / cnt)
        avg_t = int(s_sum_t[sid] / cnt)
        dur = s_end[sid] - s_start[sid]
        if (dur < 0) dur = 0
        printf "{\"id\":\"%s\",\"start_ts\":%d,\"end_ts\":%d,\"duration_s\":%d,\"start_soc\":%d,\"end_soc\":%d,\"peak_mw\":%d,\"avg_mw\":%d,\"max_temp_d1\":%d,\"avg_temp_d1\":%d,\"protocol\":\"%s\",\"points\":[",
          esc(sid), s_start[sid], s_end[sid], dur, s_start_soc[sid], s_end_soc[sid],
          s_peak_mw[sid], avg_mw, s_max_t[sid], avg_t, esc(s_proto[sid])
        max_c = (cnt > 720) ? 720 : cnt
        for (j = 1; j <= max_c; j++) {
          if (j > 1) printf ","
          printf "[%d,%d,%d,%d,%d,\"%s\"]",
            pt_ts[sid, j], pt_mw[sid, j], pt_t[sid, j], pt_st[sid, j], pt_soc[sid, j], esc(pt_pr[sid, j])
        }
        printf "]}"
      }
      printf "]}\n"
    }
  ' "$TSV_FILE" > "$HIST_LOCAL.tmp"
  mv -f "$HIST_LOCAL.tmp" "$HIST_LOCAL"
  chmod 0644 "$HIST_LOCAL"
  sync_to_app
}

# Record one sample into the current charging session (or start a new one if wired)
record_sample() {
  force_flag="${1:-0}"
  feed_shell_temp
  read_telemetry

  ACTIVE_SID=""
  LAST_SAMPLE_TS=0
  LAST_PROTO=""
  if [ -f "$META_FILE" ]; then
    # shellcheck disable=SC1090
    . "$META_FILE"
  fi

  if [ "$T_WIRED" -eq 1 ]; then
    if [ -z "$ACTIVE_SID" ]; then
      ACTIVE_SID="chg_${T_TS}"
      LAST_SAMPLE_TS=0
    fi
    load_config
    elapsed=$((T_TS - LAST_SAMPLE_TS))
    if [ "$force_flag" = "1" ] || [ "$LAST_SAMPLE_TS" -eq 0 ] || [ "$elapsed" -ge "$SAMPLE_INTERVAL" ] || [ "$T_PROTO" != "$LAST_PROTO" ]; then
      printf '%s\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%s\t%s\n' \
        "$ACTIVE_SID" "$T_TS" "$T_POWER_MW" "$T_BATT_TEMP" "$T_SHELL_TEMP" "$T_SOC" \
        "$T_VPACK_MV" "$T_IBAT_MA" "$T_VBUS_MV" "$T_IBUS_MA" "$T_PROTO" "$T_STATUS" >> "$TSV_FILE"
      cat > "$META_FILE" <<EOF
ACTIVE_SID=$ACTIVE_SID
LAST_SAMPLE_TS=$T_TS
LAST_PROTO="$T_PROTO"
EOF
      rebuild_history_json
    fi
  else
    # Unplugged: close active session cleanly
    if [ -n "$ACTIVE_SID" ]; then
      rm -f "$META_FILE"
      rebuild_history_json
    elif [ "$force_flag" = "1" ]; then
      # User pressed "立即采样" even when unplugged -> refresh live only
      true
    fi
  fi

  write_live_json
}

clear_history() {
  rm -f "$TSV_FILE" "$META_FILE"
  echo '{"sessions":[]}' > "$HIST_LOCAL"
  chmod 0644 "$HIST_LOCAL"
  write_live_json
}

case "${1:-status}" in
  init)
    load_config
    save_config
    apply_charge_mode
    record_sample 1
    ;;
  apply)
    apply_charge_mode
    write_live_json
    ;;
  set_mode)
    load_config
    case "${2:-}" in
      hyper|balanced|cool)
        CHARGE_MODE="$2"
        save_config
        apply_charge_mode
        write_live_json
        ;;
    esac
    ;;
  set_interval)
    load_config
    case "${2:-}" in
      60|120|300|600)
        SAMPLE_INTERVAL="$2"
        save_config
        write_live_json
        ;;
    esac
    ;;
  sample)
    record_sample 0
    ;;
  sample_now)
    record_sample 1
    ;;
  feed_shell)
    feed_shell_temp
    ;;
  sync_screen)
    sync_screen_status
    ;;
  refresh)
    feed_shell_temp
    write_live_json
    if [ ! -f "$HIST_LOCAL" ]; then
      rebuild_history_json
    else
      sync_to_app
    fi
    ;;
  clear_history)
    clear_history
    ;;
  status)
    write_live_json
    cat "$LIVE_LOCAL"
    ;;
  *)
    echo "Usage: $0 {init|apply|set_mode|set_interval|sample|sample_now|feed_shell|sync_screen|refresh|clear_history|status}"
    exit 1
    ;;
esac
