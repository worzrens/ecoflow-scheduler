package com.ecoflowscheduler.widget;

import android.content.Context;

/** One full refresh: the unit's live state, then the repository. Each part may fail without stopping the other. */
final class Refresher {
    private Refresher() {
    }

    static synchronized String run(Context ctx) {
        Store store = new Store(ctx);
        StringBuilder problems = new StringBuilder();
        if (store.liveConfigured()) {
            try {
                store.addLive(EcoFlow.readOnce(store.get("host", "api-e.ecoflow.com"), store.get("email", ""),
                        store.secret("password"), store.get("sn", "")));
                store.put("liveError", "");
            } catch (Exception e) {      // any failure is shown to the user, the cached data stays
                store.put("liveError", message(e));
                problems.append("Live: ").append(message(e)).append('\n');
            }
        }
        if (store.configured()) {
            String error = repository(store);
            if (!error.isEmpty()) problems.append("Repository: ").append(error).append('\n');
        }
        return problems.toString().trim();
    }

    /** Download what changed in the repository. Returns the problem, or "". */
    static String repository(Store store) {
        try {
            Repo.sync(store);
            store.put("repoAt", String.valueOf(System.currentTimeMillis() / 1000));
            store.put("repoError", "");
            Repo.pushMarks(store);              // retried here until it works; its problem is shown in the app
            return "";
        } catch (Exception e) {
            store.put("repoError", message(e));
            return message(e);
        }
    }

    static String message(Exception e) {
        String m = e.getMessage();
        return m == null || m.isEmpty() ? e.getClass().getSimpleName() : m;
    }
}
