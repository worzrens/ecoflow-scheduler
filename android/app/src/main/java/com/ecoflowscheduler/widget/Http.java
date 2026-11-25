package com.ecoflowscheduler.widget;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Map;

final class Http {
    static final class Reply {
        final int code;
        final byte[] body;

        Reply(int code, byte[] body) {
            this.code = code;
            this.body = body;
        }

        String text() {
            return new String(body, StandardCharsets.UTF_8);
        }
    }

    private Http() {
    }

    static Reply send(String method, String url, Map<String, String> headers, String body) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        try {
            c.setRequestMethod(method);
            c.setConnectTimeout(15000);
            c.setReadTimeout(20000);
            for (Map.Entry<String, String> h : headers.entrySet()) c.setRequestProperty(h.getKey(), h.getValue());
            if (body != null) {
                c.setDoOutput(true);
                try (OutputStream out = c.getOutputStream()) {
                    out.write(body.getBytes(StandardCharsets.UTF_8));
                }
            }
            int code = c.getResponseCode();
            InputStream in = code < 400 ? c.getInputStream() : c.getErrorStream();
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            if (in != null) {
                try (InputStream i = in) {
                    byte[] chunk = new byte[8192];
                    for (int n; (n = i.read(chunk)) > 0; ) buf.write(chunk, 0, n);
                }
            }
            return new Reply(code, buf.toByteArray());
        } finally {
            c.disconnect();
        }
    }
}
