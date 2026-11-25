package com.ecoflowscheduler.widget;

import java.util.ArrayList;
import java.util.List;

/**
 * The widget's top line: battery, state, and Input / Charging / Output / Limit, worked out like the desktop app's
 * input card (charging = input minus what the load takes). Pure Java, see HeaderTest.
 */
final class Header {
    static final int GREEN = 0xFF2EE68A, RED = 0xFFF87171, TEXT = 0xFFF3F4F6, MUTED = 0xFF8B93A1, OFF = 0xFF5B6270;
    static final long STALE_AFTER = 45 * 60, STATE_WINDOW = 3 * 86400L;
    private static final String NONE = "–";

    String battery = "--%", state = "No data";
    int stateColor = MUTED;
    String input = NONE, charging = NONE, output = NONE, limit = NONE;
    int inputColor = TEXT, chargingColor = TEXT, outputColor = TEXT, limitColor = TEXT;

    private Header() {
    }

    private static String watts(double w) {
        return Math.round(w) + " W";
    }

    /** `rows` sorted by time; the newest one is "now". */
    static Header of(List<Segments.Row> rows, long now) {
        Header h = new Header();
        if (rows.isEmpty()) return h;
        Segments.Row r = rows.get(rows.size() - 1);
        List<Segments.Row> recent = new ArrayList<>();
        for (Segments.Row x : rows) {
            if (x.ts >= r.ts - STATE_WINDOW) recent.add(x);
        }
        String name = Segments.stateSince(recent).name;
        h.battery = Double.isNaN(r.soc) ? "--%" : Math.round(r.soc) + "%";
        h.input = watts(r.in);
        h.output = watts(r.out);
        h.limit = r.limit > 0 ? watts(r.limit) : NONE;
        double spare = Math.max(0, r.in - Math.min(Math.max(r.out, 0), Math.max(r.in, 0)));
        if (!r.mains()) {
            h.state = "No power";
            h.stateColor = RED;
            h.chargingColor = OFF;
            h.limitColor = OFF;                 // the limit only applies to charging from the grid
        } else if ("full".equals(name)) {
            h.state = "✓ Full";
            h.stateColor = GREEN;
            h.charging = watts(0);
            h.limitColor = OFF;                 // not in use
        } else if ("charging".equals(name) && r.in - r.out > 3) {
            h.state = "⚡ Charging";
            h.stateColor = GREEN;
            h.charging = watts(spare);
            h.chargingColor = GREEN;
        } else {
            h.state = "discharging".equals(name) ? "Discharging" : "On grid";
            h.charging = watts(spare);
        }
        if (now - r.ts > STALE_AFTER) {        // old figures must not look current
            h.state = "Offline";
            h.stateColor = MUTED;
            h.inputColor = h.chargingColor = h.outputColor = h.limitColor = OFF;
        }
        return h;
    }
}
