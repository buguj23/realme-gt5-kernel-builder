#!/system/bin/sh
MODDIR="${0%/*}"
out=$(sh "$MODDIR/halo_ctl.sh" toggle)
if echo "$out" | grep -q '"enabled":1'; then
  echo "觉醒光环 Pro：已开启"
else
  echo "觉醒光环 Pro：已关闭（0 功耗待机）"
fi
