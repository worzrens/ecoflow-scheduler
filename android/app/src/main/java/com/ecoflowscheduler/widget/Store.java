package com.ecoflowscheduler.widget;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.GeneralSecurityException;
import java.security.KeyStore;
import java.util.ArrayList;
import java.util.List;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

import org.json.JSONArray;
import org.json.JSONException;

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

    synchronized List<Segments.Row> liveRows() {
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

    synchronized void addLive(Segments.Row r) throws IOException, JSONException {
        long cutoff = r.ts - 8 * 86400L;
        List<String> lines = new ArrayList<>();
        List<Segments.Row> rows = liveRows();
        rows.add(r);
        for (Segments.Row x : rows) {
            if (x.ts < cutoff) continue;
            lines.add(new JSONArray().put(x.ts).put(x.soc).put(x.in).put(x.out).put(x.acIn).put(x.acOut)
                    .put(x.limit).put(x.temp).put(x.grid).toString());
        }
        Files.write(liveFile().toPath(), lines, StandardCharsets.UTF_8);
    }
}
