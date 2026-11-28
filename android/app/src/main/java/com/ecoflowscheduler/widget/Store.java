package com.ecoflowscheduler.widget;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.GeneralSecurityException;
import java.security.KeyStore;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Settings, secrets (encrypted with a key that never leaves the Android keystore) and the phone's own readings. */
final class Store {
    private static final String KEY_ALIAS = "ecoflow-widget";
    private final Context ctx;
    private final SharedPreferences prefs;

    Store(Context ctx) {
        this.ctx = ctx.getApplicationContext();
        this.prefs = this.ctx.getSharedPreferences("cfg", Context.MODE_PRIVATE);
    }

    String get(String key, String def) {
        return prefs.getString(key, def);
    }

    void put(String key, String value) {
        prefs.edit().putString(key, value).apply();
    }

    int range(int widgetId) {
        return prefs.getInt("range" + widgetId, 3);
    }

    void setRange(int widgetId, int days) {
        prefs.edit().putInt("range" + widgetId, days).apply();
    }

    /** 3 day view: how many days back the widget shows. Starts at today again on a new day. */
    int dayBack(int widgetId, long today) {
        return prefs.getLong("dayOn" + widgetId, 0) == today ? prefs.getInt("dayBack" + widgetId, 0) : 0;
    }

    void setDayBack(int widgetId, int back, long today) {
        prefs.edit().putInt("dayBack" + widgetId, back).putLong("dayOn" + widgetId, today).apply();
    }

    boolean autoUpdate() {
        return prefs.getBoolean("autoUpdate", true);
    }

    void setAutoUpdate(boolean on) {
        prefs.edit().putBoolean("autoUpdate", on).apply();
    }

    boolean configured() {
        return !get("sn", "").isEmpty() && !get("repo", "").isEmpty() && !get("token", "").isEmpty();
    }

    boolean liveConfigured() {
        return !get("email", "").isEmpty() && !get("password", "").isEmpty() && !get("sn", "").isEmpty();
    }

    private SecretKey key() throws GeneralSecurityException, IOException {
        KeyStore ks = KeyStore.getInstance("AndroidKeyStore");
        ks.load(null);
        if (!ks.containsAlias(KEY_ALIAS)) {
            KeyGenerator gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            gen.init(new KeyGenParameterSpec.Builder(KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .build());
            gen.generateKey();
        }
        return (SecretKey) ks.getKey(KEY_ALIAS, null);
    }

    void putSecret(String name, String value) throws GeneralSecurityException, IOException {
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.ENCRYPT_MODE, key());
        byte[] body = c.doFinal(value.getBytes(StandardCharsets.UTF_8));
        put(name, Base64.encodeToString(c.getIV(), Base64.NO_WRAP) + ":" + Base64.encodeToString(body, Base64.NO_WRAP));
    }

    String secret(String name) {
        String stored = get(name, "");
        int cut = stored.indexOf(':');
        if (cut < 0) return "";
        try {
            Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
            c.init(Cipher.DECRYPT_MODE, key(),
                    new GCMParameterSpec(128, Base64.decode(stored.substring(0, cut), Base64.NO_WRAP)));
            return new String(c.doFinal(Base64.decode(stored.substring(cut + 1), Base64.NO_WRAP)), StandardCharsets.UTF_8);
        } catch (GeneralSecurityException | IOException | IllegalArgumentException e) {
            return "";
        }
    }

    File blobDir() {
        File d = new File(ctx.getFilesDir(), "blobs");
        //noinspection ResultOfMethodCallIgnored
        d.mkdirs();
        return d;
    }

    // ---- the phone's own live readings (kept on the phone only; they cover the time the PCs are off)
    private File liveFile() {
        return new File(ctx.getFilesDir(), "live.jsonl");
    }

    /** Several threads (app, service, job) share the files, each with its own Store. */
    private static final Object FILES = new Object();

    List<Segments.Row> liveRows() {
        synchronized (FILES) {
            return readLive();
        }
    }

    private List<Segments.Row> readLive() {
        List<Segments.Row> rows = new ArrayList<>();
        try {
            if (!liveFile().exists()) return rows;
            for (String line : Files.readAllLines(liveFile().toPath(), StandardCharsets.UTF_8)) {
                Segments.Row r = Repo.parseRow(line, "phone");
                if (r != null) rows.add(r);
            }
        } catch (IOException ignored) {
            // a lost cache only costs the phone's own readings
        }
        return rows;
    }

    private static Object num(double v) {
        return Double.isNaN(v) ? JSONObject.NULL : (Object) v;
    }

    void forget(String... keys) {
        SharedPreferences.Editor e = prefs.edit();
        for (String k : keys) e.remove(k);
        e.apply();
    }

    // ---- manual marks made on this phone (published to the repository when the token allows writing)
    private File marksFile() {
        return new File(ctx.getFilesDir(), "marks.json");
    }

    List<Segments.Mark> ownMarks() {
        synchronized (FILES) {
            try {
                if (!marksFile().exists()) return new ArrayList<>();
                return Marks.parse(new JSONObject(
                        new String(Files.readAllBytes(marksFile().toPath()), StandardCharsets.UTF_8)));
            } catch (IOException | JSONException e) {
                return new ArrayList<>();
            }
        }
    }

    void addMark(long start, long end, String kind) throws IOException, JSONException {
        synchronized (FILES) {
            double at = System.currentTimeMillis() / 1000.0;
            List<Segments.Mark> kept = new ArrayList<>();
            for (Segments.Mark m : ownMarks()) {
                if (m.end >= at - Marks.KEEP_SECONDS) kept.add(m);
            }
            kept.add(new Segments.Mark(start, end, kind, at, deviceLabel()));
            File tmp = new File(ctx.getFilesDir(), "marks.tmp");
            Files.write(tmp.toPath(), Marks.document(kept).toString().getBytes(StandardCharsets.UTF_8));
            Files.move(tmp.toPath(), marksFile().toPath(), StandardCopyOption.REPLACE_EXISTING);
        }
    }

    /** This phone's folder name in the repository. */
    String deviceId() {
        synchronized (FILES) {
            String id = get("deviceId", "");
            if (id.isEmpty()) {
                id = "android-" + UUID.randomUUID().toString().substring(0, 8);
                put("deviceId", id);
            }
            return id;
        }
    }

    String deviceLabel() {
        return "Phone (" + Build.MODEL + ")";
    }

    /** Drop the downloaded repository files (on disconnect). */
    void clearRepoCache() {
        File[] files = blobDir().listFiles();
        if (files == null) return;
        for (File f : files) {
            //noinspection ResultOfMethodCallIgnored
            f.delete();
        }
    }

    void addLive(Segments.Row r) throws IOException, JSONException {
        synchronized (FILES) {
            writeLive(r);
        }
    }

    private void writeLive(Segments.Row r) throws IOException, JSONException {
        long cutoff = r.ts - 8 * 86400L;
        List<String> lines = new ArrayList<>();
        List<Segments.Row> rows = liveRows();
        rows.add(r);
        for (Segments.Row x : rows) {
            if (x.ts < cutoff) continue;
            lines.add(new JSONArray().put(x.ts).put(num(x.soc)).put(x.in).put(x.out).put(x.acIn).put(x.acOut)
                    .put(x.limit).put(x.temp).put(x.grid).put(num(x.chgMin)).put(num(x.dsgMin)).toString());
        }
        Files.write(liveFile().toPath(), lines, StandardCharsets.UTF_8);
    }
}
