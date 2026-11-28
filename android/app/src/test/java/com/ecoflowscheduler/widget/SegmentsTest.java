package com.ecoflowscheduler.widget;

import static org.junit.Assert.assertEquals;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Scanner;

/** The Java port must give the same blocks as the Python code (golden.json: tools/make_android_golden.py). */
public class SegmentsTest {
    private static JSONObject golden() throws Exception {
        try (InputStream in = SegmentsTest.class.getResourceAsStream("/golden.json");
             Scanner s = new Scanner(in, StandardCharsets.UTF_8.name()).useDelimiter("\\A")) {
            return new JSONObject(s.next());
        }
    }

    private static void same(String what, JSONArray want, List<Segments.Seg> got) throws Exception {
        assertEquals(what + ": number of blocks", want.length(), got.size());
        for (int i = 0; i < want.length(); i++) {
            JSONArray w = want.getJSONArray(i);
            Segments.Seg g = got.get(i);
            String at = what + " block " + i;
            assertEquals(at + " start", w.getDouble(0), g.start, 0.01);
            assertEquals(at + " end", w.getDouble(1), g.end, 0.01);
            assertEquals(at + " kind", w.getInt(2), g.kind);
            if (w.length() > 3) {
                assertEquals(at + " soc start", w.isNull(3) ? -1 : w.getDouble(3), Double.isNaN(g.socStart) ? -1 : g.socStart, 0.01);
                assertEquals(at + " soc end", w.isNull(4) ? -1 : w.getDouble(4), Double.isNaN(g.socEnd) ? -1 : g.socEnd, 0.01);
                assertEquals(at + " energy", w.getDouble(5), g.outKwh, 0.0001);
                assertEquals(at + " marked by hand", w.getDouble(6), g.manualSeconds(), 0.01);
            }
        }
    }

    @Test
    public void historyMatchesPython() throws Exception {
        JSONArray cases = golden().getJSONArray("history");
        for (int c = 0; c < cases.length(); c++) {
            JSONObject k = cases.getJSONObject(c);
            JSONArray rows = k.getJSONArray("rows");
            List<Segments.Row> list = new ArrayList<>();
            for (int i = 0; i < rows.length(); i++) {
                JSONArray a = rows.getJSONArray(i);
                Segments.Row r = new Segments.Row();
                r.ts = a.getLong(0);
                r.soc = a.getDouble(1);
                r.in = a.getDouble(2);
                r.out = a.getDouble(3);
                r.acIn = a.getDouble(4);
                r.acOut = a.getDouble(5);
                r.limit = a.getDouble(6);
                r.temp = a.getDouble(7);
                r.grid = a.getInt(8);
                r.src = a.getString(9);
                list.add(r);
            }
            List<Segments.Mark> marks = new ArrayList<>();
            JSONArray made = k.getJSONArray("marks");
            for (int i = 0; i < made.length(); i++) {
                JSONArray a = made.getJSONArray(i);
                marks.add(new Segments.Mark(a.getLong(0), a.getLong(1), a.getString(2), a.getDouble(3), a.getString(4)));
            }
            Segments.State state = Segments.stateSince(list.subList(0, k.getInt("state_rows")));
            assertEquals("case " + c + " state", k.getJSONArray("state").getString(0), state.name);
            assertEquals("case " + c + " since", k.getJSONArray("state").getLong(1), state.since);
            same("case " + c, k.getJSONArray("segments"),
                    Segments.real(list, marks, k.getDouble("t0"), k.getDouble("t1"), k.getDouble("now")));
        }
    }

    @Test
    public void scheduleMatchesPython() throws Exception {
        JSONObject s = golden().getJSONObject("schedule");
        same("schedule", s.getJSONArray("segments"), Segments.scheduleDay(s.getLong("day"), s.getString("hours")));
    }
}
