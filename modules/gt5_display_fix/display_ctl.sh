#!/system/bin/sh
# Realme GT5 (RMX3820 / Pixelworks X7 Iris 7 + Tianma TM1240) Display & Chip Controller
# Strictly uses live-verified /odm/bin/irisConfig & /sys/kernel/oplus_display/* interfaces.

IRIS="/odm/bin/irisConfig"
SYS_DISP="/sys/kernel/oplus_display"
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
  DIRECT_HDR=0              # 0,5,9,61,62
  MEMC_MODE="off"           # off | video_single | video_dual | video_netflix | game | game_emv
  MEMC_GAME_ID=3            # factory game id (3=原神, 0=和平精英, 10=王者, 16=LOL, 4=崩坏3, 155=星穹, 153=逆水寒, 255=通用)
  MEMC_LATENCY=50           # 50=ultra-low(0x32), 34=low(0x22), 18=normal(0x12), 51=eMV1(0x33)
  MEMC_FPS=45               # 0=Auto, 30, 45, 60
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
  case "$DIRECT_HDR" in 0|5|9|61|62) ;; *) DIRECT_HDR=0 ;; esac
  case "$MEMC_MODE" in off|video_single|video_dual|video_netflix|game|game_emv) ;; *) MEMC_MODE="off" ;; esac
  MEMC_GAME_ID=$(clamp_int "$MEMC_GAME_ID" 0 255 3)
  case "$MEMC_LATENCY" in 18|34|50|51) ;; *) MEMC_LATENCY=50 ;; esac
  case "$MEMC_FPS" in 0|30|45|60) ;; *) MEMC_FPS=45 ;; esac
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

apply_gamut_and_temp() {
  local skip_temp="${1:-0}"
  case "$GAMUT" in
    native)      iris_run -colormode 0 0 ;;
    p3_vivid)    iris_run -colormode 9 308 ;;
    p3_nature)   iris_run -colormode 9 304 ;;
    p3_pro)      iris_run -colormode 9 302 ;;
    srgb_pro)    iris_run -colormode 7 301 ;;
    srgb_nature) iris_run -colormode 7 303 ;;
    bt2020)      iris_run 40 1 6 ;;
  esac
  if [ "$skip_temp" != "1" ]; then
    iris_run 48 1 "$COLOR_TEMP"
  fi
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
  sys_write hbm "$PANEL_HBM"
  sys_write LCM_CABC "$LCM_CABC"
  sys_write dither "$PANEL_DITHER"
  sys_write seed "$PANEL_SEED"
}

is_bypass_sdr2hdr() {
  case "$1" in
    0|4|5|7) return 0 ;;
    *) return 1 ;;
  esac
}

# Core applier for a given Iris7 pipeline configuration
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
    if [ "$mm" != "off" ] || [ "$srm" != "0" ] || [ "$dhdr" != "0" ]; then
      need_pt=1
    elif ! is_bypass_sdr2hdr "$s2h"; then
      need_pt=1
    fi
  fi

  local cur_bypass
  cur_bypass=$(iris_get1 56)

  if [ "$need_pt" = "1" ]; then
    # 1. Wake Pixelworks X7 into PT Active mode first
    if [ "$cur_bypass" != "0" ]; then
      iris_run 56 1 0
    fi

    # 2. Apply Direct HDR pipeline (Type 47)
    iris_run 47 1 "$dhdr"

    # 3. Apply Video/Game SDR2HDR / EDR / Filter (Type 267)
    iris_run 267 2 3 "$s2h"

    # 4. Apply Super Resolution (Type 273)
    if [ "$srm" = "0" ]; then
      iris_run 273 1 0
    else
      iris_run 273 3 1 "$srgid" "$srm"
    fi

    # 5. Apply MEMC Scenario Detection (Type 13) & MEMC (Type 258)
    iris_run 13 1 "$mdet"
    case "$mm" in
      off)           iris_run 258 1 0 ;;
      video_single)  iris_run 258 3 10 0 0 ;;
      video_dual)    iris_run 258 3 40 0 0 ;;
      video_netflix) iris_run 258 3 74 0 0 ;;
      game)          iris_run 258 6 10 99 "$mlat" 99 "$mgid" "$mfps" ;;
      game_emv)      iris_run 258 3 40 255 6 ;;
    esac

    # 6. Apply Gamut & Color Temp (preserve preset Kelvin for 6=Cinema6500K / 12=Movie5000K)
    if [ "$s2h" = "6" ] || [ "$s2h" = "12" ]; then
      apply_gamut_and_temp 1
    else
      apply_gamut_and_temp 0
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

    # 2. Enter ABP Analog Bypass for 0 extra chip power (wait briefly for MEMC/SR teardown)
    if [ "$cur_bypass" != "1" ]; then
      sleep 0.15
      iris_run 56 1 1
      if [ "$(iris_get1 56)" != "1" ]; then
        sleep 0.2
        iris_run 56 1 1
      fi
    fi

    # 3. Bypass-compatible SDR2HDR (0=Off, 4=Low-Power Video HDR, 5=Low-Power Game HDR, 7=APL)
    if is_bypass_sdr2hdr "$s2h"; then
      iris_run 267 2 3 "$s2h"
    fi

    # 4. SoftIris Color Gamut & Hardware Color Temp work natively in Bypass
    apply_gamut_and_temp 0
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

