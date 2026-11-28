#!/system/bin/sh
# Realme GT5 (RMX3820 / Pixelworks X7 Iris 7 + Tianma TM1240) Display & Chip Controller v2.1.0
# Full-stack hardware control:
#   - SurfaceFlinger (1023 ColorMode/RenderIntent, 1022 Saturation, 1015 4x4 Hardware PCC Matrix)
#   - Qualcomm SDM HWCColorModeStc + Pixelworks X7 (Iris 7) /odm/bin/irisConfig
#   - Real silicon telemetry via /sys/kernel/iris/{display_mode,esd}
#   - Chrome 134 Display-P3 wide color gamut flag helper (force-color-profile@2)
#   - Tianma TM1240 panel sysfs (/sys/kernel/oplus_display/*) & Android 16 HDR/HBM

IRIS="/odm/bin/irisConfig"
SYS_DISP="/sys/kernel/oplus_display"
SYS_IRIS="/sys/kernel/iris"
CHROME_LS="/data/data/com.android.chrome/app_chrome/Local State"
STATE_DIR="/data/adb/gt5_display"
STATE_FILE="$STATE_DIR/state.env"
AUTO_STATE_FILE="/dev/.gt5_display_auto_scene"
LOCK_DIR="/dev/.gt5_display.lock"

mkdir -p "$STATE_DIR" 2>/dev/null

# ---------- Lock helpers (prevent concurrent WebUI slider / daemon races) ----------
acquire_lock() {
  local tries=0
  while ! mkdir "$LOCK_DIR" 2>/dev/null; do
    tries=$((tries + 1))
    if [ "$tries" -ge 40 ]; then
      rmdir "$LOCK_DIR" 2>/dev/null || rm -rf "$LOCK_DIR" 2>/dev/null
      mkdir "$LOCK_DIR" 2>/dev/null && break
      break
    fi
    sleep 0.05
  done
}

release_lock() {
  rmdir "$LOCK_DIR" 2>/dev/null || true
}

# ---------- Default persistent state ----------
init_defaults() {
  CHIP_MODE="auto"          # auto | pt | bypass
  GAMUT="p3_vivid"          # native | p3_vivid | p3_nature | p3_pro | srgb_pro | srgb_nature | bt2020
  COLOR_TEMP=6500           # 2800..10000
  SDR2HDR_ID=0              # 0,1,2,3,4,6,10..24,27..38
  DIRECT_HDR=0              # 0,5,9,11,12,13,14,61,62
  MEMC_MODE="off"           # off | global_video | global_game | video_dual | video_single | video_netflix | game | game_emv | tnr
  MEMC_GAME_ID=3            # factory game id (3=原神, 0=和平精英, 10=王者, 16=LOL, 4=崩坏3, 155=星穹, 153=逆水寒, 255=通用)
  MEMC_LATENCY=50           # 50=ultra-low(0x32), 34=low(0x22), 18=normal(0x12), 51=eMV1(0x33)
  MEMC_FPS=30               # 0=Auto, 30, 45, 60
  MEMC_DETECT=0             # 0 | 1
  SR_MODE=0                 # 0=Off, 1=LPSR, 2=HESR
  SR_GAME_ID=255            # 255=Default, 3=原神, 0=和平精英, 10=王者, 16=LOL, 13=CF, 9=QQ飞车, 11=光遇, 2=天刀
  PWM_ONEPULSE=0            # 0 | 1
  PANEL_HBM=0               # 0 | 1
  LCM_CABC=1                # 0 | 1
  PANEL_DITHER=1            # 0 | 1
  PANEL_SEED=0              # 0..3
  SYS_HDR_ENABLED=1         # 0 | 1 (Android 16 HdrBrightnessModifier setting)
  SYS_HDR_BOOST=100         # 10..100 (% -> 0.1..1.0)
  CHROME_P3=1               # 0 | 1 (Chrome 134 Display-P3 wide color unlock)
  BOOT_RESTORE=1            # 0 | 1
  SCREEN_RESTORE=1          # 0 | 1
  AUTO_SCENE=0              # 0 | 1 (Factory multimedia_pixelworks_* app auto-scene engine)
  AUTO_VIDEO_MEMC=1         # 0 | 1
  AUTO_VIDEO_HDR=1          # 0 | 1
  AUTO_GAME_MEMC=1          # 0 | 1
  AUTO_GAME_SR=1            # 0 | 1
  AUTO_GAME_HDR=0           # 0 | 1
}

load_state() {
  init_defaults
  [ -f "$STATE_FILE" ] && . "$STATE_FILE"
  clamp_state
}

clamp_int() {
  local v="$1" lo="$2" hi="$3" def="$4"
  case "$v" in
    ''|*[!0-9]*) echo "$def"; return ;;
  esac
  [ "$v" -lt "$lo" ] && v="$lo"
  [ "$v" -gt "$hi" ] && v="$hi"
  echo "$v"
}

