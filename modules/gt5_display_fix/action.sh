#!/system/bin/sh
MODDIR="${0%/*}"
CTL="$MODDIR/display_ctl.sh"

echo "========================================="
echo " 真我 GT5 独显芯片与画质增强中心 Pro"
echo "========================================="
echo "请点击模块卡片的 [打开/WebUI] 按钮进入完整可视化控制面板。"
echo ""
if [ -x "$CTL" ] || [ -f "$CTL" ]; then
  sh "$CTL" status
fi
echo ""
echo "当前系统 HDR / HBM 状态："
dumpsys display 2>/dev/null | grep -E "mHbmData=|mHdrBrightnessData=|hdrSdrRatio" | head -n 6
