package app.mealsy.android.push

import android.content.Context
import android.os.Build
import androidx.core.app.NotificationManagerCompat
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.flow.first
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Where notification permission currently stands, for the Settings
 * "Daily summary" reminder toggle (#44):
 * - [GRANTED]: the switch can turn on directly.
 * - [ASKABLE]: turning the switch on should launch the system
 *   `POST_NOTIFICATIONS` request (API 33+); turn on only if granted.
 * - [DENIED_PERMANENTLY]: the switch stays off; show an inline
 *   "Notifications are off for Mealsy" message with an Open Settings action.
 */
enum class NotificationPermissionState { GRANTED, ASKABLE, DENIED_PERMANENTLY }

/**
 * Seam over Android's notification-permission APIs so [app.mealsy.android.ui.settings.SettingsViewModel]
 * is unit-testable without `PackageManager`/`NotificationManagerCompat`.
 *
 * Below API 33 there is no runtime `POST_NOTIFICATIONS` permission to
 * request — [currentState] then only reflects whether notifications are
 * enabled at the OS level ([NotificationManagerCompat.areNotificationsEnabled]);
 * since there's nothing an in-app request can fix, a disabled channel
 * resolves to [NotificationPermissionState.DENIED_PERMANENTLY] (the only
 * recovery is Settings).
 *
 * On API 33+, Android silently denies (no dialog shown) after the
 * permission has already been requested and denied twice
 * (`USER_FIXED`, see #44's repro). [recordRequestAttempt] tracks how many
 * times this app has asked so [currentState] can tell the difference
 * between "still askable" and "permanently denied" without needing an
 * `Activity` to call `shouldShowRequestPermissionRationale`.
 */
interface NotificationPermissionChecker {
    suspend fun currentState(): NotificationPermissionState

    /** Call once after every system permission request completes (granted or not). */
    suspend fun recordRequestAttempt()
}

private val Context.notificationPermissionDataStore: DataStore<Preferences> by
    preferencesDataStore(name = "notification_permission")

private val REQUEST_COUNT_KEY = intPreferencesKey("post_notifications_request_count")

/** Android stops showing the system permission dialog after this many prior requests. */
private const val MAX_ASKABLE_ATTEMPTS = 2

@Singleton
class AndroidNotificationPermissionChecker
    @Inject
    constructor(
        @ApplicationContext private val context: Context,
    ) : NotificationPermissionChecker {
        override suspend fun currentState(): NotificationPermissionState {
            if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    val requestCount = context.notificationPermissionDataStore.data.first()[REQUEST_COUNT_KEY] ?: 0
                    return if (requestCount < MAX_ASKABLE_ATTEMPTS) {
                        NotificationPermissionState.ASKABLE
                    } else {
                        NotificationPermissionState.DENIED_PERMANENTLY
                    }
                }
                // Pre-33: no runtime permission to request — the only fix is Settings.
                return NotificationPermissionState.DENIED_PERMANENTLY
            }
            return NotificationPermissionState.GRANTED
        }

        override suspend fun recordRequestAttempt() {
            context.notificationPermissionDataStore.edit { prefs ->
                prefs[REQUEST_COUNT_KEY] = (prefs[REQUEST_COUNT_KEY] ?: 0) + 1
            }
        }
    }

@Module
@InstallIn(SingletonComponent::class)
abstract class NotificationPermissionModule {
    @Binds
    abstract fun bindNotificationPermissionChecker(impl: AndroidNotificationPermissionChecker): NotificationPermissionChecker
}
