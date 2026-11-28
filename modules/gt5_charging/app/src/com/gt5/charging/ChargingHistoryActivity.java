package com.gt5.charging;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.widget.HorizontalScrollView;
import android.widget.ImageButton;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/**
 * Native AOSP / Android 16 Material 3 Expressive Battery Settings sub-screen:
 * - Live Charging Telemetry (Power W, Protocol, 2S Voltage, Current, Batt & Shell Temp, Health)
 * - Interactive Power (W) / Temp (C) / Time Visual Chart with Session History
 * - Realme GT5 150W SuperVOOC Fast-Charging Fix & Mode Control + Hardware Diagnostics
 * - Configurable Sampling Interval (>= 1 minute) & History Management
 */
public class ChargingHistoryActivity extends Activity {

    private static final int ROUND_SINGLE = 0;
    private static final int ROUND_TOP = 1;
    private static final int ROUND_MIDDLE = 2;
    private static final int ROUND_BOTTOM = 3;

    private float dp;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private boolean isResumed = false;

    // Live UI references
    private TextView tvLiveWatt;
    private TextView tvLiveProto;
    private View barProgressFill;
    private TextView tvBarCaption;
    private TextView tvTileSoc, tvTileBattTemp, tvTileShellTemp, tvTileVbus;
    private TextView tvHealthFooter;

    // Chart & session references
    private LinearLayout sessionChipsRow;
    private TextView tvStatPeak, tvStatAvg, tvStatMaxTemp, tvStatDur;
    private ChargingChartView chartView;
    private final List<TextView> chartFilterChips = new ArrayList<>();
    private int currentChartFilter = ChargingChartView.DISPLAY_BOTH;

    // Mode radio references
    private RadioButton rbHyper, rbBalanced, rbCool;
    private TextView tvDiagIcharger, tvDiagShell, tvDiagScreen, tvDiagThermal;
    private View dotIcharger, dotShell, dotScreen, dotThermal;

    // Sampling interval chip references
    private final List<TextView> intervalChips = new ArrayList<>();
    private final int[] intervalValues = {60, 120, 300, 600};

    private List<ChargingStore.ChargingSession> sessions = new ArrayList<>();
    private String selectedSessionId = null;

    private final SimpleDateFormat sessionFmt = new SimpleDateFormat("MM/dd HH:mm", Locale.getDefault());
    private final SimpleDateFormat todayFmt = new SimpleDateFormat("今天 HH:mm", Locale.getDefault());
    private final SimpleDateFormat dayKeyFmt = new SimpleDateFormat("yyyyMMdd", Locale.getDefault());

