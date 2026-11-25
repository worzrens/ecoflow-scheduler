package com.ecoflowscheduler.widget;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.text.SpannableString;
import android.text.Spanned;
import android.text.style.ForegroundColorSpan;
import android.util.TypedValue;
import android.view.View;
import android.widget.RemoteViews;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

public class WidgetProvider extends AppWidgetProvider {
    private static final String RANGE = "com.ecoflowscheduler.widget.RANGE";
    private static final String REFRESH = "com.ecoflowscheduler.widget.REFRESH";
    private static final String DAY = "com.ecoflowscheduler.widget.DAY";

    @Override
    public void onUpdate(Context ctx, AppWidgetManager manager, int[] ids) {
        inBackground(() -> {
            renderAll(ctx);
            // a new widget starts at the current time; later refreshes keep the position the user scrolled to
            Store store = new Store(ctx);
            for (int id : ids) {
                if (!store.get("scrolled" + id, "").isEmpty()) continue;
                scrollToNow(ctx, id);
                store.put("scrolled" + id, "1");
            }
        });
        RefreshJob.schedulePeriodic(ctx);
        RefreshJob.refreshNow(ctx);
    }

    @Override
    public void onAppWidgetOptionsChanged(Context ctx, AppWidgetManager manager, int id, Bundle options) {
        inBackground(() -> {
            renderAll(ctx);
            scrollToNow(ctx, id);
        });
    }

    @Override
    public void onDisabled(Context ctx) {
        RefreshJob.cancel(ctx);
    }

    @Override
    public void onReceive(Context ctx, Intent intent) {
        if (RANGE.equals(intent.getAction())) {
            Store store = new Store(ctx);
            int id = intent.getIntExtra("id", 0);
            store.setRange(id, intent.getIntExtra("value", 3));
            store.setDayBack(id, 0, Chart.midnight(System.currentTimeMillis() / 1000, 0));
            inBackground(() -> {
                renderAll(ctx);
                scrollToNow(ctx, id);
            });
        } else if (DAY.equals(intent.getAction())) {
            int id = intent.getIntExtra("id", 0);
            new Store(ctx).setDayBack(id, intent.getIntExtra("value", 0),
                    Chart.midnight(System.currentTimeMillis() / 1000, 0));
            inBackground(() -> {
                renderAll(ctx);
                scrollToNow(ctx, id);
            });
        } else if (REFRESH.equals(intent.getAction())) {
            RefreshJob.schedulePeriodic(ctx);
            RefreshJob.refreshNow(ctx);
        } else {
            super.onReceive(ctx, intent);
        }
    }

    private void inBackground(Runnable work) {
        PendingResult pending = goAsync();
        new Thread(() -> {
            try {
                work.run();
            } finally {
                if (pending != null) pending.finish();
            }
        }).start();
    }

    static void renderAll(Context ctx) {
        AppWidgetManager manager = AppWidgetManager.getInstance(ctx);
        int[] ids = manager.getAppWidgetIds(new ComponentName(ctx, WidgetProvider.class));
        if (ids.length == 0) return;
        Store store = new Store(ctx);
        Repo.Data data = Repo.load(store);
        for (int id : ids) manager.updateAppWidget(id, views(ctx, manager, store, data, id));
        manager.notifyAppWidgetViewDataChanged(ids, R.id.list);          // the day list redraws itself (DayService)
    }

    /** Move the day list to the current time (a past day: to its start). */
    private static void scrollToNow(Context ctx, int id) {
        Store store = new Store(ctx);
        int days = store.range(id);
        if (days == 7) return;
        try {
            Thread.sleep(700);                    // the list has to receive its items before it can be scrolled
        } catch (InterruptedException e) {
            return;
        }
        long now = System.currentTimeMillis() / 1000;
        Chart.Day day = Chart.selected(Chart.model(Repo.load(store), days, now), days,
                store.dayBack(id, Chart.midnight(now, 0)));
        RemoteViews v = new RemoteViews(ctx.getPackageName(), R.layout.widget);
        v.setScrollPosition(R.id.list, DayView.positionFor(day, now));
        AppWidgetManager.getInstance(ctx).partiallyUpdateAppWidget(id, v);
    }

