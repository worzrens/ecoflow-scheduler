package com.ecoflowscheduler.widget;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.DashPathEffect;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.Typeface;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/**
 * The widget's graphs, midnight to midnight. draw(): one row per day - the thick bar is what really happened
 * (green = electricity, red = none, grey = no data), the thin bar under it the planned schedule. drawDay(): one day
 * top to bottom, with the planned outages as dashed outlines over what really happened.
 */
final class Chart {
    private static final int GREEN = Color.rgb(0x2e, 0xe6, 0x8a), RED = Color.rgb(0xe5, 0x53, 0x4b),
            ORANGE = Color.rgb(0xf5, 0x9e, 0x0b), EMPTY = Color.rgb(0x2a, 0x2e, 0x36),
            TEXT = Color.rgb(0xe8, 0xea, 0xed), MUTED = Color.rgb(0x8b, 0x93, 0xa1);

    static final class Day {
        long start, end;
        List<Segments.Seg> real = new ArrayList<>(), planned = new ArrayList<>();
    }

    static final class Model {
        final List<Day> days = new ArrayList<>();
        double realOutage, plannedOutage, estimated;
        boolean hasSchedule, hasTomorrow;
    }

    private Chart() {
    }

    static long midnight(long nowSec, int offsetDays) {
        Calendar c = Calendar.getInstance();
        c.setTimeInMillis(nowSec * 1000);
        c.set(Calendar.HOUR_OF_DAY, 0);
        c.set(Calendar.MINUTE, 0);
        c.set(Calendar.SECOND, 0);
        c.set(Calendar.MILLISECOND, 0);
        c.add(Calendar.DAY_OF_MONTH, offsetDays);
        return c.getTimeInMillis() / 1000;
    }

    /** The last `n` days including today, plus tomorrow when its schedule is already published. */
    static Model model(Repo.Data data, int n, long now) {
        Model m = new Model();
        long first = midnight(now, 1 - n);
        List<Segments.Seg> real = Segments.real(data.rows, first, midnight(now, 1), now);
        for (int k = 0; k <= n; k++) {
            Day d = new Day();
            d.start = midnight(now, 1 - n + k);
            d.end = midnight(now, 2 - n + k);
            for (java.util.Map.Entry<Long, String> e : data.schedule.entrySet()) {
                if (e.getKey() + 43200 >= d.start && e.getKey() + 43200 < d.end) {
                    d.planned = Segments.scheduleDay(e.getKey(), e.getValue());
                }
            }
            boolean tomorrow = k == n;
            if (tomorrow && d.planned.isEmpty()) break;
            if (!tomorrow) {
                d.real = Segments.slice(real, d.start, d.end);
                m.realOutage += Segments.secondsOf(d.real, Segments.OUTAGE);
                m.plannedOutage += Segments.secondsOf(d.planned, Segments.OUTAGE);
                for (Segments.Seg s : d.real) {
                    if (s.kind != Segments.OUTAGE) continue;
                    for (double[] x : s.est) m.estimated += x[1] - x[0];
                }
            } else {
                m.hasTomorrow = true;
            }
            m.hasSchedule |= !d.planned.isEmpty();
            m.days.add(d);
        }
        return m;
    }

    static String duration(double seconds) {
        long min = Math.round(seconds / 60);
        return min >= 60 ? String.format(Locale.ROOT, "%dh %02dm", min / 60, min % 60) : min + "m";
    }

    private static String clock(double ts) {
        return new SimpleDateFormat("HH:mm", Locale.ROOT).format(new Date((long) ts * 1000));
    }

    private static String clockEnd(double end, Day d) {
        return end >= d.end - 1 ? "24:00" : clock(end);
    }

