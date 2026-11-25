package com.ecoflowscheduler.widget;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;

/** Background refresh. Android allows a periodic job every 15 minutes at most (and may delay it to save battery). */
public class RefreshJob extends JobService {
    private static final int PERIODIC = 1, ONCE = 2;

    static void schedulePeriodic(Context ctx) {
        JobScheduler s = ctx.getSystemService(JobScheduler.class);
        if (s.getPendingJob(PERIODIC) != null) return;
        s.schedule(new JobInfo.Builder(PERIODIC, new ComponentName(ctx, RefreshJob.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPeriodic(15 * 60 * 1000L)
                .setPersisted(true)
                .build());
    }

    static void refreshNow(Context ctx) {
        ctx.getSystemService(JobScheduler.class).schedule(
                new JobInfo.Builder(ONCE, new ComponentName(ctx, RefreshJob.class))
                        .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                        .setOverrideDeadline(1000)
                        .build());
    }

    static void cancel(Context ctx) {
        ctx.getSystemService(JobScheduler.class).cancelAll();
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        new Thread(() -> {
            try {
                Refresher.run(getApplicationContext());
            } finally {
                jobFinished(params, false);
            }
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return false;
    }
}
