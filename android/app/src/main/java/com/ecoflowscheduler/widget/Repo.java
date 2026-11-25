package com.ecoflowscheduler.widget;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TimeZone;
import java.util.TreeMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

/**
 * Read-only access to the private data repository the desktop app syncs to. One request lists every file; only
 * files whose content changed are downloaded and kept on the phone. Nothing is ever written to the repository.
 */
final class Repo {
    private static final String API = "https://api.github.com/repos/";
    private static final int KEEP_DAYS = 9;

    static final class Data {
        final List<Segments.Row> rows = new ArrayList<>();
        /** day (unix midnight) -> 24 state letters of the chosen group */
        final Map<Long, String> schedule = new TreeMap<>();
        String region = "", group = "";
    }

    private Repo() {
    }

    private static Map<String, String> headers(String token, String accept) {
        Map<String, String> h = new HashMap<>();
        h.put("Authorization", "Bearer " + token);
        h.put("Accept", accept);
        h.put("X-GitHub-Api-Version", "2022-11-28");
        h.put("User-Agent", "ecoflow-widget");
        return h;
    }

    private static String safe(String name) {
        return name.replaceAll("[^A-Za-z0-9_.-]", "_");
    }

    private static File index(Store store) {
        return new File(store.blobDir(), "index.json");
    }

    /** Download what changed. Throws IOException with a readable message. */
    static void sync(Store store) throws IOException, JSONException {
        String repo = store.get("repo", ""), token = store.secret("token");
        Http.Reply r = Http.send("GET", API + repo + "/git/trees/HEAD?recursive=1",
                headers(token, "application/vnd.github+json"), null);
        if (r.code == 401) throw new IOException("GitHub rejected the token");
        if (r.code == 404) throw new IOException("Repository not found, or the token has no access to it");
        if (r.code != 200) throw new IOException("GitHub answered HTTP " + r.code);

        SimpleDateFormat day = new SimpleDateFormat("yyyy-MM-dd", Locale.ROOT);
        day.setTimeZone(TimeZone.getTimeZone("UTC"));
        String cutoff = day.format(new Date(System.currentTimeMillis() - KEEP_DAYS * 86400000L));
        String prefix = "ecoflow-history/" + safe(store.get("sn", "")) + "/";

        JSONArray tree = new JSONObject(r.text()).getJSONArray("tree");
        JSONObject wanted = new JSONObject();          // path -> sha
        for (int i = 0; i < tree.length(); i++) {
            JSONObject e = tree.getJSONObject(i);
            String path = e.getString("path");
            if (!"blob".equals(e.optString("type")) || !path.startsWith(prefix)) continue;
            String name = path.substring(path.lastIndexOf('/') + 1);
            boolean history = name.endsWith(".jsonl") && name.length() >= 10 && name.substring(0, 10).compareTo(cutoff) >= 0;
            if (history || name.equals("settings.json") || name.equals("schedule.json")) {
                wanted.put(path, e.getString("sha"));
            }
        }
        if (wanted.length() == 0) throw new IOException("No data for this serial number in the repository");

        ExecutorService pool = Executors.newFixedThreadPool(6);
        List<Future<?>> jobs = new ArrayList<>();
        Set<String> shas = new HashSet<>();
        for (Iterator<String> it = wanted.keys(); it.hasNext(); ) {
            String sha = wanted.getString(it.next());
            shas.add(sha);
            File target = new File(store.blobDir(), sha);
            if (target.exists()) continue;
            jobs.add(pool.submit(() -> {
                Http.Reply blob = Http.send("GET", API + repo + "/git/blobs/" + sha,
                        headers(token, "application/vnd.github.raw+json"), null);
                if (blob.code != 200) throw new IOException("GitHub answered HTTP " + blob.code);
                File tmp = new File(store.blobDir(), sha + ".tmp");
                Files.write(tmp.toPath(), blob.body);
                Files.move(tmp.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING);
                return null;
            }));
        }
        pool.shutdown();
        try {
            for (Future<?> j : jobs) j.get();
        } catch (ExecutionException e) {
            throw new IOException(String.valueOf(e.getCause() != null ? e.getCause().getMessage() : e.getMessage()));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IOException("Interrupted");
        } finally {
            pool.shutdownNow();
        }
        Files.write(index(store).toPath(), wanted.toString().getBytes(StandardCharsets.UTF_8));
        File[] files = store.blobDir().listFiles();
        if (files != null) {
            for (File f : files) {
                if (!f.getName().equals("index.json") && !shas.contains(f.getName())) {
                    //noinspection ResultOfMethodCallIgnored
                    f.delete();
                }
            }
        }
    }

