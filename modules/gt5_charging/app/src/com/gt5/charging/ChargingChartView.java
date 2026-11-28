package com.gt5.charging;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.DashPathEffect;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.Shader;
import android.view.MotionEvent;
import android.view.View;

import java.text.SimpleDateFormat;
import java.util.Collections;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/**
 * High-DPI Material You dual-axis interactive charging chart:
 * - Primary Left Y-Axis: Charging Power (W) with smooth curve + gradient fill
 * - Secondary Right Y-Axis: Battery Temperature (C) with smooth warm curve
 * - Optional Overlay: Battery SOC (%) dotted green curve
 * - X-Axis: Time (HH:mm) with interactive touch scrubbing tooltip
 */
public class ChargingChartView extends View {

    public static final int DISPLAY_BOTH = 0;
    public static final int DISPLAY_POWER = 1;
    public static final int DISPLAY_TEMP = 2;
    public static final int DISPLAY_ALL = 3;

    private List<ChargingStore.SamplePoint> points = Collections.emptyList();
    private int displayMode = DISPLAY_BOTH;
    private int selectedIndex = -1;

    private final float dp;
    private final float sp;

    private final Paint gridPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint axisTextLeftPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint axisTextRightPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint axisTextBottomPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint emptyTextPaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    private final Paint powerLinePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint powerFillPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint tempLinePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint socLinePaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    private final Paint scrubLinePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint dotFillPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint dotHaloPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint tooltipBgPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint tooltipTextPaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    private final Path linePath = new Path();
    private final Path fillPath = new Path();
    private final RectF tooltipRect = new RectF();
    private final SimpleDateFormat timeFmt = new SimpleDateFormat("HH:mm", Locale.getDefault());
    private final SimpleDateFormat timeSecFmt = new SimpleDateFormat("HH:mm:ss", Locale.getDefault());

    private float downX, downY;
    private boolean scrubbing = false;

    private int colorPower;
    private int colorTemp;
    private int colorSoc;
    private int colorTextSecondary;
    private int colorDivider;
    private int colorTooltipBg;
    private int colorTooltipText;

    private float plotLeft, plotTop, plotRight, plotBottom;

    public ChargingChartView(Context ctx) {
        super(ctx);
        dp = ctx.getResources().getDisplayMetrics().density;
        sp = ctx.getResources().getDisplayMetrics().scaledDensity;

        colorPower = ctx.getColor(R.color.accent_primary);
        colorTemp = ctx.getColor(R.color.temp_color);
        colorSoc = ctx.getColor(R.color.soc_color);
        colorTextSecondary = ctx.getColor(R.color.text_secondary);
        colorDivider = ctx.getColor(R.color.divider_subtle);
        colorTooltipBg = ctx.getColor(R.color.card_surface_variant);
        colorTooltipText = ctx.getColor(R.color.text_primary);

        gridPaint.setStyle(Paint.Style.STROKE);
        gridPaint.setStrokeWidth(1f * dp);
        gridPaint.setColor(colorDivider);
        gridPaint.setPathEffect(new DashPathEffect(new float[]{4f * dp, 4f * dp}, 0));

        axisTextLeftPaint.setColor(colorPower);
        axisTextLeftPaint.setTextSize(10.5f * sp);
        axisTextLeftPaint.setTextAlign(Paint.Align.RIGHT);

        axisTextRightPaint.setColor(colorTemp);
        axisTextRightPaint.setTextSize(10.5f * sp);
        axisTextRightPaint.setTextAlign(Paint.Align.LEFT);

        axisTextBottomPaint.setColor(colorTextSecondary);
        axisTextBottomPaint.setTextSize(10.5f * sp);
        axisTextBottomPaint.setTextAlign(Paint.Align.CENTER);

        emptyTextPaint.setColor(colorTextSecondary);
        emptyTextPaint.setTextSize(13f * sp);
        emptyTextPaint.setTextAlign(Paint.Align.CENTER);

        powerLinePaint.setStyle(Paint.Style.STROKE);
        powerLinePaint.setStrokeWidth(2.6f * dp);
        powerLinePaint.setStrokeCap(Paint.Cap.ROUND);
        powerLinePaint.setStrokeJoin(Paint.Join.ROUND);
        powerLinePaint.setColor(colorPower);

        powerFillPaint.setStyle(Paint.Style.FILL);

        tempLinePaint.setStyle(Paint.Style.STROKE);
        tempLinePaint.setStrokeWidth(2.2f * dp);
        tempLinePaint.setStrokeCap(Paint.Cap.ROUND);
        tempLinePaint.setStrokeJoin(Paint.Join.ROUND);
        tempLinePaint.setColor(colorTemp);

        socLinePaint.setStyle(Paint.Style.STROKE);
        socLinePaint.setStrokeWidth(1.8f * dp);
        socLinePaint.setStrokeCap(Paint.Cap.ROUND);
        socLinePaint.setColor(colorSoc);
        socLinePaint.setPathEffect(new DashPathEffect(new float[]{5f * dp, 4f * dp}, 0));

        scrubLinePaint.setStyle(Paint.Style.STROKE);
        scrubLinePaint.setStrokeWidth(1.2f * dp);
        scrubLinePaint.setColor(colorTextSecondary);
        scrubLinePaint.setPathEffect(new DashPathEffect(new float[]{3f * dp, 3f * dp}, 0));

        dotFillPaint.setStyle(Paint.Style.FILL);
        dotHaloPaint.setStyle(Paint.Style.FILL);

        tooltipBgPaint.setStyle(Paint.Style.FILL);
        tooltipBgPaint.setColor(colorTooltipBg);

        tooltipTextPaint.setColor(colorTooltipText);
        tooltipTextPaint.setTextSize(11.5f * sp);
        tooltipTextPaint.setTextAlign(Paint.Align.CENTER);
    }

