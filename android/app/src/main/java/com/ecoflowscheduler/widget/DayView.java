package com.ecoflowscheduler.widget;

import android.appwidget.AppWidgetManager;
import android.content.Context;
import android.os.Bundle;

/**
 * Size of the widget's vertical day (1d / 3d). The day is cut into 3 hour slices shown in a list: a slice is never
 * lower than MIN_SLICE_DP, so on a short widget the day scrolls instead of being squeezed; on a tall one the slices
 * stretch and the whole day fits.
 */
final class DayView {
    static final int SLICES = 8;                  // 8 x 3 h
    static final int MIN_SLICE_DP = 60;           // 20 dp per hour
    static final int PAD_DP = 6;                  // above 00:00 and below 24:00, for the labels
    private static final int MAX_SLICE_BYTES = 600_000;   // each list item crosses processes on its own (1 MB limit)

    final int widthPx, slicePx;
    final float density;                          // of the picture; below the screen's if a slice had to be scaled down

    private DayView(int widthPx, int slicePx, float density) {
        this.widthPx = widthPx;
        this.slicePx = slicePx;
        this.density = density;
    }

    static DayView of(Context ctx, int widgetId, boolean browse) {
        Bundle o = AppWidgetManager.getInstance(ctx).getAppWidgetOptions(widgetId);
        int widthDp = o.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 320);
        int heightDp = o.getInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT, 340);
        // minus padding, header, summary, footer (and the arrows and dots of the 3 day view)
        float listWidth = Math.max(120, widthDp - 24 - (browse ? 52 : 0));
        float listHeight = heightDp - 24 - 104 - (browse ? 10 : 0);
        float slice = Math.max(MIN_SLICE_DP, (listHeight - 2 * PAD_DP) / SLICES);
        float density = ctx.getResources().getDisplayMetrics().density;
        double bytes = 4.0 * listWidth * density * (slice + 2 * PAD_DP) * density;
        if (bytes > MAX_SLICE_BYTES) density *= (float) Math.sqrt(MAX_SLICE_BYTES / bytes);
        return new DayView(Math.round(listWidth * density), Math.round(slice * density), density);
    }

    /** The list position that brings `now` on screen (the following slice at the bottom edge). */
    static int positionFor(Chart.Day day, long now) {
        if (now < day.start || now >= day.end) return 0;
        int slice = (int) ((now - day.start) * SLICES / (day.end - day.start));
        return Math.min(SLICES - 1, slice + 1);
    }
}
