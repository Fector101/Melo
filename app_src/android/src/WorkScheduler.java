package io.github.fector101.melo;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;

import java.util.concurrent.TimeUnit;

/**
 * Schedules the background update check.
 *
 * The periodic work runs every 7 days (WorkManager also survives reboots, since
 * its own manifest handles rescheduling). Two one-time checks make the first
 * result arrive sooner than a week:
 *
 * - a first-install check 60 s after the work is first scheduled;
 * - an immediate check while {@code update_endpoint.json} exists, so a local
 *   release server can be tested without waiting (test-only; the file is
 *   gitignored and only a debug build can push it).
 */
public class WorkScheduler {

    public static final String WORK_TAG = "update_check_work";
    static final String FIRST_CHECK_TAG = "update_check_first";
    static final String OVERRIDE_CHECK_TAG = "update_check_override";

    private static final String PREFS_NAME = "update_checker_prefs";
    private static final String KEY_FIRST_CHECK_SCHEDULED = "first_check_scheduled";
    private static final long FIRST_CHECK_DELAY_SECONDS = 60;
    private static final long OVERRIDE_CHECK_DELAY_SECONDS = 5;

    public static void scheduleUpdateCheck(Context context) {
        Constraints constraints = new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build();

        WorkManager workManager = WorkManager.getInstance(context);

        PeriodicWorkRequest periodic = new PeriodicWorkRequest.Builder(
                UpdateCheckWorker.class, 7, TimeUnit.DAYS)
                .setConstraints(constraints)
                .addTag(WORK_TAG)
                .build();

        workManager.enqueueUniquePeriodicWork(
                WORK_TAG,
                ExistingPeriodicWorkPolicy.KEEP,
                periodic);

        boolean hasOverride = UpdateEndpoints.hasOverride(context);
        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        if (!hasOverride && prefs.getBoolean(KEY_FIRST_CHECK_SCHEDULED, false)) {
            return;
        }
        if (!hasOverride) {
            prefs.edit().putBoolean(KEY_FIRST_CHECK_SCHEDULED, true).apply();
        }

        OneTimeWorkRequest oneTime = new OneTimeWorkRequest.Builder(UpdateCheckWorker.class)
                .setConstraints(constraints)
                .setInitialDelay(
                        hasOverride ? OVERRIDE_CHECK_DELAY_SECONDS : FIRST_CHECK_DELAY_SECONDS,
                        TimeUnit.SECONDS)
                .addTag(hasOverride ? OVERRIDE_CHECK_TAG : FIRST_CHECK_TAG)
                .build();

        workManager.enqueueUniqueWork(
                hasOverride ? OVERRIDE_CHECK_TAG : FIRST_CHECK_TAG,
                hasOverride ? ExistingWorkPolicy.REPLACE : ExistingWorkPolicy.KEEP,
                oneTime);
    }
}