clamp_state() {
  case "$CHIP_MODE" in auto|pt|bypass) ;; *) CHIP_MODE="auto" ;; esac
  case "$GAMUT" in native|p3_vivid|p3_nature|p3_pro|srgb_pro|srgb_nature|bt2020) ;; *) GAMUT="p3_vivid" ;; esac
  COLOR_TEMP=$(clamp_int "$COLOR_TEMP" 2800 10000 6500)
  SDR2HDR_ID=$(clamp_int "$SDR2HDR_ID" 0 38 0)
  case "$DIRECT_HDR" in 0|3|4|5|6|7|8|9|10|11|12|13|14|61|62) ;; *) DIRECT_HDR=0 ;; esac
  case "$MEMC_MODE" in off|global_video|global_game|video_single|video_dual|video_netflix|game|game_emv|tnr) ;; *) MEMC_MODE="off" ;; esac
  MEMC_GAME_ID=$(clamp_int "$MEMC_GAME_ID" 0 255 3)
  case "$MEMC_LATENCY" in 18|34|50|51) ;; *) MEMC_LATENCY=50 ;; esac
  case "$MEMC_FPS" in 0|30|45|60) ;; *) MEMC_FPS=30 ;; esac
  MEMC_DETECT=$(clamp_int "$MEMC_DETECT" 0 1 0)
  SR_MODE=$(clamp_int "$SR_MODE" 0 2 0)
  SR_GAME_ID=$(clamp_int "$SR_GAME_ID" 0 255 255)
  PWM_ONEPULSE=$(clamp_int "$PWM_ONEPULSE" 0 1 0)
  PANEL_HBM=$(clamp_int "$PANEL_HBM" 0 1 0)
  LCM_CABC=$(clamp_int "$LCM_CABC" 0 1 1)
  PANEL_DITHER=$(clamp_int "$PANEL_DITHER" 0 1 1)
  PANEL_SEED=$(clamp_int "$PANEL_SEED" 0 3 0)
  SYS_HDR_ENABLED=$(clamp_int "$SYS_HDR_ENABLED" 0 1 1)
  SYS_HDR_BOOST=$(clamp_int "$SYS_HDR_BOOST" 10 100 100)
  CHROME_P3=$(clamp_int "$CHROME_P3" 0 1 1)
  BOOT_RESTORE=$(clamp_int "$BOOT_RESTORE" 0 1 1)
  SCREEN_RESTORE=$(clamp_int "$SCREEN_RESTORE" 0 1 1)
  AUTO_SCENE=$(clamp_int "$AUTO_SCENE" 0 1 0)
  AUTO_VIDEO_MEMC=$(clamp_int "$AUTO_VIDEO_MEMC" 0 1 1)
  AUTO_VIDEO_HDR=$(clamp_int "$AUTO_VIDEO_HDR" 0 1 1)
  AUTO_GAME_MEMC=$(clamp_int "$AUTO_GAME_MEMC" 0 1 1)
  AUTO_GAME_SR=$(clamp_int "$AUTO_GAME_SR" 0 1 1)
  AUTO_GAME_HDR=$(clamp_int "$AUTO_GAME_HDR" 0 1 0)
}

save_state() {
  cat > "$STATE_FILE.tmp" <<EOF
CHIP_MODE="$CHIP_MODE"
GAMUT="$GAMUT"
COLOR_TEMP=$COLOR_TEMP
SDR2HDR_ID=$SDR2HDR_ID
DIRECT_HDR=$DIRECT_HDR
MEMC_MODE="$MEMC_MODE"
MEMC_GAME_ID=$MEMC_GAME_ID
MEMC_LATENCY=$MEMC_LATENCY
MEMC_FPS=$MEMC_FPS
MEMC_DETECT=$MEMC_DETECT
SR_MODE=$SR_MODE
SR_GAME_ID=$SR_GAME_ID
PWM_ONEPULSE=$PWM_ONEPULSE
PANEL_HBM=$PANEL_HBM
LCM_CABC=$LCM_CABC
PANEL_DITHER=$PANEL_DITHER
PANEL_SEED=$PANEL_SEED
SYS_HDR_ENABLED=$SYS_HDR_ENABLED
SYS_HDR_BOOST=$SYS_HDR_BOOST
CHROME_P3=$CHROME_P3
BOOT_RESTORE=$BOOT_RESTORE
SCREEN_RESTORE=$SCREEN_RESTORE
AUTO_SCENE=$AUTO_SCENE
AUTO_VIDEO_MEMC=$AUTO_VIDEO_MEMC
AUTO_VIDEO_HDR=$AUTO_VIDEO_HDR
AUTO_GAME_MEMC=$AUTO_GAME_MEMC
AUTO_GAME_SR=$AUTO_GAME_SR
AUTO_GAME_HDR=$AUTO_GAME_HDR
EOF
  mv -f "$STATE_FILE.tmp" "$STATE_FILE"
}

# ---------- Low-level hardware helpers ----------
iris_run() {
  [ -x "$IRIS" ] || return 1
  "$IRIS" "$@" >/dev/null 2>&1
}

iris_get1() {
  [ -x "$IRIS" ] || { echo "-1"; return; }
  "$IRIS" -get "$1" 1 0 2>/dev/null | awk '/^get / { print $2; exit }'
}

sys_write() {
  local node="$SYS_DISP/$1" val="$2"
  [ -w "$node" ] && printf '%s\n' "$val" > "$node" 2>/dev/null || true
}

