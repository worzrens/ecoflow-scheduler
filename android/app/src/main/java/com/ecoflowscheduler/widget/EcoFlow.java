package com.ecoflowscheduler.widget;

import android.util.Base64;

import org.eclipse.paho.client.mqttv3.IMqttDeliveryToken;
import org.eclipse.paho.client.mqttv3.MqttCallback;
import org.eclipse.paho.client.mqttv3.MqttClient;
import org.eclipse.paho.client.mqttv3.MqttConnectOptions;
import org.eclipse.paho.client.mqttv3.MqttException;
import org.eclipse.paho.client.mqttv3.MqttMessage;
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Random;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** One live reading through the unofficial app cloud (same route as ecoflow_app/api.py). Read-only. */
final class EcoFlow {
    private EcoFlow() {
    }

    private static JSONObject checked(Http.Reply r, String what) throws IOException, JSONException {
        if (r.code != 200) throw new IOException(what + ": HTTP " + r.code);
        JSONObject j = new JSONObject(r.text());
        if (!"success".equalsIgnoreCase(j.optString("message"))) {
            throw new IOException(what + ": " + j.optString("message"));
        }
        return j.getJSONObject("data");
    }

    static Segments.Row read(String host, String email, String password, String sn)
            throws IOException, JSONException, MqttException, InterruptedException {
        Map<String, String> h = new HashMap<>();
        h.put("lang", "en_US");
        h.put("content-type", "application/json");
        JSONObject body = new JSONObject()
                .put("email", email)
                .put("password", Base64.encodeToString(password.getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP))
                .put("scene", "IOT_APP")
                .put("userType", "ECOFLOW");
        JSONObject login = checked(Http.send("POST", "https://" + host + "/auth/login", h, body.toString()), "Sign in");
        String uid = login.getJSONObject("user").getString("userId");
        h.put("authorization", "Bearer " + login.getString("token"));
        JSONObject cert = checked(Http.send("GET", "https://" + host + "/iot-auth/app/certification?userId="
                + URLEncoder.encode(uid, "UTF-8"), h, null), "MQTT credentials");

        String clientId = "ANDROID_" + UUID.randomUUID().toString().replace("-", "").toUpperCase(Locale.ROOT) + "_" + uid;
        MqttClient client = new MqttClient("ssl://" + cert.getString("url") + ":" + cert.getString("port"),
                clientId, new MemoryPersistence());
        CountDownLatch done = new CountDownLatch(1);
        AtomicReference<JSONObject> reply = new AtomicReference<>();
        client.setCallback(new MqttCallback() {
            @Override
            public void connectionLost(Throwable cause) {
                done.countDown();
            }

            @Override
            public void messageArrived(String topic, MqttMessage message) {
                try {
                    JSONObject j = new JSONObject(new String(message.getPayload(), StandardCharsets.UTF_8));
                    if ("latestQuotas".equals(j.optString("operateType"))) {
                        reply.set(j.getJSONObject("data"));
                        done.countDown();
                    }
                } catch (JSONException ignored) {
                    // unrelated message
                }
            }

            @Override
            public void deliveryComplete(IMqttDeliveryToken token) {
            }
        });
        MqttConnectOptions opts = new MqttConnectOptions();
        opts.setUserName(cert.getString("certificateAccount"));
        opts.setPassword(cert.getString("certificatePassword").toCharArray());
        opts.setCleanSession(true);
        opts.setConnectionTimeout(10);
        opts.setKeepAliveInterval(15);
        client.setTimeToWait(10000);
        try {
            client.connect(opts);
            String base = "/app/" + uid + "/" + sn + "/thing/property/";
            client.subscribe(base + "get_reply", 1);
            for (int attempt = 0; attempt < 3 && reply.get() == null; attempt++) {
                JSONObject ask = new JSONObject()
                        .put("from", "ef-widget")
                        .put("id", String.valueOf(100000000 + new Random().nextInt(900000000)))
                        .put("version", "1.1")
                        .put("moduleType", 0)
                        .put("operateType", "latestQuotas")
                        .put("params", new JSONObject());
                client.publish(base + "get", ask.toString().getBytes(StandardCharsets.UTF_8), 1, false);
                done.await(5, TimeUnit.SECONDS);
            }
        } finally {
            try {
                client.disconnectForcibly(500, 1000);
                client.close();
            } catch (MqttException ignored) {
                // already gone
            }
        }
        JSONObject data = reply.get();
        if (data == null) throw new IOException("No reply from the unit");
        if (data.optInt("online", 0) != 1) throw new IOException("Unit is offline");
        return parse(data.getJSONObject("quotaMap"));
    }

    private static Segments.Row parse(JSONObject q) throws IOException {
        boolean soc = q.has("ems.f32LcdShowSoc") || q.has("ems.lcdShowSoc");
        if (!soc || !q.has("pd.wattsInSum") || !q.has("pd.wattsOutSum") || !q.has("inv.cfgSlowChgWatts")) {
            throw new IOException("Incomplete reading from the unit");
        }
        Segments.Row r = new Segments.Row();
        r.ts = System.currentTimeMillis() / 1000;
        r.soc = q.optDouble("ems.f32LcdShowSoc", q.optDouble("ems.lcdShowSoc", 0));
        r.in = q.optDouble("pd.wattsInSum", 0);
        r.out = q.optDouble("pd.wattsOutSum", 0);
        r.acIn = q.optDouble("inv.inputWatts", 0);
        r.acOut = q.optDouble("inv.outputWatts", 0);
        r.limit = q.optDouble("inv.cfgSlowChgWatts", 0);
        r.temp = q.optDouble("bmsMaster.temp", 0);
        r.grid = q.has("inv.acInVol") ? (q.optDouble("inv.acInVol", 0) >= 90000 ? 1 : 0) : (r.acIn >= 5 ? 1 : 0);
        r.src = "phone";
        return r;
    }
}