    static Bitmap drawDay(Day d, int width, int height, float density, long now) {
        Bitmap bmp = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        Canvas c = new Canvas(bmp);
        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        Typeface bold = Typeface.create(Typeface.DEFAULT, Typeface.BOLD);
        float gutter = 32 * density, top = 6 * density, h = height - 12 * density;
        float gx = gutter, gw = width - gutter;
        double span = d.end - d.start;

        int step = h >= 200 * density ? 3 : 6;
        p.setTextSize(9 * density);
        p.setTextAlign(Paint.Align.RIGHT);
        for (int hour = 0; hour <= 24; hour += step) {
            float y = top + h * hour / 24f;
            p.setColor(Color.rgb(0x26, 0x2a, 0x31));
            c.drawRect(gx, y, width, y + Math.max(1, density * 0.7f), p);
            p.setColor(MUTED);
            c.drawText(String.format(Locale.ROOT, "%02d:00", hour), gutter - 4 * density, y + 3.2f * density, p);
        }

        p.setTextAlign(Paint.Align.LEFT);
        for (Segments.Seg s : d.real) {
            float y0 = top + (float) ((s.start - d.start) / span) * h + density;
            float y1 = top + (float) ((s.end - d.start) / span) * h - density;
            RectF b = new RectF(gx + 3 * density, y0, width - 3 * density, Math.max(y1, y0 + 2 * density));
            float radius = Math.min(6 * density, b.height() / 2);
            p.setStyle(Paint.Style.FILL);
            p.setColor(s.kind == Segments.GRID ? GREEN : (s.kind == Segments.OUTAGE ? Color.rgb(0x3a, 0x1f, 0x23) : EMPTY));
            c.drawRoundRect(b, radius, radius, p);
            if (s.kind == Segments.OUTAGE) {
                p.setStyle(Paint.Style.STROKE);
                p.setStrokeWidth(1.2f * density);
                p.setColor(Color.rgb(0xb4, 0x49, 0x4f));
                c.drawRoundRect(b, radius, radius, p);
                p.setStyle(Paint.Style.FILL);
            }
            String name = s.kind == Segments.GRID ? "Electricity" : (s.kind == Segments.OUTAGE ? "No electricity" : "No data");
            int ink = s.kind == Segments.GRID ? Color.rgb(0x06, 0x26, 0x0f)
                    : (s.kind == Segments.OUTAGE ? Color.rgb(0xf8, 0x71, 0x71) : MUTED);
            String times = clock(s.start) + "–" + clockEnd(s.end, d);
            c.save();
            c.clipRect(b);
            p.setColor(ink);
            float x = b.left + 7 * density;
            if (b.height() >= 28 * density) {
                p.setTypeface(bold);
                p.setTextSize(11 * density);
                c.drawText(name + "  ·  " + duration(s.seconds()), x, b.top + 12.5f * density, p);
                p.setTypeface(Typeface.DEFAULT);
                p.setTextSize(9 * density);
                String battery = "";
                if (s.kind != Segments.NODATA && !Double.isNaN(s.socStart) && !Double.isNaN(s.socEnd)) {
                    battery = "   " + (s.est.isEmpty() ? "" : "~") + Math.round(s.socStart) + "→" + Math.round(s.socEnd) + "%";
                }
                c.drawText(times + battery, x, b.top + 24 * density, p);
            } else if (b.height() >= 12 * density) {
                p.setTypeface(bold);
                p.setTextSize(9 * density);
                c.drawText(name + "  " + times, x, b.centerY() + 3.2f * density, p);
                p.setTypeface(Typeface.DEFAULT);
            }
            c.restore();
        }

        for (Segments.Seg s : d.planned) {
            if (s.kind != Segments.OUTAGE && s.kind != Segments.MAYBE) continue;
            RectF q = new RectF(gx + density, top + (float) ((s.start - d.start) / span) * h,
                    width - density, top + (float) ((s.end - d.start) / span) * h);
            boolean sure = s.kind == Segments.OUTAGE;
            p.setStyle(Paint.Style.STROKE);
            p.setStrokeWidth(1.7f * density);
            p.setColor(ORANGE);
            p.setPathEffect(new DashPathEffect(sure ? new float[]{6 * density, 4 * density}
                    : new float[]{2 * density, 4 * density}, 0));
            c.drawRoundRect(q, 7 * density, 7 * density, p);
            p.setPathEffect(null);
            p.setStyle(Paint.Style.FILL);
            if (q.height() >= 28 * density) {            // enough room not to cover the block's own text
                String tag = (sure ? "planned " : "possible ") + clock(s.start) + "–" + clockEnd(s.end, d);
                p.setTypeface(bold);
                p.setTextSize(8 * density);
                float tw = p.measureText(tag) + 10 * density;
                RectF chip = new RectF(q.right - tw - 5 * density, q.bottom - 14 * density,
                        q.right - 5 * density, q.bottom - 2 * density);
                p.setColor(Color.rgb(0x3b, 0x2c, 0x10));
                c.drawRoundRect(chip, 5 * density, 5 * density, p);
                p.setColor(ORANGE);
                c.drawText(tag, chip.left + 5 * density, chip.bottom - 3.2f * density, p);
                p.setTypeface(Typeface.DEFAULT);
            }
        }

        if (now >= d.start && now < d.end) {
            float y = top + (float) ((now - d.start) / span) * h;
            p.setColor(Color.WHITE);
            c.drawRect(gx - 2 * density, y - 0.7f * density, width, y + 0.7f * density, p);
            c.drawCircle(gx - density, y, 3 * density, p);
        }
        return bmp;
    }

