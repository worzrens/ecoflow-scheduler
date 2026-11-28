package com.ecoflowscheduler.widget;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** After a restart of the phone or an update of the app the automatic widget updates start again by themselves. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context ctx, Intent intent) {
        String action = intent.getAction();
        if (Intent.ACTION_BOOT_COMPLETED.equals(action) || Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)) {
            LiveService.update(ctx);
        }
    }
}
