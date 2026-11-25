package com.ecoflowscheduler.widget;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

import java.util.Arrays;
import java.util.Collections;

public class HeaderTest {
    private static Segments.Row row(double soc, double in, double out, int grid) {
        Segments.Row r = new Segments.Row();
        r.ts = 1000;
        r.soc = soc;
        r.in = in;
        r.out = out;
        r.limit = 300;
        r.grid = grid;
        return r;
    }

    private static Header of(Segments.Row r) {
        return Header.of(Collections.singletonList(r), r.ts + 10);
    }

    @Test
    public void chargingSplitsInputLikeTheDesktop() {
        Header h = of(row(60, 518, 218, 1));
        assertEquals("⚡ Charging", h.state);
        assertEquals(Arrays.asList("518 W", "300 W", "218 W", "300 W"), Arrays.asList(h.input, h.charging, h.output, h.limit));
        assertEquals(Header.TEXT, h.limitColor);
    }

    @Test
    public void fullAndOutageGreyTheLimit() {
        Header full = of(row(100, 214, 214, 1));
        assertEquals("✓ Full", full.state);
        assertEquals("0 W", full.charging);
        assertEquals(Header.OFF, full.limitColor);
        Header out = of(row(89, 0, 232, 0));
        assertEquals("No power", out.state);
        assertEquals("–", out.charging);
        assertEquals("232 W", out.output);
        assertEquals(Header.OFF, out.limitColor);
    }

    @Test
    public void oldReadingsLookOffline() {
        Segments.Row r = row(60, 518, 218, 1);
        Header h = Header.of(Collections.singletonList(r), r.ts + Header.STALE_AFTER + 1);
        assertEquals("Offline", h.state);
        assertEquals(Header.OFF, h.inputColor);
        assertEquals("--%", Header.of(Collections.emptyList(), 0).battery);
    }
}