sys_read() {
  local node="$SYS_DISP/$1"
  [ -r "$node" ] && tr -d ' \r\n' < "$node" 2>/dev/null || echo "-1"
}

# ---------- Real SurfaceFlinger + SDM HWCColorModeStc Gamut Control ----------
# SurfaceFlinger transact 1023 (displayColor, compositionColorSpace) + 1022 (saturation)
# Proven live to switch SF ColorMode & SDM gamut (12=Display-P3, 255=Native, 1=sRGB).
apply_sf_gamut() {
  local dc=2 cs=9 sat="1.12"
  case "$GAMUT" in
    p3_vivid)    dc=2;   cs=9; sat="1.12" ;; # DISPLAY_P3 Enhanced + vivid saturation
    p3_nature)   dc=0;   cs=9; sat="1.0"  ;; # DISPLAY_P3 Managed natural
    p3_pro)      dc=256; cs=9; sat="1.0"  ;; # DISPLAY_P3 Pro D65 (renderIntent 256)
    native)      dc=1;   cs=0; sat="1.0"  ;; # ColorMode::NATIVE Unmanaged (full raw OLED gamut 255)
    srgb_pro)    dc=301; cs=7; sat="1.0"  ;; # ColorMode::SRGB AdaptSRGB (SoftIris=4)
    srgb_nature) dc=303; cs=7; sat="0.94" ;; # ColorMode::SRGB WeakEnhanceSRGB (SoftIris=25)
    bt2020)      dc=1;   cs=0; sat="1.0"  ;; # Raw native pass-through for Iris 7 BT.2020 LUT
  esac
  setprop persist.sys.sf.native_mode "$dc" >/dev/null 2>&1 || true
  setprop persist.sys.sf.color_mode "$cs" >/dev/null 2>&1 || true
  service call SurfaceFlinger 1023 i32 "$dc" i32 "$cs" >/dev/null 2>&1 || true
  service call SurfaceFlinger 1022 f "$sat" >/dev/null 2>&1 || true
}

apply_iris_gamut() {
  case "$GAMUT" in
    native)      iris_run -colormode 0 0 ;;
    p3_vivid)    iris_run -colormode 9 308 ;;
    p3_nature)   iris_run -colormode 9 304 ;;
    p3_pro)      iris_run -colormode 9 302 ;;
    srgb_pro)    iris_run -colormode 7 301 ;;
    srgb_nature) iris_run -colormode 7 303 ;;
    bt2020)      iris_run 40 1 6 ;;
  esac
}

# ---------- Real Hardware Color Temperature (SurfaceFlinger 1015 PCC + Iris 35/48) ----------
# Uses normalized Planckian/Tanner RGB gains so 6500K cleanly disables matrix (0 overhead),
# while warm (<6500K) and cool (>6500K) apply instant, unmistakably visible DPU PCC transforms
# that multiply cleanly with SurfaceFlinger 1022 saturation in both Bypass and PT modes.
apply_sf_color_temp() {
  local k="$1"
  if [ "$k" -eq 6500 ] 2>/dev/null; then
    service call SurfaceFlinger 1015 i32 0 >/dev/null 2>&1 || true
    return
  fi
  local gains r g b
  gains=$(awk -v K="$k" 'BEGIN {
    t = K / 100.0;
    if (t <= 66.0) {
      r = 255.0;
      g = 99.4708025861 * log(t) - 161.1195681661;
      if (t <= 19.0) b = 0.0;
      else b = 138.5177312231 * log(t - 10.0) - 305.0447927307;
    } else {
      r = 329.698727446 * exp(-0.1332047592 * log(t - 60.0));
      g = 288.1221695283 * exp(-0.0755148492 * log(t - 60.0));
      b = 255.0;
    }
    if (r < 0) r = 0; if (r > 255) r = 255;
    if (g < 0) g = 0; if (g > 255) g = 255;
    if (b < 0) b = 0; if (b > 255) b = 255;
    # Normalize relative to 6500K reference (255.0, 254.132, 250.062)
    rn = r / 255.0;
    gn = g / 254.132;
    bn = b / 250.062;
    mx = rn; if (gn > mx) mx = gn; if (bn > mx) mx = bn;
    if (mx <= 0) mx = 1.0;
    rn /= mx; gn /= mx; bn /= mx;
    if (rn < 0.35) rn = 0.35;
    if (gn < 0.35) gn = 0.35;
    if (bn < 0.35) bn = 0.35;
    printf "%.4f %.4f %.4f\n", rn, gn, bn;
  }')
  set -- $gains
  r="${1:-1.0000}"; g="${2:-1.0000}"; b="${3:-1.0000}"
  service call SurfaceFlinger 1015 i32 1 \
    f "$r" f 0.0 f 0.0 f 0.0 \
    f 0.0  f "$g" f 0.0 f 0.0 \
    f 0.0  f 0.0 f "$b" f 0.0 \
    f 0.0  f 0.0 f 0.0 f 1.0 >/dev/null 2>&1 || true
}

apply_iris_color_temp() {
  iris_run 48 1 "$COLOR_TEMP"
  iris_run 35 1 "$COLOR_TEMP"
}

