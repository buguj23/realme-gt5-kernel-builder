package com.gt5.charging;

import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.BatteryManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

public final class ChargingStore {

    public static final class LiveState {
        public long ts;
        public boolean wired;
        public String status = "Unknown";
        public String protocol = "读取中";
        public int powerMw;
        public int pbattMw;
        public int pusbMw;
        public int soc;
        public int battTempD1;
        public int shellTempD1;
        public int kernelShellD1 = -2740;
        public int subboardTempD1;
        public int vbatMv;
        public int vpackMv;
        public int ibatMa;
        public int chgMa;
        public int vbusMv;
        public int ibusMa;
        public boolean voocIng;
        public boolean ppsIng;
        public int coolDown;
        public int bccCurrent;
        public int mmiEn = 1;
        public int soh;
        public int fcc;
        public int designCap = 5200;
        public int cycleCount;
        public int devicePower = 150000;
        public int adapterPower;
        public String chargeMode = "hyper";
        public int sampleInterval = 60;
        public int ichargerCustomMode = -1;
        public int ichargerSmartMode = -1;
        public boolean screenOn = true;
        public boolean ledOn = true;
        public boolean fromDaemon = false;
    }

    public static final class SamplePoint {
        public long ts;
        public int powerMw;
        public int battTempD1;
        public int shellTempD1;
        public int soc;
        public String protocol;

        public float powerW() {
            return powerMw / 1000f;
        }

        public float battTempC() {
            return battTempD1 / 10f;
        }

        public float shellTempC() {
            return shellTempD1 / 10f;
        }
    }

    public static final class ChargingSession {
        public String id;
        public long startTs;
        public long endTs;
        public long durationS;
        public int startSoc;
        public int endSoc;
        public int peakMw;
        public int avgMw;
        public int maxTempD1;
        public int avgTempD1;
        public String protocol;
        public final List<SamplePoint> points = new ArrayList<>();
    }

    private ChargingStore() {}