    private final Runnable autoRefreshTask = new Runnable() {
        @Override
        public void run() {
            if (!isResumed) return;
            refreshUiFromFiles();
            handler.postDelayed(this, 4000);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        dp = getResources().getDisplayMetrics().density;
        setContentView(buildRootView());
        configureEdgeToEdge();
    }

    @Override
    protected void onResume() {
        super.onResume();
        isResumed = true;
        ChargingStore.sendCommand(this, "refresh");
        refreshUiFromFiles();
        handler.postDelayed(this::refreshUiFromFiles, 350);
        handler.postDelayed(autoRefreshTask, 4000);
    }

    @Override
    protected void onPause() {
        super.onPause();
        isResumed = false;
        handler.removeCallbacks(autoRefreshTask);
    }

    private void configureEdgeToEdge() {
        Window w = getWindow();
        w.setDecorFitsSystemWindows(false);
        w.setStatusBarColor(Color.TRANSPARENT);
        w.setNavigationBarColor(Color.TRANSPARENT);
        boolean night = (getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)
                == Configuration.UI_MODE_NIGHT_YES;
        WindowInsetsController ctrl = w.getInsetsController();
        if (ctrl != null) {
            int lightFlags = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                    | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
            ctrl.setSystemBarsAppearance(night ? 0 : lightFlags, lightFlags);
        }
    }

    private View buildRootView() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(getColor(R.color.bg_surface));

        // Top toolbar row (AOSP M3 Expressive circular back button + refresh button)
        LinearLayout topBar = new LinearLayout(this);
        topBar.setOrientation(LinearLayout.HORIZONTAL);
        topBar.setGravity(Gravity.CENTER_VERTICAL);
        topBar.setPadding(d(16), d(12), d(16), d(6));

        ImageButton btnBack = createCircleIconButton(R.drawable.ic_back, "返回");
        btnBack.setOnClickListener(v -> finish());
        topBar.addView(btnBack);

        View spacer = new View(this);
        topBar.addView(spacer, new LinearLayout.LayoutParams(0, 1, 1f));

        ImageButton btnRefresh = createCircleIconButton(R.drawable.ic_refresh, "刷新");
        btnRefresh.setOnClickListener(v -> {
            ChargingStore.sendCommand(this, "refresh");
            handler.postDelayed(this::refreshUiFromFiles, 320);
            Toast.makeText(this, "已刷新实时状态", Toast.LENGTH_SHORT).show();
        });
        topBar.addView(btnRefresh);

        root.addView(topBar, matchWrap());

        // Scrollable content container
        ScrollView scroll = new ScrollView(this);
        scroll.setVerticalScrollBarEnabled(false);
        scroll.setOverScrollMode(View.OVER_SCROLL_IF_CONTENT_SCROLLS);

        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(d(16), d(4), d(16), d(28));

        // Large Expressive Header Title (aligned with batt_settings.png)
        TextView tvTitle = new TextView(this);
        tvTitle.setText("充电记录");
        tvTitle.setTextColor(getColor(R.color.text_primary));
        tvTitle.setTextSize(30f);
        tvTitle.setTypeface(Typeface.create("sans-serif", Typeface.NORMAL));
        LinearLayout.LayoutParams titleLp = matchWrap();
        titleLp.setMargins(d(6), d(6), d(6), d(18));
        content.addView(tvTitle, titleLp);

        // 1. Live Status Hero Card
        content.addView(buildLiveHeroCard(), lpMarginBottom(16));

        // 2. Interactive Visual Chart Card
        content.addView(buildSectionLabel("功率、温度与时间曲线"), lpMarginBottom(8));
        content.addView(buildChartCard(), lpMarginBottom(18));

        // 3. 150W Fast Charging Fix & Strategy Section
        content.addView(buildSectionLabel("150W 快充修复与温控策略"), lpMarginBottom(8));
        content.addView(buildModeRadioCard("150W 极速快充（推荐 · 已修复）",
                "启用原厂 Hyper 40.5°C 温控曲线、解除 BCC 限流，自动桥接壳温与息屏信号",
                ROUND_TOP, "hyper"), lpMarginBottom(3));
        content.addView(buildModeRadioCard("原厂均衡快充",
                "保留 36°C 保守温控与 BCC 电池寿命保护，维持壳温与息屏链路修复",
                ROUND_MIDDLE, "balanced"), lpMarginBottom(3));
        content.addView(buildModeRadioCard("低温慢充护电池",
                "限制峰值充电电流约 40W 档位，有效降低发热，适合夜间长时充电",
                ROUND_BOTTOM, "cool"), lpMarginBottom(12));

        // Live 150W Hardware Diagnostics Card
        content.addView(buildDiagnosticsCard(), lpMarginBottom(18));

        // 4. Sampling Interval & History Management Section
        content.addView(buildSectionLabel("采样间隔与记录管理"), lpMarginBottom(8));
        content.addView(buildIntervalCard(), lpMarginBottom(3));
        content.addView(buildActionRow("立即采样一次",
                "手动将当前实时功率、温度与电量追加到充电曲线",
                ROUND_MIDDLE, false, v -> {
                    ChargingStore.sendCommand(this, "sample_now");
                    handler.postDelayed(this::refreshUiFromFiles, 420);
                    Toast.makeText(this, "已触发一次采样", Toast.LENGTH_SHORT).show();
                }), lpMarginBottom(3));
        content.addView(buildActionRow("清空历史充电记录",
                "删除本地保存的全部历史充电曲线数据",
                ROUND_BOTTOM, true, v -> confirmClearHistory()), lpMarginBottom(12));

        scroll.addView(content, matchWrap());
        root.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        // Apply edge-to-edge system bar insets cleanly
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
            topBar.setPadding(d(16), bars.top + d(10), d(16), d(6));
            content.setPadding(d(16), d(4), d(16), bars.bottom + d(28));
            return insets;
        });

        return root;
    }

    private ImageButton createCircleIconButton(int drawableRes, String desc) {
        ImageButton btn = new ImageButton(this);
        btn.setImageResource(drawableRes);
        btn.setContentDescription(desc);
        btn.setScaleType(ImageView.ScaleType.CENTER_INSIDE);
        btn.setPadding(d(9), d(9), d(9), d(9));
        btn.setBackground(makeCircleRipple(getColor(R.color.card_surface)));
        btn.setLayoutParams(new LinearLayout.LayoutParams(d(42), d(42)));
        return btn;
    }

    private TextView buildSectionLabel(String text) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextColor(getColor(R.color.accent_primary));
        tv.setTextSize(13.5f);
        tv.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        tv.setPadding(d(8), d(2), d(8), d(2));
        return tv;
    }

    private View buildLiveHeroCard() {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackground(makeCardBg(ROUND_SINGLE, getColor(R.color.card_surface), false));
        card.setPadding(d(18), d(18), d(18), d(16));

        // Top line: Wattage + Protocol Badge
        LinearLayout topRow = new LinearLayout(this);
        topRow.setOrientation(LinearLayout.HORIZONTAL);
        topRow.setGravity(Gravity.CENTER_VERTICAL);

        tvLiveWatt = new TextView(this);
        tvLiveWatt.setText("-- W");
        tvLiveWatt.setTextColor(getColor(R.color.text_primary));
        tvLiveWatt.setTextSize(34f);
        tvLiveWatt.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        topRow.addView(tvLiveWatt);

        View spc = new View(this);
        topRow.addView(spc, new LinearLayout.LayoutParams(0, 1, 1f));

        tvLiveProto = new TextView(this);
        tvLiveProto.setText("读取中");
        tvLiveProto.setTextColor(getColor(R.color.accent_on_container));
        tvLiveProto.setTextSize(12.5f);
        tvLiveProto.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        tvLiveProto.setPadding(d(12), d(6), d(12), d(6));
        tvLiveProto.setBackground(makePillBg(getColor(R.color.accent_container), 16));
        topRow.addView(tvLiveProto);

        card.addView(topRow, lpMarginBottom(12));

        // Material You Battery Bar (echoing batt_settings.png!)
        LinearLayout barTrack = new LinearLayout(this);
        barTrack.setOrientation(LinearLayout.HORIZONTAL);
        barTrack.setBackground(makePillBg(getColor(R.color.card_surface_variant), 10));
        barProgressFill = new View(this);
        barProgressFill.setBackground(makePillBg(getColor(R.color.bar_green), 10));
        barTrack.addView(barProgressFill, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f));
        View barRem = new View(this);
        barTrack.addView(barRem, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 0f));
        LinearLayout.LayoutParams barLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, d(14));
        barLp.bottomMargin = d(8);
        card.addView(barTrack, barLp);

        tvBarCaption = new TextView(this);
        tvBarCaption.setText("双电芯电压 -- V · 电池电流 -- mA");
        tvBarCaption.setTextColor(getColor(R.color.text_secondary));
        tvBarCaption.setTextSize(12.5f);
        card.addView(tvBarCaption, lpMarginBottom(14));

        // 4 compact telemetry tiles
        LinearLayout tiles = new LinearLayout(this);
        tiles.setOrientation(LinearLayout.HORIZONTAL);
        tvTileSoc = addMiniTile(tiles, "电量", "--%", 0);
        tvTileBattTemp = addMiniTile(tiles, "电池温度", "--°C", 6);
        tvTileShellTemp = addMiniTile(tiles, "机身壳温", "--°C", 6);
        tvTileVbus = addMiniTile(tiles, "USB 电压", "--V", 6);
        card.addView(tiles, lpMarginBottom(12));

        // Battery Health Footer
        tvHealthFooter = new TextView(this);
        tvHealthFooter.setText("电池健康 SOH --% · 满充容量 -- / 5200 mAh · 循环 -- 次");
        tvHealthFooter.setTextColor(getColor(R.color.text_secondary));
        tvHealthFooter.setTextSize(12f);
        card.addView(tvHealthFooter);

        return card;
    }

    private TextView addMiniTile(LinearLayout parent, String label, String initVal, int leftMarginDp) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackground(makePillBg(getColor(R.color.card_surface_variant), 14));
        box.setPadding(d(10), d(9), d(10), d(9));

        TextView tvL = new TextView(this);
        tvL.setText(label);
        tvL.setTextColor(getColor(R.color.text_secondary));
        tvL.setTextSize(11f);
        box.addView(tvL);

        TextView tvV = new TextView(this);
        tvV.setText(initVal);
        tvV.setTextColor(getColor(R.color.text_primary));
        tvV.setTextSize(15f);
        tvV.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        tvV.setSingleLine(true);
        tvV.setPadding(0, d(2), 0, 0);
        box.addView(tvV);

        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        lp.leftMargin = d(leftMarginDp);
        parent.addView(box, lp);
        return tvV;
    }

    private View buildChartCard() {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackground(makeCardBg(ROUND_SINGLE, getColor(R.color.card_surface), false));
        card.setPadding(d(14), d(14), d(14), d(14));

        // Horizontal session chips
        HorizontalScrollView hsv = new HorizontalScrollView(this);
        hsv.setHorizontalScrollBarEnabled(false);
        sessionChipsRow = new LinearLayout(this);
        sessionChipsRow.setOrientation(LinearLayout.HORIZONTAL);
        hsv.addView(sessionChipsRow);
        card.addView(hsv, lpMarginBottom(12));

        // 4-column session summary metrics
        LinearLayout statsRow = new LinearLayout(this);
        statsRow.setOrientation(LinearLayout.HORIZONTAL);
        tvStatPeak = addStatCol(statsRow, "峰值功率", "-- W");
        tvStatAvg = addStatCol(statsRow, "平均功率", "-- W");
        tvStatMaxTemp = addStatCol(statsRow, "最高温度", "-- °C");
        tvStatDur = addStatCol(statsRow, "记录时长", "--");
        card.addView(statsRow, lpMarginBottom(10));

        // Chart filter segmented pills
        LinearLayout filterRow = new LinearLayout(this);
        filterRow.setOrientation(LinearLayout.HORIZONTAL);
        String[] labels = {"功率+温度", "仅功率", "仅温度", "叠加电量"};
        int[] modes = {
                ChargingChartView.DISPLAY_BOTH,
                ChargingChartView.DISPLAY_POWER,
                ChargingChartView.DISPLAY_TEMP,
                ChargingChartView.DISPLAY_ALL
        };
        for (int i = 0; i < labels.length; i++) {
            final int mode = modes[i];
            TextView chip = createFilterChip(labels[i], i == 0);
            chip.setOnClickListener(v -> {
                currentChartFilter = mode;
                chartView.setDisplayMode(mode);
                updateChipGroupStyle(chartFilterChips, mode);
            });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
            if (i > 0) lp.leftMargin = d(6);
            filterRow.addView(chip, lp);
            chartFilterChips.add(chip);
        }
        card.addView(filterRow, lpMarginBottom(8));

        // Custom Interactive High-DPI Chart
        chartView = new ChargingChartView(this);
        card.addView(chartView, matchWrap());

        return card;
    }

    private TextView addStatCol(LinearLayout parent, String label, String val) {
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER_HORIZONTAL);

        TextView tvV = new TextView(this);
        tvV.setText(val);
        tvV.setTextColor(getColor(R.color.text_primary));
        tvV.setTextSize(15f);
        tvV.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        col.addView(tvV);

        TextView tvL = new TextView(this);
        tvL.setText(label);
        tvL.setTextColor(getColor(R.color.text_secondary));
        tvL.setTextSize(11f);
        tvL.setPadding(0, d(2), 0, 0);
        col.addView(tvL);

        parent.addView(col, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        return tvV;
    }

    private TextView createFilterChip(String text, boolean active) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setGravity(Gravity.CENTER);
        tv.setTextSize(12f);
        tv.setSingleLine(true);
        tv.setEllipsize(TextUtils.TruncateAt.END);
        tv.setPadding(d(6), d(7), d(6), d(7));
        styleChip(tv, active);
        return tv;
    }

    private void styleChip(TextView tv, boolean active) {
        if (active) {
            tv.setBackground(makePillBg(getColor(R.color.accent_container), 14));
            tv.setTextColor(getColor(R.color.accent_on_container));
            tv.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        } else {
            tv.setBackground(makePillBg(getColor(R.color.card_surface_variant), 14));
            tv.setTextColor(getColor(R.color.text_secondary));
            tv.setTypeface(Typeface.create("sans-serif", Typeface.NORMAL));
        }
    }

    private void updateChipGroupStyle(List<TextView> chips, int activeIdx) {
        for (int i = 0; i < chips.size(); i++) {
            styleChip(chips.get(i), i == activeIdx);
        }
    }

    private View buildModeRadioCard(String title, String summary, int roundMode, final String modeKey) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setBackground(makeCardBg(roundMode, getColor(R.color.card_surface), true));
        row.setPadding(d(18), d(15), d(16), d(15));
        row.setClickable(true);
        row.setFocusable(true);

        LinearLayout textCol = new LinearLayout(this);
        textCol.setOrientation(LinearLayout.VERTICAL);

        TextView tvT = new TextView(this);
        tvT.setText(title);
        tvT.setTextColor(getColor(R.color.text_primary));
        tvT.setTextSize(16f);
        textCol.addView(tvT);

        TextView tvS = new TextView(this);
        tvS.setText(summary);
        tvS.setTextColor(getColor(R.color.text_secondary));
        tvS.setTextSize(13f);
        tvS.setPadding(0, d(3), 0, 0);
        textCol.addView(tvS);

        row.addView(textCol, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        RadioButton rb = new RadioButton(this);
        rb.setClickable(false);
        rb.setFocusable(false);
        rb.setButtonTintList(ColorStateList.valueOf(getColor(R.color.accent_primary)));
        LinearLayout.LayoutParams rbLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        rbLp.leftMargin = d(12);
        row.addView(rb, rbLp);

        if ("hyper".equals(modeKey)) rbHyper = rb;
        else if ("balanced".equals(modeKey)) rbBalanced = rb;
        else rbCool = rb;

        row.setOnClickListener(v -> {
            setModeRadioVisual(modeKey);
            ChargingStore.sendCommand(this, "set_mode " + modeKey);
            handler.postDelayed(this::refreshUiFromFiles, 420);
        });

        return row;
    }

    private void setModeRadioVisual(String mode) {
        rbHyper.setChecked("hyper".equals(mode));
        rbBalanced.setChecked("balanced".equals(mode));
        rbCool.setChecked("cool".equals(mode));
    }

    private View buildDiagnosticsCard() {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackground(makeCardBg(ROUND_SINGLE, getColor(R.color.card_surface), false));
        card.setPadding(d(18), d(15), d(18), d(15));

        TextView header = new TextView(this);
        header.setText("150W 快充底层链路实时状态");
        header.setTextColor(getColor(R.color.text_primary));
        header.setTextSize(14.5f);
        header.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        card.addView(header, lpMarginBottom(10));

        Object[] r1 = addDiagRow(card, "ICharger V5 极速模式");
        dotIcharger = (View) r1[0];
        tvDiagIcharger = (TextView) r1[1];

        Object[] r2 = addDiagRow(card, "壳温桥接 (/proc/shell-temp)");
        dotShell = (View) r2[0];
        tvDiagShell = (TextView) r2[1];

        Object[] r3 = addDiagRow(card, "息屏快充信号 (notifyScreenStatus)");
        dotScreen = (View) r3[0];
        tvDiagScreen = (TextView) r3[1];

        Object[] r4 = addDiagRow(card, "原厂安全温控保护");
        dotThermal = (View) r4[0];
        tvDiagThermal = (TextView) r4[1];

        return card;
    }

    private Object[] addDiagRow(LinearLayout parent, String title) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, d(5), 0, d(5));

        View dot = new View(this);
        dot.setBackground(makePillBg(getColor(R.color.status_ok), 4));
        LinearLayout.LayoutParams dotLp = new LinearLayout.LayoutParams(d(8), d(8));
        dotLp.rightMargin = d(10);
        row.addView(dot, dotLp);

        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        TextView tvT = new TextView(this);
        tvT.setText(title);
        tvT.setTextColor(getColor(R.color.text_primary));
        tvT.setTextSize(13.5f);
        col.addView(tvT);

        TextView tvV = new TextView(this);
        tvV.setText("读取中...");
        tvV.setTextColor(getColor(R.color.text_secondary));
        tvV.setTextSize(12f);
        col.addView(tvV);

        row.addView(col, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        parent.addView(row, matchWrap());
        return new Object[]{dot, tvV};
    }

    private View buildIntervalCard() {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackground(makeCardBg(ROUND_TOP, getColor(R.color.card_surface), false));
        card.setPadding(d(18), d(15), d(18), d(15));

        TextView tvT = new TextView(this);
        tvT.setText("后台采样间隔（≥ 1 分钟）");
        tvT.setTextColor(getColor(R.color.text_primary));
        tvT.setTextSize(16f);
        card.addView(tvT);

        TextView tvS = new TextView(this);
        tvS.setText("仅在充电时按间隔自动采样，拔出充电器后零唤醒待机");
        tvS.setTextColor(getColor(R.color.text_secondary));
        tvS.setTextSize(13f);
        tvS.setPadding(0, d(3), 0, d(12));
        card.addView(tvS);

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        String[] labels = {"1 分钟", "2 分钟", "5 分钟", "10 分钟"};
        for (int i = 0; i < labels.length; i++) {
            final int sec = intervalValues[i];
            final int idx = i;
            TextView chip = createFilterChip(labels[i], i == 0);
            chip.setOnClickListener(v -> {
                updateChipGroupStyle(intervalChips, idx);
                ChargingStore.sendCommand(this, "set_interval " + sec);
                Toast.makeText(this, "采样间隔已设为 " + labels[idx], Toast.LENGTH_SHORT).show();
            });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
            if (i > 0) lp.leftMargin = d(6);
            row.addView(chip, lp);
            intervalChips.add(chip);
        }
        card.addView(row, matchWrap());
        return card;
    }

    private View buildActionRow(String title, String summary, int roundMode, boolean danger, View.OnClickListener click) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setBackground(makeCardBg(roundMode, getColor(R.color.card_surface), true));
        row.setPadding(d(18), d(15), d(18), d(15));
        row.setClickable(true);
        row.setFocusable(true);
        row.setOnClickListener(click);

        TextView tvT = new TextView(this);
        tvT.setText(title);
        tvT.setTextColor(getColor(danger ? R.color.danger_text : R.color.text_primary));
        tvT.setTextSize(16f);
        row.addView(tvT);

        TextView tvS = new TextView(this);
        tvS.setText(summary);
        tvS.setTextColor(getColor(R.color.text_secondary));
        tvS.setTextSize(13f);
        tvS.setPadding(0, d(3), 0, 0);
        row.addView(tvS);
        return row;
    }

    private void confirmClearHistory() {
        new AlertDialog.Builder(this)
                .setTitle("清空历史充电记录")
                .setMessage("确定要删除所有已保存的历史充电功率、时间与温度曲线吗？此操作不可撤销。")
                .setPositiveButton("清空", (dlg, which) -> {
                    selectedSessionId = null;
                    ChargingStore.sendCommand(this, "clear_history");
                    handler.postDelayed(this::refreshUiFromFiles, 380);
                    Toast.makeText(this, "已清空历史充电记录", Toast.LENGTH_SHORT).show();
                })
                .setNegativeButton("取消", null)
                .show();
    }

    private void refreshUiFromFiles() {
        ChargingStore.LiveState live = ChargingStore.loadLive(this);
        bindLiveState(live);

        sessions = ChargingStore.loadHistory(this);
        bindSessions();
    }

    private void bindLiveState(ChargingStore.LiveState s) {
        if (!s.wired) {
            tvLiveWatt.setText("未充电");
        } else {
            tvLiveWatt.setText(String.format(Locale.US, "%.1f W", s.powerMw / 1000f));
        }
        tvLiveProto.setText(s.protocol);

        // Update battery progress bar ratio
        LinearLayout track = (LinearLayout) barProgressFill.getParent();
        if (track != null && track.getChildCount() >= 2) {
            int soc = Math.max(0, Math.min(100, s.soc));
            ((LinearLayout.LayoutParams) barProgressFill.getLayoutParams()).weight = soc;
            ((LinearLayout.LayoutParams) track.getChildAt(1).getLayoutParams()).weight = 100 - soc;
            barProgressFill.setBackground(makePillBg(
                    getColor(s.wired ? R.color.bar_green : R.color.accent_primary), 10));
            track.requestLayout();
        }

        int dispMa = s.chgMa > 0 ? s.chgMa : Math.abs(s.ibatMa);
        String curLabel = s.chgMa > 0 ? ("充入 " + s.chgMa + " mA")
                : (s.wired && s.ibusMa > 0 ? ("USB 输入 " + s.ibusMa + " mA") : ("电流 " + dispMa + " mA"));
        tvBarCaption.setText(String.format(Locale.US, "双电芯 %.2f V (单芯 %.2f V) · %s",
                s.vpackMv / 1000f, s.vbatMv / 1000f, curLabel));

        tvTileSoc.setText(s.soc + "%");
        tvTileBattTemp.setText(String.format(Locale.US, "%.1f°C", s.battTempD1 / 10f));
        tvTileShellTemp.setText(String.format(Locale.US, "%.1f°C", s.shellTempD1 / 10f));
        tvTileVbus.setText(s.vbusMv > 0 ? String.format(Locale.US, "%.2fV", s.vbusMv / 1000f) : "--");

        if (s.soh > 0 || s.fcc > 0) {
            tvHealthFooter.setText(String.format(Locale.US,
                    "电池健康 SOH %d%% · 满充容量 %d / %d mAh · 循环 %d 次",
                    s.soh, s.fcc, s.designCap, s.cycleCount));
        } else {
            tvHealthFooter.setText("设备最大支持 150W SuperVOOC 双电芯闪充 (2S 5200mAh)");
        }

        setModeRadioVisual(s.chargeMode);

        // Sampling interval chips
        int idx = 0;
        for (int i = 0; i < intervalValues.length; i++) {
            if (intervalValues[i] == s.sampleInterval) {
                idx = i;
                break;
            }
        }
        updateChipGroupStyle(intervalChips, idx);

        // Hardware diagnostics
        if (!s.fromDaemon) {
            setDiag(dotIcharger, tvDiagIcharger, false, "正在等待后台服务同步...");
            setDiag(dotShell, tvDiagShell, false, "正在等待壳温桥接同步...");
            setDiag(dotScreen, tvDiagScreen, false, "正在等待状态同步...");
            setDiag(dotThermal, tvDiagThermal, true, "原厂硬件保护默认开启");
            return;
        }

        boolean hyperOk = (s.ichargerCustomMode == 3 && s.ichargerSmartMode == 0);
        if ("hyper".equals(s.chargeMode)) {
            setDiag(dotIcharger, tvDiagIcharger, hyperOk,
                    hyperOk ? "Hyper 150W 已激活 (mode=3) · BCC 限流已解除 (smart=0)"
                            : String.format(Locale.US, "mode=%d · smart=%d · bcc=%dmA", s.ichargerCustomMode, s.ichargerSmartMode, s.bccCurrent));
        } else if ("balanced".equals(s.chargeMode)) {
            setDiag(dotIcharger, tvDiagIcharger, true,
                    String.format(Locale.US, "原厂均衡模式 (mode=%d · smart=%d · BCC 寿命保护)", s.ichargerCustomMode, s.ichargerSmartMode));
        } else {
            setDiag(dotIcharger, tvDiagIcharger, true,
                    String.format(Locale.US, "低温护电池模式 (cool_down=%d · 约 40W 上限)", s.coolDown));
        }

        boolean shellOk = s.shellTempD1 > 100 && s.shellTempD1 < 650;
        setDiag(dotShell, tvDiagShell, shellOk,
                shellOk ? String.format(Locale.US, "正常桥接 · 壳温 %.1f°C（已修复无 horae 时 -127°C/-274°C 失效）", s.shellTempD1 / 10f)
                        : "异常 · 等待写入 /proc/shell-temp");

        setDiag(dotScreen, tvDiagScreen, true,
                (s.screenOn ? "已同步 · 当前亮屏" : "已同步 · 当前息屏 (150W 息屏温控线程激活)")
                        + String.format(Locale.US, " · cool_down=%d · mmi=%d", s.coolDown, s.mmiEn));

        setDiag(dotThermal, tvDiagThermal, true,
                "hyper".equals(s.chargeMode)
                        ? "原厂 Hyper 阶梯保护生效 (40.5°C→8A / 41.5°C→6A / 42.5°C→4A / 44°C→2A)"
                        : "原厂标准阶梯保护生效 (36.0°C→8A / 38.0°C→6A / 39.0°C→4A / 41°C→2A)");
    }

    private void setDiag(View dot, TextView tv, boolean ok, String text) {
        dot.setBackground(makePillBg(getColor(ok ? R.color.status_ok : R.color.status_warn), 4));
        tv.setText(text);
    }

    private void bindSessions() {
        sessionChipsRow.removeAllViews();
        if (sessions.isEmpty()) {
            TextView emptyChip = createFilterChip("暂无历史充电记录", false);
            sessionChipsRow.addView(emptyChip);
            tvStatPeak.setText("-- W");
            tvStatAvg.setText("-- W");
            tvStatMaxTemp.setText("-- °C");
            tvStatDur.setText("--");
            chartView.setData(null);
            return;
        }

        ChargingStore.ChargingSession active = sessions.get(0);
        if (selectedSessionId != null) {
            for (ChargingStore.ChargingSession cs : sessions) {
                if (selectedSessionId.equals(cs.id)) {
                    active = cs;
                    break;
                }
            }
        }
        selectedSessionId = active.id;

        String todayKey = dayKeyFmt.format(new Date());
        for (int i = 0; i < sessions.size(); i++) {
            final ChargingStore.ChargingSession cs = sessions.get(i);
            boolean isSel = cs.id.equals(selectedSessionId);
            Date startDate = new Date(cs.startTs * 1000L);
            String dateStr = todayKey.equals(dayKeyFmt.format(startDate))
                    ? todayFmt.format(startDate) : sessionFmt.format(startDate);
            String label = String.format(Locale.US, "%s · %d→%d%% · %.1fW",
                    dateStr, cs.startSoc, cs.endSoc, cs.peakMw / 1000f);

            TextView chip = new TextView(this);
            chip.setText(label);
            chip.setTextSize(12f);
            chip.setSingleLine(true);
            chip.setPadding(d(12), d(7), d(12), d(7));
            styleChip(chip, isSel);
            chip.setOnClickListener(v -> {
                selectedSessionId = cs.id;
                bindSessions();
            });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            if (i > 0) lp.leftMargin = d(8);
            sessionChipsRow.addView(chip, lp);
        }

        tvStatPeak.setText(String.format(Locale.US, "%.1f W", active.peakMw / 1000f));
        tvStatAvg.setText(String.format(Locale.US, "%.1f W", active.avgMw / 1000f));
        tvStatMaxTemp.setText(String.format(Locale.US, "%.1f°C", active.maxTempD1 / 10f));
        tvStatDur.setText(formatDuration(active.durationS, active.points.size()));
        chartView.setData(active.points);
    }

    private String formatDuration(long sec, int count) {
        if (sec < 60) {
            return count <= 1 ? "刚刚开始" : (sec + " 秒");
        }
        long mins = sec / 60;
        if (mins < 60) return mins + " 分钟";
        long h = mins / 60;
        long m = mins % 60;
        return String.format(Locale.US, "%d时%d分", h, m);
    }

    // --- Material 3 Expressive Rounded Drawable Helpers ---

    private android.graphics.drawable.Drawable makeCardBg(int roundMode, int fillColor, boolean ripple) {
        float big = 24f * dp;
        float small = 4f * dp;
        float tl = (roundMode == ROUND_SINGLE || roundMode == ROUND_TOP) ? big : small;
        float tr = tl;
        float bl = (roundMode == ROUND_SINGLE || roundMode == ROUND_BOTTOM) ? big : small;
        float br = bl;
        GradientDrawable gd = new GradientDrawable();
        gd.setColor(fillColor);
        gd.setCornerRadii(new float[]{tl, tl, tr, tr, br, br, bl, bl});
        if (!ripple) return gd;
        int rippleColor = Color.argb(38, 255, 255, 255);
        return new RippleDrawable(ColorStateList.valueOf(rippleColor), gd, gd);
    }

    private GradientDrawable makePillBg(int fillColor, int radiusDp) {
        GradientDrawable gd = new GradientDrawable();
        gd.setColor(fillColor);
        gd.setCornerRadius(radiusDp * dp);
        return gd;
    }

    private android.graphics.drawable.Drawable makeCircleRipple(int fillColor) {
        GradientDrawable gd = new GradientDrawable();
        gd.setShape(GradientDrawable.OVAL);
        gd.setColor(fillColor);
        int rippleColor = Color.argb(45, 255, 255, 255);
        return new RippleDrawable(ColorStateList.valueOf(rippleColor), gd, gd);
    }

    private int d(int v) {
        return Math.round(v * dp);
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
    }

    private LinearLayout.LayoutParams lpMarginBottom(int mbDp) {
        LinearLayout.LayoutParams lp = matchWrap();
        lp.bottomMargin = d(mbDp);
        return lp;
    }
}
