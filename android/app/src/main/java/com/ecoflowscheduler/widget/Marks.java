package com.ecoflowscheduler.widget;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * The shared marks.json document (see ecoflow_app/shared.py): manual "there was / was no electricity" statements about
 * stretches nothing was recorded for. Each install publishes the marks made on it; resolving them is Segments' job.
 */
final class Marks {
    static final long KEEP_SECONDS = 15 * 86400L;

    private Marks() {
    }

    static boolean valid(long start, long end, String kind) {
        return start > 0 && start < end && end - start <= 31 * 86400L
                && ("grid".equals(kind) || "outage".equals(kind) || "clear".equals(kind));
    }

    /** The marks of one document; damaged entries are skipped. */
    static List<Segments.Mark> parse(JSONObject doc) {
        List<Segments.Mark> out = new ArrayList<>();
        JSONArray list = doc.optJSONArray("marks");
        for (int i = 0; list != null && i < list.length(); i++) {
            JSONObject m = list.optJSONObject(i);
            if (m == null) continue;
            long start = m.optLong("start"), end = m.optLong("end");
            String kind = m.optString("kind");
            double at = m.optDouble("at", 0);
            if (valid(start, end, kind) && at > 0) {
                out.add(new Segments.Mark(start, end, kind, at, m.optString("by", "another device")));
            }
        }
        return out;
    }

    static JSONObject document(List<Segments.Mark> marks) throws JSONException {
        JSONArray list = new JSONArray();
        for (Segments.Mark m : marks) {
            list.put(new JSONObject().put("start", m.start).put("end", m.end).put("kind", m.kind).put("at", m.at)
                    .put("by", m.by));
        }
        return new JSONObject().put("v", 1).put("marks", list);
    }
}
