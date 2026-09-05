package app.mealsy.android.push

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.getSystemService
import app.mealsy.android.MainActivity
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/** Notification channel for backend-sent coaching/summary pushes. */
const val DAILY_SUMMARY_CHANNEL_ID = "daily-summary"

/**
 * `data["deeplink"]` value that marks a push as "open the chat screen".
 *
 * ChatScreen is the sole authenticated destination and `AppNav` already
 * routes any `SignedIn` session straight to it (see `AppNavViewModel`), so
 * honoring this deep link doesn't require a custom `mealsy://chat` intent
 * filter or a second Activity route — a plain explicit launch of
 * [MainActivity] is enough; [EXTRA_OPEN_CHAT] is carried along in case a
 * future screen needs to branch on it. This is the "simpler robust option"
 * the task brief asks to choose and document over extending the manifest's
 * `mealsy://` scheme (already used for the Supabase auth callback) with a
 * second host.
 */
const val DEEPLINK_CHAT = "mealsy://chat"
const val EXTRA_OPEN_CHAT = "app.mealsy.android.push.OPEN_CHAT"

/**
 * Receives FCM pushes and shows them as notifications.
 *
 * Registered in the manifest unconditionally; on a checkout without
 * `google-services.json` this class is simply never instantiated by the FCM
 * SDK (there's no Firebase app to route messages to it), so no guard is
 * needed here — the guard lives in [FirebaseFcmTokenProvider] and
 * `app/build.gradle.kts`'s conditional google-services plugin application.
 */
@AndroidEntryPoint
class MealsyMessagingService : FirebaseMessagingService() {

    @Inject
    lateinit var pushRegistrar: PushRegistrar

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onNewToken(token: String) {
        super.onNewToken(token)
        serviceScope.launch { pushRegistrar.registerToken(token) }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        super.onMessageReceived(message)
        showNotification(message)
    }

    private fun showNotification(message: RemoteMessage) {
        ensureChannel()

        val title = message.notification?.title ?: message.data["title"] ?: "Mealsy"
        val body = message.notification?.body ?: message.data["body"].orEmpty()
        val openChat = message.data["deeplink"] == DEEPLINK_CHAT

        val contentIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            putExtra(EXTRA_OPEN_CHAT, openChat)
        }
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            contentIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notification = NotificationCompat.Builder(this, DAILY_SUMMARY_CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(body)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .build()

        try {
            // POST_NOTIFICATIONS (API 33+) is requested at first chat entry
            // (ChatScreen); if the user denied it, notify() throws
            // SecurityException — drop the notification rather than crash.
            NotificationManagerCompat.from(this).notify(NOTIFICATION_ID, notification)
        } catch (exc: SecurityException) {
            // Permission not granted — nothing to show.
        }
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService<NotificationManager>() ?: return
        val channel = NotificationChannel(
            DAILY_SUMMARY_CHANNEL_ID,
            "Daily summary",
            NotificationManager.IMPORTANCE_DEFAULT,
        )
        manager.createNotificationChannel(channel)
    }

    private companion object {
        const val NOTIFICATION_ID = 1
    }
}
