package com.ecoflowscheduler.widget;

import android.appwidget.AppWidgetManager;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.widget.RemoteViews;
import android.widget.RemoteViewsService;

/** Supplies the scrolling list of the vertical day view: one picture of the day, handed out slice by slice. */
public class DayService extends RemoteViewsService {
    @Override
    public RemoteViewsFactory onGetViewFactory(Intent intent) {
        return new Slices(getApplicationContext(),
                intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID));
    }

    private static final class Slices implements RemoteViewsFactory {
        private final Context ctx;
        private final int widgetId;
        private Bitmap picture;
        private int slicePx;

        Slices(Context ctx, int widgetId) {
            this.ctx = ctx;
            this.widgetId = widgetId;
        }

        @Override
        public void onCreate() {
        }

        /** Called before the first item and after every refresh; may take a moment (runs off the main thread). */
        @Override
        public synchronized void onDataSetChanged() {
            Store store = new Store(ctx);
            int days = store.range(widgetId);
            if (days == 7) {                      // the week view is a single picture, not this list
                picture = null;
                return;
            }
            long now = System.currentTimeMillis() / 1000;
            Chart.Model model = Chart.model(Repo.load(store), days, now);
            Chart.Day day = Chart.selected(model, days, store.dayBack(widgetId, Chart.midnight(now, 0)));
            DayView size = DayView.of(ctx, widgetId, days == 3);
            slicePx = size.slicePx;
            picture = Chart.drawDay(day, size.widthPx, size.slicePx, size.density, now);
        }

        @Override
        public synchronized int getCount() {
            return picture == null ? 0 : DayView.SLICES;
        }

        @Override
        public synchronized RemoteViews getViewAt(int position) {
            RemoteViews item = new RemoteViews(ctx.getPackageName(), R.layout.widget_slice);
            if (picture == null || position < 0 || position >= DayView.SLICES) return item;
            int top = position * slicePx;
            // the last slice also carries the margin under 24:00
            int height = position == DayView.SLICES - 1 ? picture.getHeight() - top : slicePx;
            item.setImageViewBitmap(R.id.slice, Bitmap.createBitmap(picture, 0, top, picture.getWidth(), height));
            item.setOnClickFillInIntent(R.id.slice, new Intent());
            return item;
        }

        @Override
        public RemoteViews getLoadingView() {
            return new RemoteViews(ctx.getPackageName(), R.layout.widget_slice);
        }

        @Override
        public int getViewTypeCount() {
            return 1;
        }

        @Override
        public long getItemId(int position) {
            return position;
        }

        @Override
        public boolean hasStableIds() {
            return true;
        }

        @Override
        public synchronized void onDestroy() {
            picture = null;
        }
    }
}