# ---------- Chrome 134 Display-P3 Wide Color Gamut Helper ----------
# Chrome 134 hardcodes AlwaysUseWideColorGamut() to Pixel 4/4 XL only and marks
# DynamicColorGamut expired (M90). Setting force-color-profile@2 (display-p3-d65,
# expiry_milestone=-1) unlocks true Display-P3 in Chrome & WebKit gamut tests.
chrome_p3_is_enabled() {
  [ -r "$CHROME_LS" ] || { echo 0; return; }
  if grep -q '"force-color-profile@2"' "$CHROME_LS" 2>/dev/null; then
    echo 1
  else
    echo 0
  fi
}

patch_chrome_local_state() {
  local want="${1:-1}" restart="${2:-0}"
  [ -w "$CHROME_LS" ] || return 0
  if [ "$restart" = "1" ]; then
    am force-stop com.android.chrome >/dev/null 2>&1 || true
    sleep 0.3
  else
    # Never mutate Local State while Chrome is actively running unless restart=1
    if pidof com.android.chrome >/dev/null 2>&1; then
      return 0
    fi
  fi

  local cur
  cur=$(chrome_p3_is_enabled)
  [ "$cur" = "$want" ] && return 0

  local tmp="/dev/.gt5_chrome_ls.tmp"
  if [ "$want" = "1" ]; then
    awk '
      {
        s = $0
        if (s ~ /"force-color-profile@[0-9]+"/) {
          sub(/"force-color-profile@[0-9]+"/, "\"force-color-profile@2\"", s)
        } else if (s ~ /"enabled_labs_experiments":\[\]/) {
          sub(/"enabled_labs_experiments":\[\]/, "\"enabled_labs_experiments\":[\"force-color-profile@2\"]", s)
        } else if (s ~ /"enabled_labs_experiments":\[/) {
          sub(/"enabled_labs_experiments":\[/, "\"enabled_labs_experiments\":[\"force-color-profile@2\",", s)
        } else if (s ~ /"browser":\{/) {
          sub(/"browser":\{/, "\"browser\":{\"enabled_labs_experiments\":[\"force-color-profile@2\"],", s)
        } else if (substr(s, 1, 1) == "{") {
          s = "{\"browser\":{\"enabled_labs_experiments\":[\"force-color-profile@2\"]}," substr(s, 2)
        }
        printf "%s", s
      }
    ' "$CHROME_LS" > "$tmp" 2>/dev/null
  else
    awk '
      {
        s = $0
        gsub(/,"force-color-profile@2"/, "", s)
        gsub(/"force-color-profile@2",/, "", s)
        gsub(/"force-color-profile@2"/, "", s)
        printf "%s", s
      }
    ' "$CHROME_LS" > "$tmp" 2>/dev/null
  fi

  # Validate JSON boundary before overwriting in-place (preserves uid/gid/perms/SELinux context)
  if [ -s "$tmp" ] && head -c 1 "$tmp" | grep -q '{' && tail -c 2 "$tmp" | grep -q '}'; then
    cat "$tmp" > "$CHROME_LS" 2>/dev/null || true
  fi
  rm -f "$tmp" 2>/dev/null || true
}

apply_sys_hdr() {
  # Android 16 HdrBrightnessModifier SettingsObserver keys
  local boost_float
  boost_float=$(awk "BEGIN { printf \"%.2f\", $SYS_HDR_BOOST / 100.0 }")
  settings put secure hdr_brightness_enabled "$SYS_HDR_ENABLED" >/dev/null 2>&1 || true
  settings put secure hdr_brightness_boost_level "$boost_float" >/dev/null 2>&1 || true
}

apply_panel_hw() {
  sys_write pwm_onepulse "$PWM_ONEPULSE"
  sys_write LCM_CABC "$LCM_CABC"
  sys_write dither "$PANEL_DITHER"
  # Kernel forbids writing seed while HBM is active: set seed before enabling HBM
  if [ "$PANEL_HBM" = "0" ]; then
    sys_write hbm 0
    sys_write seed "$PANEL_SEED"
  else
    sys_write seed "$PANEL_SEED"
    sys_write hbm 1
  fi
}

is_bypass_sdr2hdr() {
  case "$1" in
    0|4|5|7) return 0 ;;
    *) return 1 ;;
  esac
}

# Core applier for a given Iris7 + SurfaceFlinger pipeline configuration
# Args: chip_mode sdr2hdr_id direct_hdr memc_mode memc_game_id memc_latency memc_fps memc_detect sr_mode sr_game_id
apply_iris_pipeline() {
  local cm="$1" s2h="$2" dhdr="$3" mm="$4" mgid="$5" mlat="$6" mfps="$7" mdet="$8" srm="$9"
  shift 9
  local srgid="$1"

  local need_pt=0
  if [ "$cm" = "pt" ]; then
    need_pt=1
  elif [ "$cm" = "bypass" ]; then
    need_pt=0
  else
    if [ "$mm" != "off" ] || [ "$srm" != "0" ] || [ "$dhdr" != "0" ] || [ "$GAMUT" = "bt2020" ]; then
      need_pt=1
    elif ! is_bypass_sdr2hdr "$s2h"; then
      need_pt=1
    fi
  fi

  # Always apply real SurfaceFlinger + SDM HWCColorModeStc color gamut first
  apply_sf_gamut

  local cur_bypass
  cur_bypass=$(iris_get1 56)

  if [ "$need_pt" = "1" ]; then
    # 1. Wake Pixelworks X7 into PT Active mode first
    if [ "$cur_bypass" != "0" ]; then
      iris_run 56 1 0
    fi

    # 2. Apply Video/Game SDR2HDR / EDR / Filter (Type 267)
    # (Powers up Iris HDR block + loads SDR2HDR_LUT + AI TM + AI LCE)
    iris_run 267 2 3 "$s2h"

    # 3. Apply Direct HDR pipeline (Type 47) only when explicitly selected
    if [ "$dhdr" != "0" ]; then
      iris_run 47 1 "$dhdr"
    elif [ "$s2h" = "0" ]; then
      iris_run 47 1 0
    fi

    # 4. Only apply Iris Gamut when SDR2HDR & DirectHDR are OFF so we NEVER clobber SDR2HDR_LUT & ColorGains!
    if [ "$s2h" = "0" ] && [ "$dhdr" = "0" ]; then
      apply_iris_gamut
    fi

    # 5. Apply Super Resolution (Type 273) -> engages SINGLE-PT-SR (frc:1)
    if [ "$srm" = "0" ]; then
      iris_run 273 1 0
    else
      iris_run 273 3 1 "$srgid" "$srm"
    fi

    # 6. Apply MEMC Scenario Detection (Type 13) & MEMC (Type 258)
    # global_video (scene=1) & global_game (scene=0x31=49) engage real hardware SINGLE-MEMC
    # (bsram:1, frc:1, memc_mode:1) on ANY moving content even at 144Hz!
    iris_run 13 1 "$mdet"
    case "$mm" in
      off)           iris_run 258 1 0 ;;
      global_video)  iris_run 258 7 10 -1 1 -1 0 "$mfps" 0 ;;
      global_game)   iris_run 258 7 10 -1 49 -1 3 "$mfps" 0 ;;
      video_single)  iris_run 258 3 10 0 0 ;;
      video_dual)    iris_run 258 3 40 0 0 ;;
      video_netflix) iris_run 258 3 74 0 0 ;;
      game)          iris_run 258 6 10 99 "$mlat" 99 "$mgid" "$mfps" ;;
      game_emv)      iris_run 258 3 40 255 6 ;;
      tnr)           iris_run 258 1 14 ;;
    esac

    # 7. Hardware Color Temp via SF 1015 PCC matrix (never clobbers Iris SDR2HDR_LUT);
    # also send Iris 35/48 only when SDR2HDR is off so preset LUTs/kelvins stay intact.
    if [ "$s2h" = "6" ] || [ "$s2h" = "12" ]; then
      service call SurfaceFlinger 1015 i32 0 >/dev/null 2>&1 || true
    else
      apply_sf_color_temp "$COLOR_TEMP"
      if [ "$s2h" = "0" ] && [ "$dhdr" = "0" ]; then
        apply_iris_color_temp
      fi
    fi
  else
    # 1. Cleanly disable all PT-only engines BEFORE returning to Bypass
    iris_run 258 1 0
    iris_run 273 1 0
    iris_run 47 1 0
    iris_run 13 1 0
    if ! is_bypass_sdr2hdr "$s2h"; then
      iris_run 267 2 3 0
    fi

    # 2. Enter ABP Analog Bypass for 0 extra chip power
    if [ "$cur_bypass" != "1" ]; then
      sleep 0.15
      iris_run 56 1 1
      if [ "$(iris_get1 56)" != "1" ]; then
        sleep 0.2
        iris_run 56 1 1
      fi
    fi

    # 3. SoftIris Gamut in Bypass first, then optional Bypass SDR2HDR
    apply_iris_gamut
    if is_bypass_sdr2hdr "$s2h"; then
      iris_run 267 2 3 "$s2h"
    fi

    # 4. Real hardware Color Temp via SurfaceFlinger 1015 PCC + Iris 35/48
    apply_sf_color_temp "$COLOR_TEMP"
    apply_iris_color_temp
  fi
}

