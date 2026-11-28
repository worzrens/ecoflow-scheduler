package com.ecoflowscheduler.widget;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * The app: Dashboard, Statistics and Settings, drawn by the bundled page in assets/app (no remote content is ever
 * loaded). This class feeds it data, polls the unit while the app is open and saves connections after verifying them.
 */
public class MainActivity extends Activity {
    private static final long POLL_MS = 5000, STORE_EVERY = 60, SYNC_IF_OLDER = 120;

    private Store store;
    private WebView web;
    private final ExecutorService work = Executors.newSingleThreadExecutor();
    private volatile boolean pageReady;
    private Thread poller;
    private String startTab = "dashboard";

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        store = new Store(this);
        startTab = tabOf(getIntent(), store.configured() || store.liveConfigured() ? "dashboard" : "settings");
        web = new WebView(this);
        web.setBackgroundColor(Color.rgb(0x0e, 0x10, 0x13));
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setBlockNetworkLoads(true);
        s.setDomStorageEnabled(true);       // remembers the chosen graph ranges
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return true;                  // the page never navigates anywhere
            }
        });
        web.addJavascriptInterface(new Bridge(), "Native");
        setContentView(web);
        web.loadUrl("file:///android_asset/app/index.html");
    }

    private static String tabOf(Intent intent, String def) {
        String t = intent == null ? null : intent.getStringExtra("tab");
        return t != null && t.matches("dashboard|statistics|settings") ? t : def;
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        js("App.showTab('" + tabOf(intent, "dashboard") + "')");
    }

    @Override
    protected void onResume() {
        super.onResume();
        startPolling();
        RefreshJob.schedulePeriodic(this);
        LiveService.update(this);
        long synced = Long.parseLong(store.get("repoAt", "0"));
        if (store.configured() && System.currentTimeMillis() / 1000 - synced > SYNC_IF_OLDER) work.execute(this::syncRepo);
        else work.execute(this::push);
    }

    @Override
    protected void onPause() {
        super.onPause();
        stopPolling();
        work.execute(() -> WidgetProvider.renderAll(getApplicationContext()));
    }

    @Override
    protected void onDestroy() {
        work.shutdown();
        web.destroy();
        super.onDestroy();
    }

    private void js(String code) {
        runOnUiThread(() -> {
            if (pageReady && !isDestroyed()) web.evaluateJavascript(code, null);
        });
    }

    private static String text(Exception e) {
        String m = e.getMessage();
        return m == null || m.isEmpty() ? e.getClass().getSimpleName() : m;
    }

    /** Send everything to the page. */
    private void push() {
        try {
            Repo.Data data = Repo.load(store);
            JSONObject model = Model.build(data, System.currentTimeMillis() / 1000).put("setup", Model.setup(store, data));
            js("App.setModel(" + model + ")");
        } catch (JSONException | RuntimeException e) {
            js("App.fail(" + JSONObject.quote(text(e)) + ")");
        }
    }

    private void syncRepo() {
        push();                              // show the cached data right away
        try {
            if (store.configured()) {
                Repo.sync(store);
                store.put("repoAt", String.valueOf(System.currentTimeMillis() / 1000));
                store.put("repoError", "");
            }
        } catch (Exception e) {
            store.put("repoError", text(e));
        }
        push();
        js("App.refreshDone()");
    }

    // ---------------------------------------------------------------- live readings while the app is open
    private synchronized void startPolling() {
        stopPolling();
        poller = new Thread(() -> {
            EcoFlow session = null;
            String account = "";
            long stored = 0;
            int failures = 0;
            try {
                while (!Thread.currentThread().isInterrupted()) {
                    long wait = POLL_MS;
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
                            Segments.Row r = session.read();
                            failures = 0;
                            store.put("liveError", "");
                            if (r.ts - stored >= STORE_EVERY) {
                                store.addLive(r);
                                stored = r.ts;
                                push();
                            }
                            js("App.setLive(" + Model.reading(r) + ")");
                        } catch (InterruptedException e) {
                            return;
                        } catch (Exception e) {
                            if (session != null) session.close();
                            session = null;
                            store.put("liveError", text(e));
                            js("App.liveError(" + JSONObject.quote(text(e)) + ")");
                            wait = Math.min(60000, POLL_MS * (1L << Math.min(4, ++failures)));
                        }
                    }
                    Thread.sleep(wait);
                }
            } catch (InterruptedException ignored) {
                // the app went to the background
            } finally {
                if (session != null) session.close();
            }
        }, "ecoflow-live");
        poller.start();
    }

    private synchronized void stopPolling() {
        if (poller != null) poller.interrupt();
        poller = null;
    }

    // ---------------------------------------------------------------- called by the page
    public final class Bridge {
        @JavascriptInterface
        public void ready() {
            pageReady = true;
            js("App.showTab('" + startTab + "')");
            work.execute(MainActivity.this::push);
        }

        @JavascriptInterface
        public void refresh() {
            work.execute(MainActivity.this::syncRepo);
        }

        /** An empty password keeps the saved one. Saved only if signing in and reading the unit works. */
        @JavascriptInterface
        public void connectAccount(String email, String password, String sn, String host) {
            work.execute(() -> {
                String error = "";
                try {
                    String mail = email.trim(), serial = sn.trim();
                    String server = host.trim().isEmpty() ? "api-e.ecoflow.com" : host.trim();
                    String secret = password.isEmpty() ? store.secret("password") : password;
                    if (mail.isEmpty() || serial.isEmpty() || secret.isEmpty()) {
                        throw new IllegalArgumentException("Fill in e-mail, password and serial number");
                    }
                    Segments.Row r = EcoFlow.readOnce(server, mail, secret, serial);
                    store.putSecret("password", secret);
                    store.put("email", mail);
                    store.put("sn", serial);
                    store.put("host", server);
                    store.put("liveError", "");
                    store.addLive(r);
                } catch (Exception e) {
                    error = text(e);
                }
                push();
                js("App.connected('account'," + JSONObject.quote(error) + ")");
                runOnUiThread(() -> LiveService.update(MainActivity.this));
            });
        }

        /** An empty token keeps the saved one. Saved only if the repository can be read. */
        @JavascriptInterface
        public void connectRepo(String repo, String token) {
            work.execute(() -> {
                String error = "";
                try {
                    String name = repo.trim().replaceFirst("^https://github\\.com/", "").replaceAll("^/+|/+$", "");
                    String secret = token.trim().isEmpty() ? store.secret("token") : token.trim();
                    if (store.get("sn", "").isEmpty()) {
                        throw new IllegalArgumentException("Connect the EcoFlow account first (its serial number is needed)");
                    }
                    if (!name.matches("[\\w.-]+/[\\w.-]+") || secret.isEmpty()) {
                        throw new IllegalArgumentException("Enter the repository as owner/name and a token");
                    }
                    Repo.sync(store, name, secret, store.get("sn", ""));
                    store.putSecret("token", secret);
                    store.put("repo", name);
                    store.put("repoAt", String.valueOf(System.currentTimeMillis() / 1000));
                    store.put("repoError", "");
                } catch (Exception e) {
                    error = text(e);
                }
                push();
                js("App.connected('repo'," + JSONObject.quote(error) + ")");
            });
        }

        /** "grid" / "outage" / "clear" for a stretch without data; shown at once, then sent to the repository. */
        @JavascriptInterface
        public void mark(double start, double end, String kind) {
            work.execute(() -> {
                String error;
                try {
                    long a = (long) start, b = (long) Math.ceil(end);
                    if (!Marks.valid(a, b, kind)) throw new IllegalArgumentException("Nothing to mark");
                    store.addMark(a, b, kind);
                    push();
                    error = store.configured() ? Repo.pushMarks(store) : "Connect the data repository to share it";
                } catch (Exception e) {
                    error = text(e);
                }
                push();
                WidgetProvider.renderAll(getApplicationContext());
                js("App.marked(" + JSONObject.quote(error) + ")");
            });
        }

        @JavascriptInterface
        public void setAutoUpdate(boolean on) {
            store.setAutoUpdate(on);
            runOnUiThread(() -> LiveService.update(MainActivity.this));
            work.execute(MainActivity.this::push);
        }

        @JavascriptInterface
        public void disconnect(String what) {
            work.execute(() -> {
                if ("account".equals(what)) {
                    store.forget("password", "email", "liveError");
                } else {
                    store.forget("token", "repo", "repoAt", "repoError", "marksError", "marksPushed");
                    store.clearRepoCache();
                }
                push();
            });
        }
    }
}
