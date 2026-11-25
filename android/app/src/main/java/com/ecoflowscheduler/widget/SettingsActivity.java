package com.ecoflowscheduler.widget;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/** The only screen: connection settings and a status line. Passwords and the token are stored encrypted. */
public class SettingsActivity extends Activity {
    private Store store;
    private LinearLayout box;
    private TextView status;
    private EditText email, password, sn, host, repo, token;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        store = new Store(this);
        box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(20);
        box.setPadding(pad, pad, pad, pad);

        title("EcoFlow account (live battery and charging power)");
        email = field("E-mail", store.get("email", ""), InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS);
        password = secretField("Password", "password");
        sn = field("Serial number of the unit", store.get("sn", ""),
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        host = field("Server", store.get("host", "api-e.ecoflow.com"), InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);

        title("Data repository (graphs and outage schedule)");
        repo = field("owner/name", store.get("repo", ""), InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        token = secretField("Token (read-only is enough)", "token");

        Button save = new Button(this);
        save.setText("Save and refresh");
        save.setOnClickListener(this::save);
        box.addView(save);

        status = new TextView(this);
        status.setTextColor(Color.rgb(0x8b, 0x93, 0xa1));
        status.setPadding(0, dp(10), 0, 0);
        status.setText(lastStatus());
        box.addView(status);

        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(Color.rgb(0x0f, 0x11, 0x15));
        scroll.setFitsSystemWindows(true);
        scroll.addView(box);
        setContentView(scroll);
    }

    private String lastStatus() {
        String problems = (store.get("liveError", "") + "\n" + store.get("repoError", "")).trim();
        if (!problems.isEmpty()) return "Last refresh had problems:\n" + problems;
        return store.configured() ? "Add the widget from your home screen's widget list."
                : "Fill in the fields, press Save, then add the widget to your home screen.";
    }

    private void save(View button) {
        try {
            store.put("email", text(email));
            store.put("sn", text(sn));
            store.put("host", text(host).isEmpty() ? "api-e.ecoflow.com" : text(host));
            store.put("repo", text(repo).replaceFirst("^https://github\\.com/", "").replaceAll("^/+|/+$", ""));
            // an empty secret field keeps what is already stored
            if (!text(password).isEmpty()) store.putSecret("password", password.getText().toString());
            if (!text(token).isEmpty()) store.putSecret("token", text(token));
            password.setText("");
            token.setText("");
            password.setHint("Password (saved)");
        } catch (Exception e) {
            status.setText("Could not save: " + e.getMessage());
            return;
        }
        button.setEnabled(false);
        status.setText("Refreshing - the first download can take a minute...");
        RefreshJob.schedulePeriodic(this);
        new Thread(() -> {
            String problems = Refresher.run(getApplicationContext());
            Repo.Data data = Repo.load(store);
            String[] now = WidgetProvider.describe(data.rows, System.currentTimeMillis() / 1000);
            String result = (problems.isEmpty() ? "Connected." : problems) + "\n" + now[0] + " · " + now[1]
                    + "\n" + data.rows.size() + " samples, " + data.schedule.size() + " schedule days"
                    + (data.group.isEmpty() ? " (no outage group synced yet)" : " for group " + data.group);
            runOnUiThread(() -> {
                status.setText(result);
                button.setEnabled(true);
            });
        }).start();
    }

    private static String text(EditText e) {
        return e.getText().toString().trim();
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private void title(String s) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextColor(Color.rgb(0x2e, 0xe6, 0x8a));
        t.setPadding(0, dp(12), 0, dp(4));
        box.addView(t);
    }

    private EditText field(String hint, String value, int type) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setSingleLine(true);
        e.setInputType(type);
        e.setText(value);
        box.addView(e);
        return e;
    }

    private EditText secretField(String hint, String key) {
        return field(store.get(key, "").isEmpty() ? hint : hint + " (saved)", "",
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
    }
}
