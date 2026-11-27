package com.gt5.halotile;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.SeekBar;
import android.widget.TextView;

public class QuickControlActivity extends Activity {

    private static final String[][] MODES = {
        {"always_on", "常亮"},
        {"breath",    "硬件呼吸"},
        {"blink",     "节奏闪烁"},
        {"marquee",   "跑马流光"},
        {"rainbow",   "四区彩虹"}
    };

    private boolean enabled;
    private String mode;
    private int brightness;

    private TextView powerBtn;
    private TextView brValue;
    private final TextView[] modeBtns = new TextView[MODES.length];

    private int dp(int v) {
        return Math.round(TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics()));
    }

    private GradientDrawable roundedBg(int color, int radiusDp, int strokeColor) {
        GradientDrawable gd = new GradientDrawable();
        gd.setColor(color);
        gd.setCornerRadius(dp(radiusDp));
        if (strokeColor != 0) {
            gd.setStroke(dp(1), strokeColor);
        }
        return gd;
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        requestWindowFeature(Window.FEATURE_NO_TITLE);

        HaloBridge.HaloState st = HaloBridge.readState(this);
        enabled = st.enabled;
        mode = st.mode;
        brightness = st.brightness > 0 ? st.brightness : 60;

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(18), dp(20), dp(18));
        root.setBackground(roundedBg(0xFF151924, 24, 0x26FFFFFF));

        // Header row: title + power pill
        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);

        LinearLayout titleCol = new LinearLayout(this);
        titleCol.setOrientation(LinearLayout.VERTICAL);
        LinearLayout.LayoutParams tcLp = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
        titleCol.setLayoutParams(tcLp);

        TextView title = new TextView(this);
        title.setText("觉醒光环 Pro");
        title.setTextColor(Color.WHITE);
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        titleCol.addView(title);

        TextView sub = new TextView(this);
        sub.setText("Realme GT5 · 快捷控光");
        sub.setTextColor(0xFF8B95AB);
        sub.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        titleCol.addView(sub);
        header.addView(titleCol);

        powerBtn = new TextView(this);
        powerBtn.setPadding(dp(16), dp(9), dp(16), dp(9));
        powerBtn.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        powerBtn.setTypeface(Typeface.DEFAULT_BOLD);
        powerBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                enabled = !enabled;
                pushState(enabled ? "on" : "off");
            }
        });
        header.addView(powerBtn);
        root.addView(header);

        // Mode label
        TextView modeTitle = new TextView(this);
        modeTitle.setText("灯效模式");
        modeTitle.setTextColor(0xFF8B95AB);
        modeTitle.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        LinearLayout.LayoutParams mtLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        mtLp.topMargin = dp(16);
        mtLp.bottomMargin = dp(8);
        root.addView(modeTitle, mtLp);

        // 2 rows of mode chips (3 + 2)
        LinearLayout row1 = makeRow();
        LinearLayout row2 = makeRow();
        for (int i = 0; i < MODES.length; i++) {
            final int idx = i;
            TextView chip = new TextView(this);
            chip.setText(MODES[i][1]);
            chip.setGravity(Gravity.CENTER);
            chip.setPadding(dp(8), dp(10), dp(8), dp(10));
            chip.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
            LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
            clp.setMargins(dp(4), dp(4), dp(4), dp(4));
            chip.setLayoutParams(clp);
            chip.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    mode = MODES[idx][0];
                    enabled = true;
                    pushState("mode " + mode);
                }
            });
            modeBtns[i] = chip;
            (i < 3 ? row1 : row2).addView(chip);
        }
        root.addView(row1);
        root.addView(row2);

        // Brightness row
        LinearLayout brHead = new LinearLayout(this);
        brHead.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout.LayoutParams bhLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        bhLp.topMargin = dp(14);
        TextView brLbl = new TextView(this);
        brLbl.setText("总亮度");
        brLbl.setTextColor(0xFF8B95AB);
        brLbl.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        brLbl.setLayoutParams(new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        brHead.addView(brLbl);

        brValue = new TextView(this);
        brValue.setTextColor(Color.WHITE);
        brValue.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        brHead.addView(brValue);
        root.addView(brHead, bhLp);

        SeekBar sb = new SeekBar(this);
        sb.setMax(99);
        sb.setProgress(Math.max(0, Math.min(99, brightness - 1)));
        sb.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                brightness = progress + 1;
                brValue.setText(brightness + "%");
            }
            @Override
            public void onStartTrackingTouch(SeekBar seekBar) {}
            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {
                enabled = true;
                pushState("br " + brightness);
            }
        });
        LinearLayout.LayoutParams sbLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        sbLp.topMargin = dp(6);
        root.addView(sb, sbLp);

        // Footer hint + close button
        LinearLayout foot = new LinearLayout(this);
        foot.setOrientation(LinearLayout.HORIZONTAL);
        foot.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout.LayoutParams fLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        fLp.topMargin = dp(14);

        TextView hint = new TextView(this);
        hint.setText("精细 4 灯分色请在模块 WebUI 中调整");
        hint.setTextColor(0xFF6B7280);
        hint.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
        hint.setLayoutParams(new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        foot.addView(hint);

        TextView closeBtn = new TextView(this);
        closeBtn.setText("完成");
        closeBtn.setTextColor(0xFF9FB8FF);
        closeBtn.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        closeBtn.setTypeface(Typeface.DEFAULT_BOLD);
        closeBtn.setPadding(dp(12), dp(6), dp(4), dp(6));
        closeBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                finish();
            }
        });
        foot.addView(closeBtn);
        root.addView(foot, fLp);

        setContentView(root);
        setFinishOnTouchOutside(true);

        Window win = getWindow();
        if (win != null) {
            WindowManager.LayoutParams lp = win.getAttributes();
            lp.width = Math.min(dp(340), getResources().getDisplayMetrics().widthPixels - dp(32));
            win.setAttributes(lp);
        }

        renderUi();
    }

    private LinearLayout makeRow() {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));
        return row;
    }

    private void pushState(String cmd) {
        HaloBridge.writeOptimisticState(this, enabled, mode, brightness);
        HaloBridge.sendCommand(this, cmd);
        HaloBridge.requestTileRefresh(this);
        renderUi();
    }

    private void renderUi() {
        powerBtn.setText(enabled ? "● 已开启" : "○ 已关闭");
        powerBtn.setTextColor(enabled ? Color.WHITE : 0xFF8B95AB);
        powerBtn.setBackground(enabled
                ? roundedBg(0xFF5B7CFA, 99, 0)
                : roundedBg(0xFF1C2231, 99, 0x22FFFFFF));
        brValue.setText(brightness + "%");
        for (int i = 0; i < MODES.length; i++) {
            boolean active = MODES[i][0].equals(mode);
            modeBtns[i].setTextColor(active ? Color.WHITE : 0xFFCBD5E1);
            modeBtns[i].setTypeface(active ? Typeface.DEFAULT_BOLD : Typeface.DEFAULT);
            modeBtns[i].setBackground(active
                    ? roundedBg(0x336C8CFF, 12, 0xFF6C8CFF)
                    : roundedBg(0xFF1C2231, 12, 0x1AFFFFFF));
        }
    }
}
