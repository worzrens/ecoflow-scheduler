package com.ecoflowscheduler.widget;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.widget.RemoteViews;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.List;
import java.util.Locale;

public class WidgetProvider extends AppWidgetProvider {
    private static final String RANGE = "com.ecoflowscheduler.widget.RANGE";
    private static final String REFRESH = "com.ecoflowscheduler.widget.REFRESH";
    private static final long LIVE_MAX_AGE = 45 * 60;

    @Override
    public void onUpdate(Context ctx, AppWidgetManager manager, int[] ids) {
        inBackground(() -> renderAll(ctx));
        RefreshJob.schedulePeriodic(ctx);
        RefreshJob.refreshNow(ctx);
    }

    @Override
    public void onAppWidgetOptionsChanged(Context ctx, AppWidgetManager manager, int id, Bundle options) {
        inBackground(() -> renderAll(ctx));
    }

    @Override
    public void onDisabled(Context ctx) {
        RefreshJob.cancel(ctx);
    }

    @Override
    public void onReceive(Context ctx, Intent intent) {
        if (RANGE.equals(intent.getAction())) {
            new Store(ctx).setRange(intent.getIntExtra("id", 0), intent.getIntExtra("days", 3));
            inBackground(() -> renderAll(ctx));
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
    }

    private static PendingIntent broadcast(Context ctx, String action, int id, int days) {
        Intent i = new Intent(ctx, WidgetProvider.class).setAction(action).putExtra("id", id).putExtra("days", days);
        return PendingIntent.getBroadcast(ctx, id * 10 + days, i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    /** What the unit is doing now, from the newest sample of any source. Returns {battery, state, power line}. */
    static String[] describe(List<Segments.Row> rows, long now) {
        if (rows.isEmpty()) return new String[]{"--%", "No data yet", ""};
        Segments.Row r = rows.get(rows.size() - 1);
        String battery = Double.isNaN(r.soc) ? "--%" : Math.round(r.soc) + "%";
        double net = r.in - r.out;
        String state;
        String power;
        if (!r.mains()) {
            state = "No electricity";
            power = "Output " + Math.round(r.out) + " W" + (r.in > 3 ? " · solar " + Math.round(r.in) + " W" : "");
        } else {
            double usage = Math.min(Math.max(r.out, 0), Math.max(r.in, 0));
            double charging = Math.max(0, r.in - usage);
            state = r.soc >= 99.5 && net >= -3 ? "Fully charged" : (net > 3 ? "Charging " + Math.round(charging) + " W" : "On mains");
            power = "In " + Math.round(r.in) + " W · out " + Math.round(r.out) + " W · limit " + Math.round(r.limit) + " W";
        }
        if (now - r.ts > LIVE_MAX_AGE) {
            power = "Last reading " + new SimpleDateFormat("d.MM HH:mm", Locale.ROOT).format(new Date(r.ts * 1000))
                    + " · " + power;
        }
        return new String[]{battery, state, power};
    }

    private static RemoteViews views(Context ctx, AppWidgetManager manager, Store store, Repo.Data data, int id) {
        RemoteViews v = new RemoteViews(ctx.getPackageName(), R.layout.widget);
        long now = System.currentTimeMillis() / 1000;
        int days = store.range(id);

        String[] d = describe(data.rows, now);
        boolean setUp = store.configured() || store.liveConfigured();
        v.setTextViewText(R.id.battery, d[0]);
        v.setTextViewText(R.id.state, setUp ? d[1] : "Tap to set up");
        v.setTextColor(R.id.state, "No electricity".equals(d[1]) ? 0xFFE5534B : 0xFF2EE68A);
        v.setTextViewText(R.id.power, d[2]);

        Chart.Model m = Chart.model(data, days, now);
        String summary = "No power " + Chart.duration(m.realOutage)
                + (m.estimated >= 60 ? " (~" + Chart.duration(m.estimated) + " est.)" : "")
                + (m.hasSchedule ? " · planned " + Chart.duration(m.plannedOutage) : " · no schedule")
                + " · " + (days == 1 ? "today" : days + " days");
        v.setTextViewText(R.id.summary, summary);

        Bundle o = manager.getAppWidgetOptions(id);
        float density = ctx.getResources().getDisplayMetrics().density;
        int widthDp = o.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 280);
        int heightDp = o.getInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT, 220);
        int width = Math.min(1000, Math.max(200, Math.round((widthDp - 24) * density)));
        int height = Math.min(900, Math.max(80, Math.round((heightDp - 24 - 100) * density)));
        v.setImageViewBitmap(R.id.chart, Chart.draw(m, width, height, density, now));

        int[] chips = {R.id.range1, R.id.range3, R.id.range7};
        int[] values = {1, 3, 7};
        for (int i = 0; i < chips.length; i++) {
            boolean on = values[i] == days;
            v.setInt(chips[i], "setBackgroundResource", on ? R.drawable.chip_on : R.drawable.chip);
            v.setTextColor(chips[i], on ? 0xFF06130C : 0xFF8B93A1);
            v.setOnClickPendingIntent(chips[i], broadcast(ctx, RANGE, id, values[i]));
        }
        v.setOnClickPendingIntent(R.id.refresh, broadcast(ctx, REFRESH, id, 0));
        v.setOnClickPendingIntent(R.id.root, PendingIntent.getActivity(ctx, 0, new Intent(ctx, SettingsActivity.class),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));

        boolean failed = !store.get("repoError", "").isEmpty() || !store.get("liveError", "").isEmpty();
        long at = data.rows.isEmpty() ? 0 : data.rows.get(data.rows.size() - 1).ts;
        String updated = at == 0 ? "" : new SimpleDateFormat("HH:mm", Locale.ROOT).format(new Date(at * 1000));
        v.setTextViewText(R.id.updated, (failed ? "⚠ " : "") + updated);
        return v;
    }
}