apply_all() {
  apply_sys_hdr
  apply_panel_hw
  apply_iris_pipeline "$CHIP_MODE" "$SDR2HDR_ID" "$DIRECT_HDR" "$MEMC_MODE" \
    "$MEMC_GAME_ID" "$MEMC_LATENCY" "$MEMC_FPS" "$MEMC_DETECT" "$SR_MODE" "$SR_GAME_ID"
}

# Check if user has manually engaged any Iris7 HW enhancement (so Auto-Scene yields cleanly)
has_manual_override() {
  [ "$CHIP_MODE" != "auto" ] && return 0
  [ "$MEMC_MODE" != "off" ] && return 0
  [ "$SR_MODE" != "0" ] && return 0
  [ "$SDR2HDR_ID" != "0" ] && return 0
  [ "$DIRECT_HDR" != "0" ] && return 0
  return 1
}

# ---------- Live JSON status output (with REAL silicon & SF telemetry) ----------
print_status() {
  local hw_bypass hw_gamut hw_temp hw_memc hw_s2h hw_sr hw_hdr hw_feat
  local hw_hbm hw_pwm hw_cabc hw_dither hw_seed hw_bl hw_bl_max
  local sys_hdr_ready sys_hbm_ready auto_pkg
  local silicon_mode esd_raw hw_frc hw_bsram hw_memc_active hw_dpg
  local sf_info sf_cm sf_setting chrome_p3_now

  hw_bypass=$(iris_get1 56)
  hw_gamut=$(iris_get1 40)
  hw_temp=$(iris_get1 35)
  case "$hw_temp" in ''|0|-*) hw_temp=$(iris_get1 48) ;; esac
  hw_memc=$(iris_get1 258)
  hw_s2h=$(iris_get1 267)
  hw_sr=$(iris_get1 273)
  hw_hdr=$(iris_get1 47)
  hw_feat=$(getprop persist.vendor.display.pxlw.iris_feature 2>/dev/null)
  [ -z "$hw_feat" ] && hw_feat="0x41ff0780"

  # Direct kernel silicon telemetry from /sys/kernel/iris/
  silicon_mode=$(tr -d ' \r\n"' < "$SYS_IRIS/display_mode" 2>/dev/null || echo "UNKNOWN")
  [ -z "$silicon_mode" ] && silicon_mode="UNKNOWN"
  esd_raw=$(awk '
    /Power -/ {
      for (i=1; i<=NF; i++) {
        if ($i ~ /^dpg:/) { sub(/^dpg:/,"",$i); gsub(/,/,"",$i); dpg=$i }
        if ($i ~ /^bsram:/) { sub(/^bsram:/,"",$i); gsub(/,/,"",$i); bsram=$i }
        if ($i ~ /^frc:/) { sub(/^frc:/,"",$i); gsub(/,/,"",$i); frc=$i }
      }
    }
    /Status -/ {
      for (i=1; i<=NF; i++) {
        if ($i ~ /^memc_mode:/) { sub(/^memc_mode:/,"",$i); gsub(/,/,"",$i); mm=$i }
      }
    }
    END { printf "%d %d %d %d\n", dpg+0, bsram+0, frc+0, mm+0 }
  ' "$SYS_IRIS/esd" 2>/dev/null)
  set -- $esd_raw
  hw_dpg="${1:-0}"; hw_bsram="${2:-0}"; hw_frc="${3:-0}"; hw_memc_active="${4:-0}"

  # Live SurfaceFlinger ColorMode & DisplayColorSetting (~70ms)
  sf_info=$(dumpsys SurfaceFlinger 2>/dev/null | awk '
    /DisplayColorSetting:/ { setting=$2 }
    /Current color mode:/ { mode=$4; sub(/^ColorMode::/, "", mode); exit }
    END { printf "%s %s\n", (mode==""?"UNKNOWN":mode), (setting==""?"UNKNOWN":setting) }
  ')
  set -- $sf_info
  sf_cm="${1:-UNKNOWN}"; sf_setting="${2:-UNKNOWN}"

  chrome_p3_now=$(chrome_p3_is_enabled)

  hw_hbm=$(sys_read hbm)
  hw_pwm=$(sys_read pwm_onepulse)
  hw_cabc=$(sys_read LCM_CABC)
  hw_dither=$(sys_read dither)
  hw_seed=$(sys_read seed)
  hw_bl=$(tr -d ' \r\n' < /sys/class/backlight/panel0-backlight/brightness 2>/dev/null || echo 0)
  hw_bl_max=$(tr -d ' \r\n' < /sys/class/backlight/panel0-backlight/max_brightness 2>/dev/null || echo 4095)

  # Cache boot-immutable DisplayDeviceConfig HDR/HBM capabilities for instant WebUI response
  local caps_file="/dev/.gt5_display_sys_caps"
  if [ -r "$caps_file" ]; then
    . "$caps_file"
  else
    sys_hdr_ready=0
    sys_hbm_ready=0
    local ddump
    ddump=$(dumpsys display 2>/dev/null)
    case "$ddump" in
      *"mHdrBrightnessData=HdrBrightnessData"*) sys_hdr_ready=1 ;;
    esac
    case "$ddump" in
      *"mHbmData=HBM{"*) sys_hbm_ready=1 ;;
    esac
    if [ "$sys_hdr_ready" = "1" ] && [ "$sys_hbm_ready" = "1" ]; then
      printf 'sys_hdr_ready=%s\nsys_hbm_ready=%s\n' "$sys_hdr_ready" "$sys_hbm_ready" > "$caps_file" 2>/dev/null || true
    fi
  fi

  auto_pkg=""
  [ -f "$AUTO_STATE_FILE" ] && auto_pkg=$(tr -d '\r\n"' < "$AUTO_STATE_FILE" 2>/dev/null)

  cat <<EOF
{"chip_mode":"$CHIP_MODE","gamut":"$GAMUT","color_temp":$COLOR_TEMP,"sdr2hdr_id":$SDR2HDR_ID,"direct_hdr":$DIRECT_HDR,"memc_mode":"$MEMC_MODE","memc_game_id":$MEMC_GAME_ID,"memc_latency":$MEMC_LATENCY,"memc_fps":$MEMC_FPS,"memc_detect":$MEMC_DETECT,"sr_mode":$SR_MODE,"sr_game_id":$SR_GAME_ID,"pwm_onepulse":$PWM_ONEPULSE,"panel_hbm":$PANEL_HBM,"lcm_cabc":$LCM_CABC,"panel_dither":$PANEL_DITHER,"panel_seed":$PANEL_SEED,"sys_hdr_enabled":$SYS_HDR_ENABLED,"sys_hdr_boost":$SYS_HDR_BOOST,"chrome_p3":$CHROME_P3,"boot_restore":$BOOT_RESTORE,"screen_restore":$SCREEN_RESTORE,"auto_scene":$AUTO_SCENE,"auto_video_memc":$AUTO_VIDEO_MEMC,"auto_video_hdr":$AUTO_VIDEO_HDR,"auto_game_memc":$AUTO_GAME_MEMC,"auto_game_sr":$AUTO_GAME_SR,"auto_game_hdr":$AUTO_GAME_HDR,"hw":{"bypass":${hw_bypass:--1},"silicon_mode":"$silicon_mode","dpg":$hw_dpg,"bsram":$hw_bsram,"frc":$hw_frc,"memc_active":$hw_memc_active,"sf_color_mode":"$sf_cm","sf_setting":"$sf_setting","chrome_p3_now":$chrome_p3_now,"gamut":${hw_gamut:--1},"color_temp":${hw_temp:--1},"memc":${hw_memc:--1},"sdr2hdr":${hw_s2h:--1},"sr":${hw_sr:--1},"direct_hdr":${hw_hdr:--1},"feature":"$hw_feat","hbm":${hw_hbm:--1},"pwm_onepulse":${hw_pwm:--1},"lcm_cabc":${hw_cabc:--1},"dither":${hw_dither:--1},"seed":${hw_seed:--1},"backlight":${hw_bl:-0},"backlight_max":${hw_bl_max:-4095},"sys_hdr_ready":$sys_hdr_ready,"sys_hbm_ready":$sys_hbm_ready,"auto_active":"$auto_pkg"}}
EOF
}

