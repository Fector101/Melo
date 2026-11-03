package io.github.fector101.melo;

import android.content.Context;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

public class UpdateCheckWorker extends Worker {

    private static final String TAG = "UpdateCheckWorker";

    public UpdateCheckWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    @NonNull
    @Override
    public Result doWork() {
        Log.d(TAG, "doWork called");

        Context ctx = getApplicationContext();

        if (UpdateNotifier.isAppForeground(ctx)) {
            // The app's own startup check shows the update UI; a notification on
            // top of it would be a duplicate. Do not retry.
            Log.d(TAG, "App is in the foreground, skipping");
            return Result.success();
        }

        if (!UpdateNotifier.isNetworkAvailable(ctx)) {
            Log.d(TAG, "No network, retrying later");
            return Result.retry();
        }

        if (UpdateNotifier.isCooldownActive(ctx)) {
            Log.d(TAG, "Cooldown active, skipping");
            return Result.success();
        }

        return UpdateNotifier.checkAndNotify(ctx) == UpdateNotifier.CHECK_RETRY
                ? Result.retry()
                : Result.success();
    }
}