    static Bitmap draw(Model m, int width, int height, float density, long now) {
        Bitmap bmp = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        Canvas c = new Canvas(bmp);
        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        int rows = Math.max(1, m.days.size());
        float axis = 13 * density;
        float rowH = (height - axis) / rows;
        float text = Math.max(7 * density, Math.min(11 * density, rowH * 0.42f));
        p.setTextSize(text);
        float left = p.measureText("Wed 30 ") + 2 * density;
        float right = p.measureText(" 24h 00m") + 2 * density;
        float barW = Math.max(10, width - left - right);

        p.setColor(MUTED);
        p.setTextSize(9 * density);
        for (int h = 0; h <= 24; h += 6) {
            float x = left + barW * h / 24f;
            p.setTextAlign(h == 0 ? Paint.Align.LEFT : (h == 24 ? Paint.Align.RIGHT : Paint.Align.CENTER));
            c.drawText(String.format(Locale.ROOT, "%02d", h), x, 9 * density, p);
        }
        SimpleDateFormat label = new SimpleDateFormat("EEE d", Locale.ENGLISH);
        for (int i = 0; i < m.days.size(); i++) {
            Day d = m.days.get(i);
            float top = axis + i * rowH;
            float gap = Math.max(1.5f * density, rowH * 0.12f);
            float usable = rowH - gap;
            float realH = Math.min(26 * density, usable * (m.hasSchedule ? 0.66f : 1f));
            float planH = m.hasSchedule ? Math.min(9 * density, usable * 0.26f) : 0;
            float y = top + (rowH - realH - planH - (m.hasSchedule ? usable * 0.08f : 0)) / 2;
            boolean future = d.start > now;
            bar(c, p, d, d.real, left, y, barW, realH, density, false);
            if (m.hasSchedule) {
                bar(c, p, d, d.planned, left, y + realH + usable * 0.08f, barW, planH, density, true);
            }
            if (now >= d.start && now < d.end) {
                float x = left + barW * (now - d.start) / (float) (d.end - d.start);
                p.setColor(TEXT);
                c.drawRect(x - density, y - density, x + density, y + realH + planH + usable * 0.08f + density, p);
            }
            p.setTextSize(text);
            p.setTextAlign(Paint.Align.LEFT);
            p.setColor(future ? MUTED : TEXT);
            float baseline = y + realH / 2 + text * 0.35f;
            c.drawText(label.format(new Date(d.start * 1000)), 0, baseline, p);
            p.setTextAlign(Paint.Align.RIGHT);
            double off = Segments.secondsOf(future ? d.planned : d.real, Segments.OUTAGE);
            p.setColor(future ? ORANGE : (off > 0 ? RED : MUTED));
            c.drawText(off > 0 ? duration(off) : "0", width, baseline, p);
        }
        return bmp;
    }

    private static void bar(Canvas c, Paint p, Day d, List<Segments.Seg> segs, float x, float y, float w, float h,
                            float density, boolean planned) {
        RectF all = new RectF(x, y, x + w, y + h);
        float radius = Math.min(4 * density, h / 2);
        Path clip = new Path();
        clip.addRoundRect(all, radius, radius, Path.Direction.CW);
        c.save();
        c.clipPath(clip);
        p.setColor(EMPTY);
        c.drawRect(all, p);
        for (Segments.Seg s : segs) {
            int color;
            if (planned) {
                if (s.kind == Segments.OUTAGE) color = ORANGE;
                else if (s.kind == Segments.MAYBE) color = Color.argb(110, 0xf5, 0x9e, 0x0b);
                else continue;
            } else {
                if (s.kind == Segments.NODATA) continue;
                color = s.kind == Segments.GRID ? GREEN : RED;
            }
            p.setColor(color);
            float a = x + w * (float) ((s.start - d.start) / (d.end - d.start));
            float b = x + w * (float) ((s.end - d.start) / (d.end - d.start));
            c.drawRect(a, y, Math.max(b, a + 1), y + h, p);
        }
        c.restore();
    }
}
