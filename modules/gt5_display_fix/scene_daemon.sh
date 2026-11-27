#!/system/bin/sh
# Realme GT5 Pixelworks X7 Factory App Auto-Scene & Screen-Wake Guard Daemon
# Event-driven (0% CPU idle):
#   1. Parses GT5 factory multimedia_pixelworks_apps.xml & multimedia_pixelworks_game_apps.xml once.
#   2. Watches kernel-filtered `logcat -b events -s input_focus:I` for foreground app changes.
#   3. Watches kernel-filtered `logcat -s PowerManagerService:W` for screen-on gamut/DC restore.

MODDIR="${0%/*}"
CTL="$MODDIR/display_ctl.sh"
VIDEO_XML="/mnt/vendor/my_product/vendor/etc/multimedia_pixelworks_apps.xml"
GAME_XML="/mnt/vendor/my_product/vendor/etc/multimedia_pixelworks_game_apps.xml"
VIDEO_MAP="/dev/.gt5_display_video.map"
GAME_MAP="/dev/.gt5_display_game.map"

# ---------- Build fast lookup tables once from factory XMLs ----------
build_maps() {
  : > "$VIDEO_MAP"
  : > "$GAME_MAP"

  if [ -r "$VIDEO_XML" ]; then
    awk '
      /<mConfigActivity / {
        mt = "40"
        if (match($0, /type="258-[0-9]+/)) {
          s = substr($0, RSTART + 10, RLENGTH - 10)
          mt = s
        }
        if (match($0, />[^<]+</)) {
          body = substr($0, RSTART + 1, RLENGTH - 2)
          split(body, a, "/")
          pkg = a[1]
          if (pkg != "" && !(pkg in vmap)) vmap[pkg] = mt
        }
      }
      /<mConfigPackage / {
        if (match($0, />[^<]+</)) {
          pkg = substr($0, RSTART + 1, RLENGTH - 2)
          if (pkg != "" && !(pkg in vmap)) vmap[pkg] = "40"
        }
      }
      END {
        for (p in vmap) printf "%s|%s\n", p, vmap[p]
      }
    ' "$VIDEO_XML" > "$VIDEO_MAP" 2>/dev/null
  fi

  if [ -r "$GAME_XML" ]; then
    awk '
      BEGIN {
        # Factory iris_configs.xml game_id -> PxlwSdr2hdrList Id
        s2h[0] = 18; s2h[2] = 29; s2h[3] = 17; s2h[4] = 21
        s2h[6] = 20; s2h[8] = 22; s2h[9] = 27; s2h[10] = 19
        s2h[11] = 24; s2h[12] = 23; s2h[13] = 28; s2h[16] = 16
      }
      /<mConfigMEMCSRPackage / {
        gid = "255"
        if (match($0, /type="[0-9]+"/)) {
          gid = substr($0, RSTART + 6, RLENGTH - 7)
        }
        if (match($0, />[^<]+</)) {
          pkg = substr($0, RSTART + 1, RLENGTH - 2)
          if (pkg != "") gmap[pkg] = gid
        }
      }
      /<mConfigSRPackage / {
        gid = "255"
        if (match($0, /type="273-1-[0-9]+"/)) {
          gid = substr($0, RSTART + 12, RLENGTH - 13)
        }
        if (match($0, />[^<]+</)) {
          pkg = substr($0, RSTART + 1, RLENGTH - 2)
          if (pkg != "" && !(pkg in gmap)) gmap[pkg] = gid
        }
      }
      /<mConfigEMVAutoPackage / {
        if (match($0, />[^<]+</)) {
          pkg = substr($0, RSTART + 1, RLENGTH - 2)
          if (pkg != "") {
            emv[pkg] = 1
            if (!(pkg in gmap)) gmap[pkg] = "255"
          }
        }
      }
      END {
        for (p in gmap) {
          g = gmap[p]
          h = (g in s2h) ? s2h[g] : 0
          e = (p in emv) ? 1 : 0
          printf "%s|%s|%s|%s\n", p, g, h, e
        }
      }
    ' "$GAME_XML" > "$GAME_MAP" 2>/dev/null
  fi
}

build_maps

# ---------- Watcher 1: Screen-On Gamut / Color Temp / DC Dimming Guard ----------
(
  while true; do
    logcat -T 1 -v raw -s PowerManagerService:W 2>/dev/null | while IFS= read -r line; do
      case "$line" in
        *"Screen on took"*)
          sleep 0.25
          sh "$CTL" screen_restore >/dev/null 2>&1 || true
          ;;
      esac
    done
    sleep 3
  done
) </dev/null >/dev/null 2>&1 &

# ---------- Watcher 2: Event-Driven Foreground App Auto-Scene Engine ----------
(
  last_pkg=""
  last_matched=0
  while true; do
    logcat -b events -T 1 -v raw -s input_focus:I 2>/dev/null | while IFS= read -r line; do
      case "$line" in
        *"Focus entering "*"/"*)
          # Format: [Focus entering 20d81cb com.pkg/com.pkg.Act,reason=...]
          rest="${line#*Focus entering }"
          rest="${rest#* }"
          pkg="${rest%%/*}"
          # Ignore malformed tokens or unchanged app
          case "$pkg" in
            ''|*' '*|*'['*|*','*) continue ;;
          esac
          [ "$pkg" = "$last_pkg" ] && continue
          last_pkg="$pkg"

          # Fast skip if Auto-Scene is disabled in state.env
          if ! grep -q '^AUTO_SCENE=1$' /data/adb/gt5_display/state.env 2>/dev/null; then
            if [ "$last_matched" = "1" ]; then
              last_matched=0
              sh "$CTL" scene_exit >/dev/null 2>&1 || true
            fi
            continue
          fi

          # Check video map first
          v_hit=$(grep -m1 "^${pkg}|" "$VIDEO_MAP" 2>/dev/null)
          if [ -n "$v_hit" ]; then
            mt="${v_hit#*|}"
            last_matched=1
            sh "$CTL" scene_video "$pkg" "$mt" >/dev/null 2>&1 || true
            continue
          fi

          # Check game map second
          g_hit=$(grep -m1 "^${pkg}|" "$GAME_MAP" 2>/dev/null)
          if [ -n "$g_hit" ]; then
            rem="${g_hit#*|}"
            gid="${rem%%|*}"
            rem="${rem#*|}"
            s2h="${rem%%|*}"
            emv="${rem#*|}"
            last_matched=1
            sh "$CTL" scene_game "$pkg" "$gid" "$s2h" "$emv" >/dev/null 2>&1 || true
            continue
          fi

          # Left enhanced app -> return cleanly to user base state / ABP bypass
          if [ "$last_matched" = "1" ]; then
            last_matched=0
            sh "$CTL" scene_exit >/dev/null 2>&1 || true
          fi
          ;;
      esac
    done
    sleep 3
  done
) </dev/null >/dev/null 2>&1 &
