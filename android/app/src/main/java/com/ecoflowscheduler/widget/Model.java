package com.ecoflowscheduler.widget;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** The data the app screens show, as JSON for assets/app/app.js (which only draws it). */
final class Model {
    static final int DAYS = 7;
    private static final long STATE_WINDOW = 3 * 86400L, ENERGY_MAX_GAP = 300;

    private Model() {
    }

    private static Object num(double v) {
        return Double.isNaN(v) ? JSONObject.NULL : (Object) (Math.round(v * 1000) / 1000.0);
    }

    static JSONObject reading(Segments.Row r) throws JSONException {
        return new JSONObject().put("ts", r.ts).put("soc", num(r.soc)).put("in", r.in).put("out", r.out)
                .put("acOut", r.acOut).put("limit", r.limit).put("temp", r.temp).put("grid", r.mains())
                .put("chgMin", num(r.chgMin)).put("dsgMin", num(r.dsgMin));
    }

    /** "live" = the newest reading, "state" = what the unit is doing and since when. */
    private static void current(JSONObject o, List<Segments.Row> rows, long now) throws JSONException {
        if (rows.isEmpty()) return;
        List<Segments.Row> recent = new ArrayList<>();
        for (Segments.Row r : rows) {
            if (r.ts >= now - STATE_WINDOW) recent.add(r);
        }
        o.put("live", reading(rows.get(rows.size() - 1)));
        Segments.State s = Segments.stateSince(recent);
        if (s != null) o.put("state", new JSONObject().put("name", s.name).put("since", s.since));
    }

    static JSONObject build(Repo.Data data, long now) throws JSONException {
        List<Segments.Row> rows = Segments.dropStale(data.rows);
        JSONObject out = new JSONObject().put("now", now).put("group", data.group);
        current(out, rows, now);

        long first = Chart.midnight(now, 1 - DAYS);
        JSONArray samples = new JSONArray();
        for (Segments.Row r : rows) {
            if (r.ts >= first - ENERGY_MAX_GAP) samples.put(new JSONArray().put(r.ts).put(num(r.soc)).put(r.in).put(r.out));
        }
        out.put("samples", samples);

        List<Segments.Seg> real = Segments.real(rows, data.marks, first, Chart.midnight(now, 1), now);
        JSONArray gaps = new JSONArray();               // stretches nothing was recorded for: these can be marked
        for (Segments.Seg s : Segments.grid(rows, first, Chart.midnight(now, 1), now)) {
            if (s.kind == Segments.NODATA) gaps.put(new JSONArray().put(s.start).put(s.end));
        }
        out.put("gaps", gaps);
        JSONArray days = new JSONArray();
        for (int k = 0; k <= DAYS; k++) {                       // the last one is tomorrow (schedule only)
            long d0 = Chart.midnight(now, 1 - DAYS + k), d1 = Chart.midnight(now, 2 - DAYS + k);
            JSONArray realJson = new JSONArray(), planJson = new JSONArray();
            for (Segments.Seg s : Segments.slice(real, d0, d1)) {
                double estimated = 0;
                for (double[] e : s.est) estimated += e[1] - e[0];
                realJson.put(new JSONArray().put(s.start).put(s.end).put(s.kind).put(num(s.socStart))
                        .put(num(s.socEnd)).put(num(s.outKwh)).put(estimated).put(s.manualSeconds()));
            }
            for (Map.Entry<Long, String> e : data.schedule.entrySet()) {
                if (e.getKey() + 43200 >= d0 && e.getKey() + 43200 < d1) {
                    for (Segments.Seg s : Segments.scheduleDay(e.getKey(), e.getValue())) {
                        planJson.put(new JSONArray().put(s.start).put(s.end).put(s.kind));
                    }
                }
            }
            double in = 0, used = 0;
            boolean has = false;
            for (int i = 0; i < rows.size(); i++) {
                Segments.Row a = rows.get(i);
                if (a.ts < d0 || a.ts >= d1) continue;
                has = true;
                if (i + 1 < rows.size()) {
                    long dt = rows.get(i + 1).ts - a.ts;
                    if (dt > 0 && dt <= ENERGY_MAX_GAP) {
                        in += a.in * dt / 3.6e6;
                        used += a.out * dt / 3.6e6;
                    }
                }
            }
            days.put(new JSONObject().put("start", d0).put("end", d1).put("real", realJson).put("plan", planJson)
                    .put("inKwh", num(in)).put("outKwh", num(used)).put("hasData", has));
        }
        return out.put("days", days);
    }

    /** What is connected - never includes the password or the token. */
    static JSONObject setup(Store store, Repo.Data data) throws JSONException {
        JSONObject account = new JSONObject()
                .put("connected", store.liveConfigured())
                .put("email", store.get("email", ""))
                .put("sn", store.get("sn", ""))
                .put("host", store.get("host", "api-e.ecoflow.com"))
                .put("error", store.get("liveError", ""));
        JSONObject repo = new JSONObject()
                .put("connected", store.configured())
                .put("repo", store.get("repo", ""))
                .put("error", store.get("repoError", ""))
                .put("marksError", store.get("marksError", ""))
                .put("syncedAt", Long.parseLong(store.get("repoAt", "0")))
                .put("samples", data.rows.size())
                .put("scheduleDays", data.schedule.size())
                .put("group", data.group);
        return new JSONObject().put("account", account).put("repo", repo).put("autoUpdate", store.autoUpdate());
    }
}
