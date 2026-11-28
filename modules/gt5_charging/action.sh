#!/system/bin/sh
# Open「充电记录」native Settings UI directly from YukiSU Manager Action button
am start -n com.gt5.charging/.ChargingHistoryActivity >/dev/null 2>&1
echo "已打开「充电记录」页面（也可在 系统设置 → 电池 → 充电记录 中进入）"
