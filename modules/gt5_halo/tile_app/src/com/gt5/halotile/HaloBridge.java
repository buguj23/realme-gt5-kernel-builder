package com.gt5.halotile;

import android.content.ComponentName;
import android.content.Context;
import android.service.quicksettings.TileService;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.FileReader;
import java.nio.charset.StandardCharsets;

public final class HaloBridge {
    public static final String STATE_FILE = "state";
    public static final String CMD_FILE = "cmd";

    public static final class HaloState {
        public final boolean enabled;
        public final String mode;
        public final int brightness;

        public HaloState(boolean enabled, String mode, int brightness) {
            this.enabled = enabled;
            this.mode = mode;
            this.brightness = brightness;
        }
    }

    public static void ensureFiles(Context ctx) {
        try {
            File dir = ctx.getFilesDir();
            if (!dir.exists()) dir.mkdirs();
            File state = new File(dir, STATE_FILE);
            if (!state.exists()) {
                try (FileOutputStream fos = new FileOutputStream(state)) {
                    fos.write("0|always_on|60\n".getBytes(StandardCharsets.UTF_8));
                }
            }
        } catch (Throwable ignored) {
        }
    }

    public static HaloState readState(Context ctx) {
        ensureFiles(ctx);
        File f = new File(ctx.getFilesDir(), STATE_FILE);
        try (BufferedReader br = new BufferedReader(new FileReader(f))) {
            String line = br.readLine();
            if (line != null) {
                String[] parts = line.trim().split("\\|");
                boolean en = parts.length > 0 && "1".equals(parts[0]);
                String mode = (parts.length > 1 && !parts[1].isEmpty()) ? parts[1] : "always_on";
                int pct = 60;
                if (parts.length > 2) {
                    try {
                        pct = Integer.parseInt(parts[2]);
                    } catch (NumberFormatException ignored) {
                    }
                }
                return new HaloState(en, mode, Math.max(0, Math.min(100, pct)));
            }
        } catch (Throwable ignored) {
        }
        return new HaloState(false, "always_on", 60);
    }

    public static void sendCommand(Context ctx, String command) {
        ensureFiles(ctx);
        File cmd = new File(ctx.getFilesDir(), CMD_FILE);
        try (FileOutputStream fos = new FileOutputStream(cmd, false)) {
            fos.write((command + "\n").getBytes(StandardCharsets.UTF_8));
            fos.flush();
        } catch (Throwable ignored) {
        }
    }

    public static void writeOptimisticState(Context ctx, boolean enabled, String mode, int brightness) {
        ensureFiles(ctx);
        File state = new File(ctx.getFilesDir(), STATE_FILE);
        try (FileOutputStream fos = new FileOutputStream(state, false)) {
            String out = (enabled ? "1" : "0") + "|" + mode + "|" + brightness + "\n";
            fos.write(out.getBytes(StandardCharsets.UTF_8));
            fos.flush();
        } catch (Throwable ignored) {
        }
    }

    public static String modeLabel(String mode) {
        if ("breath".equals(mode)) return "硬件呼吸";
        if ("blink".equals(mode)) return "节奏闪烁";
        if ("marquee".equals(mode)) return "跑马流光";
        if ("rainbow".equals(mode)) return "四区彩虹";
        return "常亮";
    }

    public static void requestTileRefresh(Context ctx) {
        try {
            TileService.requestListeningState(
                    ctx.getApplicationContext(),
                    new ComponentName(ctx.getApplicationContext(), HaloTileService.class));
        } catch (Throwable ignored) {
        }
    }
}
