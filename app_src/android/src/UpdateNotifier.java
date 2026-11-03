package io.github.fector101.melo;

import android.app.ActivityManager;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.os.Build;
import android.util.Log;

import androidx.core.app.NotificationCompat;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The background (WorkManager) update check: asks GitHub for the latest release,
 * compares it with the installed {@code versionName} (the buildozer.spec version)
 * and posts a notification. Tapping the notification opens Melo with an
 * {@code action=open_update} extra; the Python side then checks and shows the
 * update screen. The Java side never downloads anything and never reads the
 * release notes.
 */
public class UpdateNotifier {

    private static final String TAG = "UpdateNotifier";
    private static final String PREFS_NAME = "update_checker_prefs";
    private static final String KEY_LAST_NOTIFIED = "last_notified_timestamp";
    private static final long SEVEN_DAYS_MS = 7L * 24 * 60 * 60 * 1000;
    private static final String CHANNEL_ID = "update_channel";
    private static final String CHANNEL_NAME = "App Updates";
    private static final int NOTIFICATION_ID = 999;

    /** Mirrors repositories/update_repository.py::_VERSION. */
    private static final Pattern VERSION_PATTERN =
            Pattern.compile("(\\d+)(?:\\.(\\d+))?(?:\\.(\\d+))?");

    public static boolean isCooldownActive(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        long lastNotified = prefs.getLong(KEY_LAST_NOTIFIED, 0);
        long now = System.currentTimeMillis();
        Log.d(TAG, "elapsed=" + (now - lastNotified) + "ms, cooldown=" + SEVEN_DAYS_MS + "ms");
        return now - lastNotified < SEVEN_DAYS_MS;
    }

    public static boolean isNetworkAvailable(Context context) {
        try {
            ConnectivityManager cm = (ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
            if (cm == null) {
                return false;
            }
            NetworkInfo info = cm.getActiveNetworkInfo();
            return info != null && info.isConnected();
        } catch (Exception e) {
            Log.e(TAG, "Error checking network", e);
            return false;
        }
    }

    /** True while this app's own process is the foreground one (no duplicate notification). */
    public static boolean isAppForeground(Context context) {
        try {
            ActivityManager am = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
            if (am == null) {
                return false;
            }
            List<ActivityManager.RunningAppProcessInfo> processes = am.getRunningAppProcesses();
            if (processes == null) {
                return false;
            }
            String packageName = context.getPackageName();
            for (ActivityManager.RunningAppProcessInfo process : processes) {
                if (packageName.equals(process.processName)) {
                    return process.importance
                            == ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND;
                }
            }
        } catch (Exception e) {
            Log.e(TAG, "Could not read the process importance", e);
        }
        return false;
    }

    /** The check finished; nothing left to do. */
    public static final int CHECK_OK = 0;
    /** The fetch failed; a later attempt might succeed. */
    public static final int CHECK_RETRY = 1;
    /** A newer release exists but this device cannot show the notification. */
    public static final int CHECK_NOT_ELIGIBLE = 2;

    /**
     * Full check: version compare + notification.
     *
     * Returns {@link #CHECK_RETRY} only for transient failures: retrying a
     * notification that can never be posted (permission denied, channel off)
     * would hammer the API for nothing.
     */
    public static int checkAndNotify(Context context) {
        try {
            String currentVersion = getCurrentVersion(context);
            Log.d(TAG, "Current version: " + currentVersion);

            String latestVersion = fetchLatestVersion(context);
            if (latestVersion == null) {
                Log.e(TAG, "Failed to fetch latest version");
                return CHECK_RETRY;
            }
            Log.d(TAG, "Latest version: " + latestVersion);

            if (!isNewer(latestVersion, currentVersion)) {
                Log.d(TAG, "Already on latest version");
                return CHECK_OK;
            }

            Log.d(TAG, "New version available: " + latestVersion);
            if (!sendNotification(context, latestVersion)) {
                Log.w(TAG, "Notification not eligible to post, cooldown timestamp NOT saved");
                return CHECK_NOT_ELIGIBLE;
            }

            context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                    .edit().putLong(KEY_LAST_NOTIFIED, System.currentTimeMillis()).apply();
            Log.d(TAG, "Timestamp saved, notification sent");

        } catch (Exception e) {
            Log.e(TAG, "Update check failed", e);
            return CHECK_RETRY;
        }
        return CHECK_OK;
    }

    public static String getCurrentVersion(Context context) {
        try {
            PackageInfo pInfo = context.getPackageManager()
                    .getPackageInfo(context.getPackageName(), 0);
            return pInfo.versionName == null ? "" : pInfo.versionName;
        } catch (PackageManager.NameNotFoundException e) {
            Log.e(TAG, "Could not get package version", e);
            return "";
        }
    }

    /** True when {@code latest} is genuinely newer than {@code installed}. */
    static boolean isNewer(String latest, String installed) {
        int[] latestParts = versionParts(latest);
        int[] installedParts = versionParts(installed);
        if (latestParts == null || installedParts == null) {
            return latest != null && !latest.equals(installed);
        }
        for (int i = 0; i < 3; i++) {
            if (latestParts[i] != installedParts[i]) {
                return latestParts[i] > installedParts[i];
            }
        }
        return false;
    }

    private static int[] versionParts(String version) {
        if (version == null) {
            return null;
        }
        Matcher matcher = VERSION_PATTERN.matcher(version);
        if (!matcher.find()) {
            return null;
        }
        try {
            return new int[]{
                    Integer.parseInt(matcher.group(1)),
                    matcher.group(2) == null ? 0 : Integer.parseInt(matcher.group(2)),
                    matcher.group(3) == null ? 0 : Integer.parseInt(matcher.group(3)),
            };
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static String fetchLatestVersion(Context context) {
        try {
            URL url = new URL(UpdateEndpoints.getApiUrl(context));
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("GET");
            conn.setRequestProperty("Accept", "application/vnd.github.v3+json");
            conn.setConnectTimeout(10000);
            conn.setReadTimeout(10000);

            int responseCode = conn.getResponseCode();
            if (responseCode != 200) {
                Log.e(TAG, "HTTP " + responseCode);
                return null;
            }

            BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                sb.append(line);
            }
            reader.close();
            conn.disconnect();

            JSONObject json = new JSONObject(sb.toString());
            String tag = json.getString("tag_name").trim();
            return tag.startsWith("v") ? tag.substring(1) : tag;

        } catch (Exception e) {
            Log.e(TAG, "Failed to fetch latest version", e);
            return null;
        }
    }

    private static boolean canPostNotification(Context context) {
        try {
            NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm == null) {
                Log.w(TAG, "NotificationManager unavailable, cannot post");
                return false;
            }

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                if (context.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)
                        != PackageManager.PERMISSION_GRANTED) {
                    Log.w(TAG, "POST_NOTIFICATIONS permission not granted");
                    return false;
                }
            } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                if (!nm.areNotificationsEnabled()) {
                    Log.w(TAG, "Notifications disabled for app");
                    return false;
                }
            }

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                NotificationChannel channel = new NotificationChannel(
                        CHANNEL_ID, CHANNEL_NAME, NotificationManager.IMPORTANCE_DEFAULT);
                channel.setDescription("Notifications for app updates");
                nm.createNotificationChannel(channel);

