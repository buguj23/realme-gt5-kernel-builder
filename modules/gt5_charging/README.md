# GT5 150W 快充修复与充电记录 (`gt5_charging`)

面向 **Realme GT5 (`RMX3820` / `22635`) + Project Infinity-X 3.12 (Android 16 GSI)** 的系统级快充修复与充电可视化模块。

## 1. 150W SuperVOOC 快充修复原理（经真机 HAL & 内核逆向实测）

在 GSI 环境下，原厂 `oplus_chg.ko` 与 `/odm/bin/hw/vendor.oplus.hardware.charger-V5-service` 均正常运行，但缺少 ColorOS 上层 `horae` 与 `Battery.apk` 的四个关键桥接导致 150W 快充被大幅限速：

1. **壳温桥接 (`/proc/shell-temp`)**：无 `horae` 时 `shell_front`/`shell_frame`/`shell_back` 长期停在 `-127000` (`-127°C`)，`oplus_chg_get_shell_temp()` 返回异常值。守护进程实时读取 `skin-msm-therm` + `battery` + `batt0_con_therm_adc` 硬件热敏传感器并写入 `/proc/shell-temp`。
2. **启用原厂 150W Hyper 温控曲线 (`ICharger.setCustomSelectChgMode(3, true)`)**：GSI 默认 `s_chg_user_mode=0`（`charging_thermal_config_default.txt`，36.0°C 即降流至 8A）；切换至 `mode=3` 后由 HAL 原生加载 `/odm/firmware/fastchg/22635/charging_hyper_mode_config.txt`（40.5°C 前保持全速，40.5/41.5/42.5/44.0°C 原厂安全阶梯降流）。
3. **解除 BCC 寿命保护限流 (`ICharger.setSmartChgMode("0")`)**：解除默认 `smart_charge_mode=1` 的负极电位限流，将 `bcc_current` 归零。
4. **息屏快充信号同步 (`ICharger.notifyScreenStatus(0|1)`)**：实时监听 `debug.tracing.screen_state`，息屏时通知 HAL 启动 `scale_chg` 息屏极速温控线程，亮屏时暂停。

## 2. 类原生「系统设置 → 电池 → 充电记录」

- 通过标准 AOSP `com.android.settings.action.IA_SETTINGS` + `category.ia.battery` 挂载于 `/system/system_ext/app/Gt5ChargingHistory/`（配合同签名 `/data/app` 系统应用更新副本兼容 YukiSU `umount_modules=1`），零修改 `Settings.apk`、零静态 RRO 覆盖。
- 严格对齐 Android 16 Material 3 Expressive（莫奈动态取色、自动深浅色、分组圆角卡片、双轴可触控滑动曲线图：充电功率 W · 电池温度 °C · 电量 % · 时间）。
- 后台采样间隔可配置（`1 / 2 / 5 / 10 分钟`，全部 ≥ 1 分钟），拔出充电器后零唤醒待机。

## 3. 重新构建 APK

```bash
bash app/build_apk.sh
```