    static Segments.Row parseRow(String line, String src) {
        try {
            JSONArray a = new JSONArray(line);
            if (a.length() < 9) return null;
            Segments.Row r = new Segments.Row();
            r.ts = a.getLong(0);
            r.soc = a.optDouble(1, Double.NaN);
            r.in = a.optDouble(2, 0);
            r.out = a.optDouble(3, 0);
            r.acIn = a.optDouble(4, 0);
            r.acOut = a.optDouble(5, 0);
            r.limit = a.optDouble(6, 0);
            r.temp = a.optDouble(7, 0);
            r.grid = a.isNull(8) ? -1 : a.optInt(8, -1);
            r.src = src;
            return r;
        } catch (JSONException e) {
            return null;
        }
    }

    /** Everything cached on the phone (repository files plus the phone's own readings), rows sorted by time. */
    static Data load(Store store) {
        Data d = new Data();
        List<Segments.Row> all = new ArrayList<>(store.liveRows());
        List<JSONObject> settings = new ArrayList<>(), schedules = new ArrayList<>();
        try {
            if (index(store).exists()) {
                JSONObject idx = new JSONObject(new String(Files.readAllBytes(index(store).toPath()), StandardCharsets.UTF_8));
                for (Iterator<String> it = idx.keys(); it.hasNext(); ) {
                    String path = it.next();
                    File f = new File(store.blobDir(), idx.getString(path));
                    if (!f.exists()) continue;
                    String[] parts = path.split("/");
                    String device = parts.length >= 4 ? parts[2] : "";
                    String text = new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
                    if (path.endsWith(".jsonl")) {
                        for (String line : text.split("\n")) {
                            Segments.Row r = parseRow(line, device);
                            if (r != null) all.add(r);
                        }
                    } else if (path.endsWith("/settings.json")) {
                        settings.add(new JSONObject(text));
                    } else if (path.endsWith("/schedule.json")) {
                        schedules.add(new JSONObject(text));
                    }
                }
            }
        } catch (IOException | JSONException ignored) {
            // show what could be read
        }
        all.sort((a, b) -> a.ts != b.ts ? Long.compare(a.ts, b.ts) : a.src.compareTo(b.src));
        long last = Long.MIN_VALUE;
        for (Segments.Row r : all) {
            if (r.ts != last) d.rows.add(r);
            last = r.ts;
        }

        // region / group: the newest choice made on any device
        double best = -1;
        for (JSONObject s : settings) {
            JSONObject o = s.optJSONObject("sections") == null ? null : s.optJSONObject("sections").optJSONObject("outage");
            JSONObject v = o == null ? null : o.optJSONObject("value");
            if (v == null) continue;
            double at = o.optDouble("at", 0);
            if (at > best && (at > 0 || !v.optString("region").isEmpty())) {
                best = at;
                d.region = v.optString("region");
                d.group = v.optString("group");
            }
        }
        // schedule: per day the most recently published copy
        Map<Long, String> published = new HashMap<>();
        for (JSONObject s : schedules) {
            JSONObject regions = s.optJSONObject("regions");
            JSONObject days = regions == null ? null : regions.optJSONObject(d.region);
            if (days == null) continue;
            for (Iterator<String> it = days.keys(); it.hasNext(); ) {
                String key = it.next();
                JSONObject entry = days.optJSONObject(key);
                JSONObject groups = entry == null ? null : entry.optJSONObject("g");
                String hours = groups == null ? "" : groups.optString(d.group);
                if (hours.length() != 24) continue;
                long ts = Long.parseLong(key);
                String stamp = sortable(entry.optString("u"));
                if (!published.containsKey(ts) || stamp.compareTo(published.get(ts)) > 0) {
                    published.put(ts, stamp);
                    d.schedule.put(ts, hours);
                }
            }
        }
        return d;
    }

    /** "dd.mm.yyyy HH:MM" -> "yyyymmdd HH:MM". */
    private static String sortable(String u) {
        return u.length() >= 16 ? u.substring(6, 10) + u.substring(3, 5) + u.substring(0, 2) + u.substring(10) : "";
    }
}