    public static LiveState loadLive(Context ctx) {
        LiveState s = new LiveState();
        File f = new File(ctx.getFilesDir(), "live.json");
        String txt = readText(f);
        if (txt != null && !txt.isEmpty()) {
            try {
                JSONObject o = new JSONObject(txt);
                s.ts = o.optLong("ts", 0);
                s.wired = o.optInt("wired", 0) == 1;
                s.status = o.optString("status", "Unknown");
                s.protocol = o.optString("protocol", "未知");
                s.powerMw = o.optInt("power_mw", 0);
                s.pbattMw = o.optInt("pbatt_mw", 0);
                s.pusbMw = o.optInt("pusb_mw", 0);
                s.soc = o.optInt("soc", 0);
                s.battTempD1 = o.optInt("batt_temp_d1", 0);
                s.shellTempD1 = o.optInt("shell_temp_d1", 0);
                s.kernelShellD1 = o.optInt("kernel_shell_d1", -2740);
                s.subboardTempD1 = o.optInt("subboard_temp_d1", 0);
                s.vbatMv = o.optInt("vbat_mv", 0);
                s.vpackMv = o.optInt("vpack_mv", 0);
                s.ibatMa = o.optInt("ibat_ma", 0);
                s.chgMa = o.optInt("chg_ma", 0);
                s.vbusMv = o.optInt("vbus_mv", 0);
                s.ibusMa = o.optInt("ibus_ma", 0);
                s.voocIng = o.optInt("vooc_ing", 0) == 1;
                s.ppsIng = o.optInt("pps_ing", 0) == 1;
                s.coolDown = o.optInt("cool_down", 0);
                s.bccCurrent = o.optInt("bcc_current", 0);
                s.mmiEn = o.optInt("mmi_en", 1);
                s.soh = o.optInt("soh", 0);
                s.fcc = o.optInt("fcc", 0);
                s.designCap = o.optInt("design_cap", 5200);
                s.cycleCount = o.optInt("cycle_count", 0);
                s.devicePower = o.optInt("device_power", 150000);
                s.adapterPower = o.optInt("adapter_power", 0);
                s.chargeMode = o.optString("charge_mode", "hyper");
                s.sampleInterval = o.optInt("sample_interval", 60);
                s.ichargerCustomMode = o.optInt("icharger_custom_mode", -1);
                s.ichargerSmartMode = o.optInt("icharger_smart_mode", -1);
                s.screenOn = o.optInt("screen_on", 1) == 1;
                s.ledOn = o.optInt("led_on", 1) == 1;
                s.fromDaemon = true;
                return s;
            } catch (Exception ignored) {
            }
        }

        // Graceful fallback via Android BatteryManager while waiting for first daemon sync
        Intent bi = ctx.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        if (bi != null) {
            int level = bi.getIntExtra(BatteryManager.EXTRA_LEVEL, 0);
            int scale = bi.getIntExtra(BatteryManager.EXTRA_SCALE, 100);
            s.soc = scale > 0 ? (level * 100 / scale) : level;
            s.battTempD1 = bi.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0);
            s.shellTempD1 = s.battTempD1;
            int mv = bi.getIntExtra(BatteryManager.EXTRA_VOLTAGE, 0);
            s.vbatMv = mv;
            s.vpackMv = mv * 2;
            int plugged = bi.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0);
            s.wired = plugged != 0;
            int st = bi.getIntExtra(BatteryManager.EXTRA_STATUS, 0);
            s.status = st == BatteryManager.BATTERY_STATUS_FULL ? "Full"
                    : st == BatteryManager.BATTERY_STATUS_CHARGING ? "Charging" : "Discharging";
            s.protocol = s.wired ? (plugged == BatteryManager.BATTERY_PLUGGED_USB ? "USB 5V" : "有线充电") : "未充电";
        }
        return s;
    }

    public static List<ChargingSession> loadHistory(Context ctx) {
        List<ChargingSession> list = new ArrayList<>();
        File f = new File(ctx.getFilesDir(), "history.json");
        String txt = readText(f);
        if (txt == null || txt.isEmpty()) return list;
        try {
            JSONObject root = new JSONObject(txt);
            JSONArray arr = root.optJSONArray("sessions");
            if (arr == null) return list;
            for (int i = 0; i < arr.length(); i++) {
                JSONObject o = arr.optJSONObject(i);
                if (o == null) continue;
                ChargingSession cs = new ChargingSession();
                cs.id = o.optString("id", "s" + i);
                cs.startTs = o.optLong("start_ts", 0);
                cs.endTs = o.optLong("end_ts", 0);
                cs.durationS = o.optLong("duration_s", 0);
                cs.startSoc = o.optInt("start_soc", 0);
                cs.endSoc = o.optInt("end_soc", 0);
                cs.peakMw = o.optInt("peak_mw", 0);
                cs.avgMw = o.optInt("avg_mw", 0);
                cs.maxTempD1 = o.optInt("max_temp_d1", 0);
                cs.avgTempD1 = o.optInt("avg_temp_d1", 0);
                cs.protocol = o.optString("protocol", "有线充电");
                JSONArray pts = o.optJSONArray("points");
                if (pts != null) {
                    for (int j = 0; j < pts.length(); j++) {
                        JSONArray p = pts.optJSONArray(j);
                        if (p == null || p.length() < 6) continue;
                        SamplePoint sp = new SamplePoint();
                        sp.ts = p.optLong(0, 0);
                        sp.powerMw = p.optInt(1, 0);
                        sp.battTempD1 = p.optInt(2, 0);
                        sp.shellTempD1 = p.optInt(3, 0);
                        sp.soc = p.optInt(4, 0);
                        sp.protocol = p.optString(5, cs.protocol);
                        cs.points.add(sp);
                    }
                }
                if (!cs.points.isEmpty()) {
                    list.add(cs);
                }
            }
        } catch (Exception ignored) {
        }
        return list;
    }

    public static void sendCommand(Context ctx, String cmd) {
        File dir = ctx.getFilesDir();
        if (!dir.exists()) {
            //noinspection ResultOfMethodCallIgnored
            dir.mkdirs();
        }
        File f = new File(dir, "cmd");
        try (FileOutputStream fos = new FileOutputStream(f, false)) {
            fos.write((cmd + "\n").getBytes(StandardCharsets.UTF_8));
            fos.flush();
        } catch (Exception ignored) {
        }
    }

    private static String readText(File f) {
        if (f == null || !f.exists() || !f.canRead()) return null;
        StringBuilder sb = new StringBuilder();
        try (BufferedReader br = new BufferedReader(new InputStreamReader(new FileInputStream(f), StandardCharsets.UTF_8))) {
            String line;
            while ((line = br.readLine()) != null) {
                sb.append(line).append('\n');
            }
            return sb.toString();
        } catch (Exception e) {
            return null;
        }
    }
}