    private static PendingIntent broadcast(Context ctx, String action, int id, int value) {
        Intent i = new Intent(ctx, WidgetProvider.class).setAction(action).putExtra("id", id).putExtra("value", value)
                .setData(Uri.parse("ecoflow://widget/" + id + "/" + action + "/" + value));   // one PendingIntent each
        return PendingIntent.getBroadcast(ctx, 0, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    private static void figure(RemoteViews v, int caption, int value, String name, String text, int color, boolean narrow) {
        v.setTextViewText(caption, name);
        v.setTextViewText(value, text);
        v.setTextColor(value, color);
        v.setTextViewTextSize(value, TypedValue.COMPLEX_UNIT_SP, narrow ? 10.5f : 13f);
    }

    private static RemoteViews views(Context ctx, AppWidgetManager manager, Store store, Repo.Data data, int id) {
        RemoteViews v = new RemoteViews(ctx.getPackageName(), R.layout.widget);
        long now = System.currentTimeMillis() / 1000;
        long today = Chart.midnight(now, 0);
        int days = store.range(id);
        boolean setUp = store.configured() || store.liveConfigured();

        Bundle o = manager.getAppWidgetOptions(id);
        float density = ctx.getResources().getDisplayMetrics().density;
        int widthDp = o.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 320);
        int heightDp = o.getInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT, 340);
        boolean narrow = widthDp < 300;

        Header head = Header.of(data.rows, now);
        v.setTextViewText(R.id.battery, head.battery);
        v.setTextViewText(R.id.state, setUp ? head.state : "Tap to set up");
        v.setTextColor(R.id.state, setUp ? head.stateColor : Header.GREEN);
        figure(v, R.id.cap_in, R.id.val_in, narrow ? "IN" : "INPUT", head.input, head.inputColor, narrow);
        figure(v, R.id.cap_chg, R.id.val_chg, narrow ? "CHG" : "CHARGING", head.charging, head.chargingColor, narrow);
        figure(v, R.id.cap_out, R.id.val_out, narrow ? "OUT" : "OUTPUT", head.output, head.outputColor, narrow);
        figure(v, R.id.cap_lim, R.id.val_lim, narrow ? "MAX" : "LIMIT", head.limit, head.limitColor, narrow);

        // 1d = today, 3d = one of the last three days (arrows), 7d = one row per day
        Chart.Model m = Chart.model(data, days, now);
        boolean vertical = days != 7, browse = days == 3;
        int back = browse ? Math.max(0, Math.min(2, store.dayBack(id, today))) : 0;
        Chart.Day day = vertical ? Chart.selected(m, days, back) : null;
        double off = m.realOutage, planned = m.plannedOutage, estimated = m.estimated;
        boolean hasSchedule = m.hasSchedule;
        if (day != null) {
            off = Segments.secondsOf(day.real, Segments.OUTAGE);
            planned = Segments.secondsOf(day.planned, Segments.OUTAGE);
            hasSchedule = !day.planned.isEmpty();
            estimated = 0;
            for (Segments.Seg s : day.real) {
                if (s.kind != Segments.OUTAGE) continue;
                for (double[] x : s.est) estimated += x[1] - x[0];
            }
        }
        v.setTextViewText(R.id.off, "No power " + (estimated >= 60 ? "~" : "") + Chart.duration(off));
        v.setTextViewText(R.id.planned, hasSchedule ? "Planned " + Chart.duration(planned) : "No schedule");
        v.setTextViewText(R.id.date, day != null
                ? new SimpleDateFormat("EEE d MMM", Locale.ENGLISH).format(new Date(day.start * 1000)) : "7 days");

        v.setViewVisibility(R.id.prev, browse ? View.VISIBLE : View.GONE);
        v.setViewVisibility(R.id.next, browse ? View.VISIBLE : View.GONE);
        v.setViewVisibility(R.id.dots, browse ? View.VISIBLE : View.GONE);
        if (browse) {
            SpannableString dots = new SpannableString("●  ●  ●");           // oldest ... today
            int selected = (2 - back) * 3;
            dots.setSpan(new ForegroundColorSpan(Header.GREEN), selected, selected + 1, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
            v.setTextViewText(R.id.dots, dots);
            v.setTextColor(R.id.prev, back < 2 ? Header.TEXT : Header.OFF);
            v.setTextColor(R.id.next, back > 0 ? Header.TEXT : Header.OFF);
            v.setOnClickPendingIntent(R.id.prev, broadcast(ctx, DAY, id, Math.min(2, back + 1)));
            v.setOnClickPendingIntent(R.id.next, broadcast(ctx, DAY, id, Math.max(0, back - 1)));
        }

        v.setViewVisibility(R.id.list, vertical ? View.VISIBLE : View.GONE);
        v.setViewVisibility(R.id.chart, vertical ? View.GONE : View.VISIBLE);
        if (vertical) {                           // scrolling list of 3 hour slices
            Intent slices = new Intent(ctx, DayService.class).putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id);
            slices.setData(Uri.parse(slices.toUri(Intent.URI_INTENT_SCHEME)));        // one list per widget
            v.setRemoteAdapter(R.id.list, slices);
            // taps on list items fill into this template, so it has to be mutable (it names our own activity)
            int mutable = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ? PendingIntent.FLAG_MUTABLE : 0;
            v.setPendingIntentTemplate(R.id.list, PendingIntent.getActivity(ctx, 2,
                    new Intent(ctx, MainActivity.class).putExtra("tab", setUp ? "statistics" : "settings"),
                    PendingIntent.FLAG_UPDATE_CURRENT | mutable));
        } else {
            int width = Math.min(1000, Math.max(200, Math.round((widthDp - 24) * density)));
            int height = Math.min(1200, Math.max(80, Math.round((heightDp - 24 - 104) * density)));
            v.setImageViewBitmap(R.id.chart, Chart.draw(m, width, height, density, now));
        }

        int[] chips = {R.id.range1, R.id.range3, R.id.range7};
        int[] values = {1, 3, 7};
        for (int i = 0; i < chips.length; i++) {
            boolean on = values[i] == days;
            v.setInt(chips[i], "setBackgroundResource", on ? R.drawable.chip_on : R.drawable.chip);
            v.setTextColor(chips[i], on ? 0xFF06130C : 0xFF8B93A1);
            v.setOnClickPendingIntent(chips[i], broadcast(ctx, RANGE, id, values[i]));
        }
        v.setOnClickPendingIntent(R.id.refresh, broadcast(ctx, REFRESH, id, 0));
        v.setOnClickPendingIntent(R.id.root, PendingIntent.getActivity(ctx, setUp ? 1 : 0,
                new Intent(ctx, MainActivity.class).putExtra("tab", setUp ? "dashboard" : "settings"),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));

        boolean failed = !store.get("repoError", "").isEmpty() || !store.get("liveError", "").isEmpty();
        long at = data.rows.isEmpty() ? 0 : data.rows.get(data.rows.size() - 1).ts;
        String updated = at == 0 ? ""
                : new SimpleDateFormat(at >= today ? "HH:mm" : "d.MM HH:mm", Locale.ROOT).format(new Date(at * 1000));
        v.setTextViewText(R.id.updated, (failed ? "⚠ " : "") + updated);
        return v;
    }
}