                NotificationChannel created = nm.getNotificationChannel(CHANNEL_ID);
                if (created == null || created.getImportance() == NotificationManager.IMPORTANCE_NONE) {
                    Log.w(TAG, "Update channel disabled, cannot post");
                    return false;
                }
            }
            return true;
        } catch (Exception e) {
            Log.e(TAG, "Notification eligibility check failed", e);
            return false;
        }
    }

    private static boolean sendNotification(Context context, String version) {
        if (!canPostNotification(context)) {
            return false;
        }

        NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) {
            return false;
        }

        Intent launchIntent = context.getPackageManager().getLaunchIntentForPackage(context.getPackageName());
        if (launchIntent == null) {
            return false;
        }
        launchIntent.putExtra("action", "open_update");
        launchIntent.putExtra("version", version);
        launchIntent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                | Intent.FLAG_ACTIVITY_CLEAR_TOP
                | Intent.FLAG_ACTIVITY_SINGLE_TOP);

        PendingIntent pendingIntent = PendingIntent.getActivity(
                context, NOTIFICATION_ID, launchIntent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        NotificationCompat.Builder builder = new NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle("New version available")
                .setContentText("v" + version + " is ready. Tap to update.")
                .setPriority(NotificationCompat.PRIORITY_DEFAULT)
                .setContentIntent(pendingIntent)
                .setAutoCancel(true);

        nm.notify(NOTIFICATION_ID, builder.build());
        Log.d(TAG, "Notification sent for v" + version);
        return true;
    }

    /** Remove the update notification (called when the update screen opens). */
    public static void cancel(Context context) {
        try {
            NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null) {
                nm.cancel(NOTIFICATION_ID);
                Log.d(TAG, "Update notification cancelled");
            }
        } catch (Exception e) {
            Log.e(TAG, "Could not cancel the update notification", e);
        }
    }
}