    public void setData(List<ChargingStore.SamplePoint> pts) {
        this.points = (pts != null) ? pts : Collections.emptyList();
        if (selectedIndex >= this.points.size()) {
            selectedIndex = -1;
        }
        invalidate();
    }

    public void setDisplayMode(int mode) {
        this.displayMode = mode;
        invalidate();
    }

    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        int desiredH = Math.round(256f * dp);
        int h = resolveSize(desiredH, heightMeasureSpec);
        int w = MeasureSpec.getSize(widthMeasureSpec);
        setMeasuredDimension(w, h);
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        if (points == null || points.isEmpty()) return super.onTouchEvent(event);
        int action = event.getActionMasked();
        if (action == MotionEvent.ACTION_DOWN) {
            downX = event.getX();
            downY = event.getY();
            scrubbing = false;
            return true;
        } else if (action == MotionEvent.ACTION_MOVE) {
            float dx = Math.abs(event.getX() - downX);
            float dy = Math.abs(event.getY() - downY);
            if (!scrubbing) {
                if (dy > 10f * dp && dy > dx * 1.2f) {
                    // Vertical scroll: yield cleanly to parent ScrollView
                    if (getParent() != null) getParent().requestDisallowInterceptTouchEvent(false);
                    return false;
                }
                if (dx > 6f * dp) {
                    scrubbing = true;
                    if (getParent() != null) getParent().requestDisallowInterceptTouchEvent(true);
                }
            }
            if (scrubbing) {
                updateSelectedIndex(event.getX());
            }
            return true;
        } else if (action == MotionEvent.ACTION_UP) {
            if (!scrubbing && Math.abs(event.getY() - downY) < 12f * dp) {
                // Single tap on chart selects the nearest point
                updateSelectedIndex(event.getX());
            }
            scrubbing = false;
            if (getParent() != null) getParent().requestDisallowInterceptTouchEvent(false);
            return true;
        } else if (action == MotionEvent.ACTION_CANCEL) {
            scrubbing = false;
            if (getParent() != null) getParent().requestDisallowInterceptTouchEvent(false);
            return true;
        }
        return super.onTouchEvent(event);
    }

    private void updateSelectedIndex(float touchX) {
        int n = points.size();
        if (n == 1) {
            selectedIndex = 0;
            invalidate();
            return;
        }
        float clamped = Math.max(plotLeft, Math.min(plotRight, touchX));
        long minTs = points.get(0).ts;
        long maxTs = points.get(n - 1).ts;
        float span = Math.max(1f, plotRight - plotLeft);
        int best = 0;
        float bestDist = Float.MAX_VALUE;
        for (int i = 0; i < n; i++) {
            float x = pointX(i, n, minTs, maxTs, span);
            float d = Math.abs(x - clamped);
            if (d < bestDist) {
                bestDist = d;
                best = i;
            }
        }
        if (best != selectedIndex) {
            selectedIndex = best;
            invalidate();
        }
    }

    private float pointX(int i, int n, long minTs, long maxTs, float span) {
        if (n <= 1) return plotLeft + span * 0.5f;
        if (maxTs > minTs) {
            return plotLeft + span * ((points.get(i).ts - minTs) / (float) (maxTs - minTs));
        }
        return plotLeft + span * (i / (float) (n - 1));
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        int w = getWidth();
        int h = getHeight();
        if (w <= 0 || h <= 0) return;

        boolean showPower = displayMode == DISPLAY_BOTH || displayMode == DISPLAY_POWER || displayMode == DISPLAY_ALL;
        boolean showTemp = displayMode == DISPLAY_BOTH || displayMode == DISPLAY_TEMP || displayMode == DISPLAY_ALL;
        boolean showSoc = displayMode == DISPLAY_ALL;

        plotLeft = showPower ? 44f * dp : 16f * dp;
        plotRight = showTemp ? (w - 44f * dp) : (w - 16f * dp);
        plotTop = 40f * dp;
        plotBottom = h - 30f * dp;
        float plotW = Math.max(1f, plotRight - plotLeft);
        float plotH = Math.max(1f, plotBottom - plotTop);

        if (points == null || points.isEmpty()) {
            // Subtle placeholder grid + centered hint
            drawHorizontalGrid(canvas, 3, plotW, plotH);
            canvas.drawText("插上充电器后将按设定间隔记录功率与温度曲线", w * 0.5f, plotTop + plotH * 0.48f, emptyTextPaint);
            canvas.drawText("也可以点击下方「立即采样一次」记录当前状态", w * 0.5f, plotTop + plotH * 0.62f, emptyTextPaint);
            return;
        }

        int n = points.size();
        float maxW = 0f;
        float minT = 100f;
        float maxT = 0f;
        for (int i = 0; i < n; i++) {
            ChargingStore.SamplePoint p = points.get(i);
            float pw = p.powerW();
            float tc = p.battTempC();
            if (pw > maxW) maxW = pw;
            if (tc < minT) minT = tc;
            if (tc > maxT) maxT = tc;
        }

        // Clean auto-scaled ceiling for Power (W)
        float powerMax;
        if (maxW <= 8f) powerMax = 10f;
        else if (maxW <= 18f) powerMax = 20f;
        else if (maxW <= 36f) powerMax = 40f;
        else if (maxW <= 72f) powerMax = 80f;
        else if (maxW <= 110f) powerMax = 120f;
        else powerMax = 160f;

        // Clean auto-scaled window for Temperature (C)
        float tempMin = (float) (Math.floor((minT - 3f) / 5.0) * 5.0);
        float tempMax = (float) (Math.ceil((maxT + 4f) / 5.0) * 5.0);
        if (tempMin < 10f) tempMin = 10f;
        if (tempMax - tempMin < 15f) tempMax = tempMin + 15f;

        // 1. Grid + Y-axis labels
        int steps = 4;
        for (int s = 0; s <= steps; s++) {
            float frac = s / (float) steps;
            float y = plotBottom - frac * plotH;
            canvas.drawLine(plotLeft, y, plotRight, y, gridPaint);

            if (showPower) {
                float valW = powerMax * frac;
                String lbl = (powerMax <= 10f && s % 2 == 1)
                        ? String.format(Locale.US, "%.1fW", valW)
                        : String.format(Locale.US, "%.0fW", valW);
                canvas.drawText(lbl, plotLeft - 6f * dp, y + 3.5f * sp, axisTextLeftPaint);
            }
            if (showTemp) {
                float valT = tempMin + (tempMax - tempMin) * frac;
                String lbl = String.format(Locale.US, "%.0f°", valT);
                canvas.drawText(lbl, plotRight + 6f * dp, y + 3.5f * sp, axisTextRightPaint);
            }
        }

        long minTs = points.get(0).ts;
        long maxTs = points.get(n - 1).ts;

        // 2. X-axis time labels (use HH:mm:ss for short <3m sessions, HH:mm otherwise)
        SimpleDateFormat xFmt = (maxTs - minTs < 180) ? timeSecFmt : timeFmt;
        if (n == 1) {
            String t = xFmt.format(new Date(minTs * 1000L));
            canvas.drawText(t, plotLeft + plotW * 0.5f, h - 8f * dp, axisTextBottomPaint);
        } else {
            int labelCount = Math.min(4, n);
            for (int k = 0; k < labelCount; k++) {
                float frac = k / (float) (labelCount - 1);
                float x = plotLeft + frac * plotW;
                long ts = (maxTs > minTs)
                        ? (minTs + (long) ((maxTs - minTs) * frac))
                        : points.get((int) Math.round(frac * (n - 1))).ts;
                String t = xFmt.format(new Date(ts * 1000L));
                if (k == 0) axisTextBottomPaint.setTextAlign(Paint.Align.LEFT);
                else if (k == labelCount - 1) axisTextBottomPaint.setTextAlign(Paint.Align.RIGHT);
                else axisTextBottomPaint.setTextAlign(Paint.Align.CENTER);
                canvas.drawText(t, x, h - 8f * dp, axisTextBottomPaint);
            }
            axisTextBottomPaint.setTextAlign(Paint.Align.CENTER);
        }

        // Precompute coordinates
        float[] xs = new float[n];
        float[] yPower = new float[n];
        float[] yTemp = new float[n];
        float[] ySoc = new float[n];
        for (int i = 0; i < n; i++) {
            ChargingStore.SamplePoint p = points.get(i);
            xs[i] = pointX(i, n, minTs, maxTs, plotW);
            float pf = Math.max(0f, Math.min(1f, p.powerW() / powerMax));
            float tf = Math.max(0f, Math.min(1f, (p.battTempC() - tempMin) / (tempMax - tempMin)));
            float sf = Math.max(0f, Math.min(1f, p.soc / 100f));
            yPower[i] = plotBottom - pf * plotH;
            yTemp[i] = plotBottom - tf * plotH;
            ySoc[i] = plotBottom - sf * plotH;
        }

        // 3. Draw SOC overlay (subtle dotted green line underneath)
        if (showSoc && n >= 2) {
            buildSmoothPath(linePath, xs, ySoc, n, plotTop, plotBottom);
            canvas.drawPath(linePath, socLinePaint);
        }

        // 4. Draw Power curve + gradient fill
        if (showPower) {
            if (n >= 2) {
                buildSmoothPath(linePath, xs, yPower, n, plotTop, plotBottom);
                fillPath.reset();
                fillPath.addPath(linePath);
                fillPath.lineTo(xs[n - 1], plotBottom);
                fillPath.lineTo(xs[0], plotBottom);
                fillPath.close();

                int topAlpha = Color.argb(82, Color.red(colorPower), Color.green(colorPower), Color.blue(colorPower));
                int botAlpha = Color.argb(4, Color.red(colorPower), Color.green(colorPower), Color.blue(colorPower));
                powerFillPaint.setShader(new LinearGradient(0, plotTop, 0, plotBottom, topAlpha, botAlpha, Shader.TileMode.CLAMP));
                canvas.drawPath(fillPath, powerFillPaint);
                canvas.drawPath(linePath, powerLinePaint);
            } else {
                drawHighlightDot(canvas, xs[0], yPower[0], colorPower);
            }
        }

        // 5. Draw Temperature curve
        if (showTemp) {
            if (n >= 2) {
                buildSmoothPath(linePath, xs, yTemp, n, plotTop, plotBottom);
                canvas.drawPath(linePath, tempLinePaint);
            } else {
                drawHighlightDot(canvas, xs[0], yTemp[0], colorTemp);
            }
        }

        // 6. Active scrub selection (or default latest point badge if n == 1)
        int activeIdx = selectedIndex;
        if (activeIdx < 0 && n == 1) {
            activeIdx = 0;
        }
        if (activeIdx >= 0 && activeIdx < n) {
            float sx = xs[activeIdx];
            canvas.drawLine(sx, plotTop, sx, plotBottom, scrubLinePaint);
            if (showPower) drawHighlightDot(canvas, sx, yPower[activeIdx], colorPower);
            if (showTemp) drawHighlightDot(canvas, sx, yTemp[activeIdx], colorTemp);
            if (showSoc) drawHighlightDot(canvas, sx, ySoc[activeIdx], colorSoc);

            ChargingStore.SamplePoint p = points.get(activeIdx);
            String tip = String.format(Locale.US, "%s  ·  %.1fW  ·  %.1f°C  ·  %d%%",
                    timeFmt.format(new Date(p.ts * 1000L)), p.powerW(), p.battTempC(), p.soc);
            drawTooltip(canvas, tip, sx, w);
        } else {
            // Draw compact legend pill at top
            String hint = "滑动图表查看各时间点功率与温度";
            drawLegendHeader(canvas, showPower, showTemp, showSoc, hint, w);
        }
    }

    private void drawHorizontalGrid(Canvas canvas, int steps, float plotW, float plotH) {
        for (int s = 0; s <= steps; s++) {
            float y = plotBottom - (s / (float) steps) * plotH;
            canvas.drawLine(plotLeft, y, plotLeft + plotW, y, gridPaint);
        }
    }

    private void buildSmoothPath(Path path, float[] xs, float[] ys, int n, float minY, float maxY) {
        path.reset();
        path.moveTo(xs[0], ys[0]);
        for (int i = 0; i < n - 1; i++) {
            float x0 = xs[i];
            float y0 = ys[i];
            float x1 = xs[i + 1];
            float y1 = ys[i + 1];
            float cx = (x0 + x1) * 0.5f;
            float cy0 = Math.max(minY, Math.min(maxY, y0));
            float cy1 = Math.max(minY, Math.min(maxY, y1));
            path.cubicTo(cx, cy0, cx, cy1, x1, cy1);
        }
    }

    private void drawHighlightDot(Canvas canvas, float cx, float cy, int color) {
        dotHaloPaint.setColor(Color.argb(65, Color.red(color), Color.green(color), Color.blue(color)));
        canvas.drawCircle(cx, cy, 8f * dp, dotHaloPaint);
        dotFillPaint.setColor(color);
        canvas.drawCircle(cx, cy, 4f * dp, dotFillPaint);
    }

    private void drawTooltip(Canvas canvas, String text, float anchorX, int viewW) {
        float textW = tooltipTextPaint.measureText(text);
        float padH = 12f * dp;
        float boxW = textW + padH * 2f;
        float boxH = 26f * dp;
        float left = anchorX - boxW * 0.5f;
        if (left < 8f * dp) left = 8f * dp;
        if (left + boxW > viewW - 8f * dp) left = viewW - 8f * dp - boxW;
        float top = 6f * dp;
        tooltipRect.set(left, top, left + boxW, top + boxH);
        canvas.drawRoundRect(tooltipRect, 13f * dp, 13f * dp, tooltipBgPaint);
        Paint.FontMetrics fm = tooltipTextPaint.getFontMetrics();
        float textY = tooltipRect.centerY() - (fm.ascent + fm.descent) * 0.5f;
        canvas.drawText(text, tooltipRect.centerX(), textY, tooltipTextPaint);
    }

    private void drawLegendHeader(Canvas canvas, boolean showPower, boolean showTemp, boolean showSoc, String hint, int viewW) {
        float x = plotLeft;
        float y = 18f * dp;
        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        p.setTextSize(11f * sp);
        if (showPower) {
            dotFillPaint.setColor(colorPower);
            canvas.drawCircle(x + 4f * dp, y - 3.5f * dp, 3.5f * dp, dotFillPaint);
            p.setColor(colorTextSecondary);
            canvas.drawText("功率(W)", x + 11f * dp, y, p);
            x += 58f * dp;
        }
        if (showTemp) {
            dotFillPaint.setColor(colorTemp);
            canvas.drawCircle(x + 4f * dp, y - 3.5f * dp, 3.5f * dp, dotFillPaint);
            p.setColor(colorTextSecondary);
            canvas.drawText("温度(°C)", x + 11f * dp, y, p);
            x += 62f * dp;
        }
        if (showSoc) {
            dotFillPaint.setColor(colorSoc);
            canvas.drawCircle(x + 4f * dp, y - 3.5f * dp, 3.5f * dp, dotFillPaint);
            p.setColor(colorTextSecondary);
            canvas.drawText("电量(%)", x + 11f * dp, y, p);
        }
        p.setTextAlign(Paint.Align.RIGHT);
        p.setColor(colorTextSecondary);
        p.setTextSize(10.5f * sp);
        canvas.drawText(hint, viewW - 12f * dp, y, p);
    }
}