# ---------- CLI Dispatch ----------
CMD="${1:-status}"
shift 2>/dev/null || true

case "$CMD" in
  status)
    load_state
    print_status
    ;;

  set)
    acquire_lock
    load_state
    for kv in "$@"; do
      k="${kv%%=*}"
      v="${kv#*=}"
      case "$k" in
        CHIP_MODE|GAMUT|COLOR_TEMP|SDR2HDR_ID|DIRECT_HDR|MEMC_MODE|MEMC_GAME_ID|MEMC_LATENCY|MEMC_FPS|MEMC_DETECT|SR_MODE|SR_GAME_ID|PWM_ONEPULSE|PANEL_HBM|LCM_CABC|PANEL_DITHER|PANEL_SEED|SYS_HDR_ENABLED|SYS_HDR_BOOST|CHROME_P3|BOOT_RESTORE|SCREEN_RESTORE|AUTO_SCENE|AUTO_VIDEO_MEMC|AUTO_VIDEO_HDR|AUTO_GAME_MEMC|AUTO_GAME_SR|AUTO_GAME_HDR)
          eval "$k=\"\$v\""
          ;;
      esac
    done
    clamp_state
    save_state
    rm -f "$AUTO_STATE_FILE" 2>/dev/null
    apply_all
    release_lock
    print_status
    ;;

  chrome_p3_apply)
    # Explicitly toggle Chrome 134 Display-P3 flag and restart Chrome so it takes effect immediately
    acquire_lock
    load_state
    CHROME_P3=$(clamp_int "${1:-1}" 0 1 1)
    save_state
    patch_chrome_local_state "$CHROME_P3" 1
    release_lock
    print_status
    ;;

  preset)
    acquire_lock
    load_state
    case "$1" in
      balanced)
        CHIP_MODE="auto"; GAMUT="p3_vivid"; COLOR_TEMP=6500
        SDR2HDR_ID=0; DIRECT_HDR=0; MEMC_MODE="off"; MEMC_DETECT=0; SR_MODE=0; PANEL_HBM=0
        ;;
      cinema)
        CHIP_MODE="auto"; GAMUT="p3_pro"; COLOR_TEMP=6500
        SDR2HDR_ID=6; DIRECT_HDR=0; MEMC_MODE="global_video"; MEMC_FPS=30; MEMC_DETECT=1; SR_MODE=0
        ;;
      video_hdr)
        CHIP_MODE="auto"; GAMUT="p3_vivid"; COLOR_TEMP=6500
        SDR2HDR_ID=1; DIRECT_HDR=0; MEMC_MODE="global_video"; MEMC_FPS=30; MEMC_DETECT=1; SR_MODE=0
        ;;
      esports)
        CHIP_MODE="auto"; GAMUT="p3_vivid"; COLOR_TEMP=6800
        SDR2HDR_ID=3; DIRECT_HDR=0; MEMC_MODE="global_game"; MEMC_LATENCY=50; MEMC_FPS=45; MEMC_DETECT=1; SR_MODE=2
        ;;
      srgb_pro)
        CHIP_MODE="auto"; GAMUT="srgb_pro"; COLOR_TEMP=6500
        SDR2HDR_ID=0; DIRECT_HDR=0; MEMC_MODE="off"; MEMC_DETECT=0; SR_MODE=0
        ;;
      powersave)
        CHIP_MODE="auto"; SDR2HDR_ID=0; DIRECT_HDR=0; MEMC_MODE="off"; MEMC_DETECT=0
        SR_MODE=0; PANEL_HBM=0; LCM_CABC=1
        ;;
    esac
    clamp_state
    save_state
    rm -f "$AUTO_STATE_FILE" 2>/dev/null
    apply_all
    release_lock
    print_status
    ;;

  apply)
    acquire_lock
    load_state
    apply_all
    release_lock
    ;;

  boot_apply)
    acquire_lock
    load_state
    if [ "$BOOT_RESTORE" = "1" ]; then
      apply_all
    fi
    # Safe on boot when Chrome is not yet running: unlock Chrome 134 Display-P3
    patch_chrome_local_state "$CHROME_P3" 0
    release_lock
    ;;

  screen_restore)
    acquire_lock
    load_state
    if [ "$SCREEN_RESTORE" = "1" ]; then
      # Re-apply SurfaceFlinger gamut, hardware color temp, and DC dimming cleanly on screen wake
      apply_sf_gamut
      if [ "$SDR2HDR_ID" = "0" ] && [ "$DIRECT_HDR" = "0" ]; then
        apply_iris_gamut
        apply_iris_color_temp
      fi
      if [ "$SDR2HDR_ID" = "6" ] || [ "$SDR2HDR_ID" = "12" ]; then
        service call SurfaceFlinger 1015 i32 0 >/dev/null 2>&1 || true
      else
        apply_sf_color_temp "$COLOR_TEMP"
      fi
      sys_write pwm_onepulse "$PWM_ONEPULSE"
    fi
    release_lock
    ;;

  scene_video)
    # Usage: scene_video <pkg> <memc_type:10|40|74>
    acquire_lock
    load_state
    if [ "$AUTO_SCENE" = "1" ] && ! has_manual_override; then
      local_pkg="$1"
      local_mt="${2:-40}"
      v_memc="off"
      v_det=0
      v_s2h=0
      if [ "$AUTO_VIDEO_MEMC" = "1" ]; then
        case "$local_mt" in
          74) v_memc="video_netflix" ;;
          *)  v_memc="global_video" ;;
        esac
        v_det=1
      fi
      if [ "$AUTO_VIDEO_HDR" = "1" ]; then
        v_s2h=1
      fi
      if [ "$v_memc" != "off" ] || [ "$v_s2h" != "0" ]; then
        printf '%s (视频增强)\n' "$local_pkg" > "$AUTO_STATE_FILE"
        apply_iris_pipeline "auto" "$v_s2h" 0 "$v_memc" "$MEMC_GAME_ID" "$MEMC_LATENCY" 30 "$v_det" 0 "$SR_GAME_ID"
      fi
    fi
    release_lock
    ;;

  scene_game)
    # Usage: scene_game <pkg> <game_id> <sdr2hdr_id_or_0> <emv:0|1>
    acquire_lock
    load_state
    if [ "$AUTO_SCENE" = "1" ] && ! has_manual_override; then
      local_pkg="$1"
      local_gid="${2:-255}"
      local_s2h="${3:-0}"
      local_emv="${4:-0}"
      g_memc="off"
      g_det=0
      g_sr=0
      g_s2h=0
      if [ "$AUTO_GAME_MEMC" = "1" ]; then
        if [ "$local_emv" = "1" ]; then
          g_memc="game_emv"
        else
          g_memc="global_game"
        fi
        g_det=1
      fi
      if [ "$AUTO_GAME_SR" = "1" ]; then
        g_sr=2
      fi
      if [ "$AUTO_GAME_HDR" = "1" ]; then
        if [ "$local_s2h" != "0" ]; then g_s2h="$local_s2h"; else g_s2h=3; fi
      fi
      if [ "$g_memc" != "off" ] || [ "$g_sr" != "0" ] || [ "$g_s2h" != "0" ]; then
        printf '%s (游戏超帧/超分 #%s)\n' "$local_pkg" "$local_gid" > "$AUTO_STATE_FILE"
        apply_iris_pipeline "auto" "$g_s2h" 0 "$g_memc" "$local_gid" 50 45 "$g_det" "$g_sr" "$local_gid"
      fi
    fi
    release_lock
    ;;

  scene_exit)
    acquire_lock
    load_state
    if [ -f "$AUTO_STATE_FILE" ]; then
      rm -f "$AUTO_STATE_FILE" 2>/dev/null
      if ! has_manual_override; then
        apply_iris_pipeline "$CHIP_MODE" "$SDR2HDR_ID" "$DIRECT_HDR" "$MEMC_MODE" \
          "$MEMC_GAME_ID" "$MEMC_LATENCY" "$MEMC_FPS" "$MEMC_DETECT" "$SR_MODE" "$SR_GAME_ID"
      fi
    fi
    release_lock
    ;;

  reset)
    acquire_lock
    init_defaults
    save_state
    rm -f "$AUTO_STATE_FILE" 2>/dev/null
    apply_all
    release_lock
    print_status
    ;;
esac
