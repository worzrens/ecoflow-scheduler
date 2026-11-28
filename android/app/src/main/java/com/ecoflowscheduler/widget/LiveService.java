package com.ecoflowscheduler.widget;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.appwidget.AppWidgetManager;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

/**
 * Keeps the widget current while the screen is on: a reading from the unit as soon as the screen lights up and then
 * every 30 seconds, the repository every 5 minutes. Nothing runs while the screen is off. Android cannot tell an app
 * that its widget is being looked at, so "screen on" is the closest there is; staying alive for that needs a
 * foreground service.
 */
public class LiveService extends Service {
    private static final long LIVE_EVERY_MS = 30_000, REPO_EVERY = 300;
    private static final String CHANNEL = "live";

    private BroadcastReceiver screen;
    private Thread worker;

    static boolean wanted(Context ctx) {
        Store store = new Store(ctx);
        return store.autoUpdate() && (store.configured() || store.liveConfigured())
                && AppWidgetManager.getInstance(ctx)
                .getAppWidgetIds(new ComponentName(ctx, WidgetProvider.class)).length > 0;
    }

    /** Start or stop to match the settings. Android may refuse a start from the background; a later call succeeds. */
    static void update(Context ctx) {
        Intent i = new Intent(ctx, LiveService.class);
        if (!wanted(ctx)) {
            ctx.stopService(i);
            return;
        }
        try {
            ctx.startForegroundService(i);
        } catch (IllegalStateException | SecurityException ignored) {
            // not allowed right now: opening the app, tapping the widget or a restart starts it
        }
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL, "Widget auto update",
                NotificationManager.IMPORTANCE_MIN));
        screen = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                if (Intent.ACTION_SCREEN_OFF.equals(intent.getAction())) pause();
                else resume();
            }
        };
        IntentFilter filter = new IntentFilter(Intent.ACTION_SCREEN_ON);
        filter.addAction(Intent.ACTION_SCREEN_OFF);
        registerReceiver(screen, filter);              // these two are only delivered to a receiver registered in code
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        Notification n = new Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_refresh)
                .setContentTitle("EcoFlow widget updates while the screen is on")
                .setOngoing(true)
                .build();
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
            } else {
                startForeground(1, n);
            }
        } catch (IllegalStateException | SecurityException e) {
            stopSelf();
            return START_NOT_STICKY;
        }
        if (getSystemService(PowerManager.class).isInteractive()) resume();
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        unregisterReceiver(screen);
        pause();
        super.onDestroy();
    }

    private synchronized void resume() {
        if (worker != null && worker.isAlive() && !worker.isInterrupted()) return;
        worker = new Thread(this::loop, "ecoflow-widget-live");
        worker.start();
    }

    private synchronized void pause() {
        if (worker != null) worker.interrupt();
        worker = null;
    }

    /** False once paused - also when a library swallowed the interrupt. */
    private synchronized boolean current() {
        return worker == Thread.currentThread() && !Thread.currentThread().isInterrupted();
    }

    private void loop() {
        Context ctx = getApplicationContext();
        Store store = new Store(ctx);
        EcoFlow session = null;
        String account = "";
        try {
            while (current()) {
                if (!wanted(ctx)) {
                    stopSelf();
                    return;
                }
                if (store.liveConfigured()) {
                    try {
                        String now = store.get("email", "") + "|" + store.get("sn", "") + "|" + store.get("host", "")
                                + "|" + store.get("password", "");
                        if (session == null || !now.equals(account)) {
                            if (session != null) session.close();
                            session = null;
                            session = new EcoFlow(store.get("host", "api-e.ecoflow.com"), store.get("email", ""),
                                    store.secret("password"), store.get("sn", ""));
                            account = now;
                        }
                        store.addLive(session.read());
                        store.put("liveError", "");
                    } catch (InterruptedException e) {
                        return;
                    } catch (Exception e) {        // shown in the app; the next round connects again
                        if (session != null) session.close();
                        session = null;
                        store.put("liveError", Refresher.message(e));
                    }
                }
                if (!current()) return;
                long synced = Long.parseLong(store.get("repoAt", "0"));
                if (store.configured() && System.currentTimeMillis() / 1000 - synced >= REPO_EVERY) {
                    Refresher.repository(store);
                }
                WidgetProvider.renderAll(ctx);
                Thread.sleep(LIVE_EVERY_MS);
            }
        } catch (InterruptedException ignored) {
            // the screen went off
        } finally {
            if (session != null) session.close();
        }
    }
}