# ---------- Live JSON status output ----------
print_status() {
  local hw_bypass hw_gamut hw_temp hw_memc hw_s2h hw_sr hw_hdr hw_feat
  local hw_hbm hw_pwm hw_cabc hw_dither hw_seed hw_bl hw_bl_max
  local sys_hdr_ready sys_hbm_ready auto_pkg

  hw_bypass=$(iris_get1 56)
  hw_gamut=$(iris_get1 40)
  hw_temp=$(iris_get1 48)
  hw_memc=$(iris_get1 258)
  hw_s2h=$(iris_get1 267)
  hw_sr=$(iris_get1 273)
  hw_hdr=$(iris_get1 47)
  hw_feat=$(getprop persist.vendor.display.pxlw.iris_feature 2>/dev/null)
  [ -z "$hw_feat" ] && hw_feat="0x41ff0780"

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
{"chip_mode":"$CHIP_MODE","gamut":"$GAMUT","color_temp":$COLOR_TEMP,"sdr2hdr_id":$SDR2HDR_ID,"direct_hdr":$DIRECT_HDR,"memc_mode":"$MEMC_MODE","memc_game_id":$MEMC_GAME_ID,"memc_latency":$MEMC_LATENCY,"memc_fps":$MEMC_FPS,"memc_detect":$MEMC_DETECT,"sr_mode":$SR_MODE,"sr_game_id":$SR_GAME_ID,"pwm_onepulse":$PWM_ONEPULSE,"panel_hbm":$PANEL_HBM,"lcm_cabc":$LCM_CABC,"panel_dither":$PANEL_DITHER,"panel_seed":$PANEL_SEED,"sys_hdr_enabled":$SYS_HDR_ENABLED,"sys_hdr_boost":$SYS_HDR_BOOST,"boot_restore":$BOOT_RESTORE,"screen_restore":$SCREEN_RESTORE,"auto_scene":$AUTO_SCENE,"auto_video_memc":$AUTO_VIDEO_MEMC,"auto_video_hdr":$AUTO_VIDEO_HDR,"auto_game_memc":$AUTO_GAME_MEMC,"auto_game_sr":$AUTO_GAME_SR,"auto_game_hdr":$AUTO_GAME_HDR,"hw":{"bypass":${hw_bypass:--1},"gamut":${hw_gamut:--1},"color_temp":${hw_temp:--1},"memc":${hw_memc:--1},"sdr2hdr":${hw_s2h:--1},"sr":${hw_sr:--1},"direct_hdr":${hw_hdr:--1},"feature":"$hw_feat","hbm":${hw_hbm:--1},"pwm_onepulse":${hw_pwm:--1},"lcm_cabc":${hw_cabc:--1},"dither":${hw_dither:--1},"seed":${hw_seed:--1},"backlight":${hw_bl:-0},"backlight_max":${hw_bl_max:-4095},"sys_hdr_ready":$sys_hdr_ready,"sys_hbm_ready":$sys_hbm_ready,"auto_active":"$auto_pkg"}}
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
        CHIP_MODE|GAMUT|COLOR_TEMP|SDR2HDR_ID|DIRECT_HDR|MEMC_MODE|MEMC_GAME_ID|MEMC_LATENCY|MEMC_FPS|MEMC_DETECT|SR_MODE|SR_GAME_ID|PWM_ONEPULSE|PANEL_HBM|LCM_CABC|PANEL_DITHER|PANEL_SEED|SYS_HDR_ENABLED|SYS_HDR_BOOST|BOOT_RESTORE|SCREEN_RESTORE|AUTO_SCENE|AUTO_VIDEO_MEMC|AUTO_VIDEO_HDR|AUTO_GAME_MEMC|AUTO_GAME_SR|AUTO_GAME_HDR)
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
        SDR2HDR_ID=6; DIRECT_HDR=0; MEMC_MODE="video_dual"; MEMC_DETECT=1; SR_MODE=0
        ;;
      video_hdr)
        CHIP_MODE="auto"; GAMUT="p3_vivid"; COLOR_TEMP=6500
        SDR2HDR_ID=1; DIRECT_HDR=0; MEMC_MODE="video_dual"; MEMC_DETECT=1; SR_MODE=0
        ;;
      esports)
        CHIP_MODE="auto"; GAMUT="p3_vivid"; COLOR_TEMP=6800
        SDR2HDR_ID=3; DIRECT_HDR=0; MEMC_MODE="game"; MEMC_LATENCY=50; MEMC_FPS=45; MEMC_DETECT=1; SR_MODE=2
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
    release_lock
    ;;

  screen_restore)
    acquire_lock
    load_state
    if [ "$SCREEN_RESTORE" = "1" ]; then
      # Only re-apply gamut, color temp, and panel DC dimming cleanly on screen wake
      if [ "$SDR2HDR_ID" = "6" ] || [ "$SDR2HDR_ID" = "12" ]; then
        apply_gamut_and_temp 1
      else
        apply_gamut_and_temp 0
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
          10) v_memc="video_single" ;;
          74) v_memc="video_netflix" ;;
          *)  v_memc="video_dual" ;;
        esac
        v_det=1
      fi
      if [ "$AUTO_VIDEO_HDR" = "1" ]; then
        v_s2h=1
      fi
      if [ "$v_memc" != "off" ] || [ "$v_s2h" != "0" ]; then
        printf '%s (视频增强)\n' "$local_pkg" > "$AUTO_STATE_FILE"
        apply_iris_pipeline "auto" "$v_s2h" 0 "$v_memc" "$MEMC_GAME_ID" "$MEMC_LATENCY" "$MEMC_FPS" "$v_det" 0 "$SR_GAME_ID"
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
          g_memc="game"
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
