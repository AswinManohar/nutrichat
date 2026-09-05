package app.mealsy.android.push

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.RegisterDeviceRequest
import app.mealsy.data.auth.SignOutHook
import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import kotlin.coroutines.resume
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.suspendCancellableCoroutine
import javax.inject.Inject
import javax.inject.Provider
import javax.inject.Singleton

/**
 * Seam over the real FCM token source (`FirebaseMessaging.getInstance().token`),
 * so [PushRegistrar] and [PushRegistrarTest] never touch Firebase directly and
 * run as plain JVM tests.
 */
fun interface FcmTokenProvider {
    suspend fun currentToken(): String?
}

/**
 * Persists the most recently registered FCM token, for [PushRegistrar]'s
 * idempotency check, and whether the user has explicitly turned reminders
 * off from Settings ([isRemindersDisabled]) — [PushRegistrar.ensureRegistered]
 * checks this so `AppNav`'s unconditional post-sign-in call can't silently
 * re-register a token the user just asked to stop receiving.
 */
interface DeviceTokenStore {
    suspend fun getLastSentToken(): String?
    suspend fun setLastSentToken(token: String)
    suspend fun clearLastSentToken()
    suspend fun isRemindersDisabled(): Boolean
    suspend fun setRemindersDisabled(disabled: Boolean)
}

private val Context.deviceTokenDataStore: DataStore<Preferences> by
    preferencesDataStore(name = "push_device")

private val LAST_SENT_TOKEN_KEY = stringPreferencesKey("last_sent_fcm_token")
private val REMINDERS_DISABLED_KEY = booleanPreferencesKey("reminders_disabled")

@Singleton
class DataStoreDeviceTokenStore @Inject constructor(
    @ApplicationContext private val context: Context,
) : DeviceTokenStore {

    override suspend fun getLastSentToken(): String? =
        context.deviceTokenDataStore.data.first()[LAST_SENT_TOKEN_KEY]

    override suspend fun setLastSentToken(token: String) {
        context.deviceTokenDataStore.edit { prefs -> prefs[LAST_SENT_TOKEN_KEY] = token }
    }

    override suspend fun clearLastSentToken() {
        context.deviceTokenDataStore.edit { prefs -> prefs.remove(LAST_SENT_TOKEN_KEY) }
    }

    override suspend fun isRemindersDisabled(): Boolean =
        context.deviceTokenDataStore.data.first()[REMINDERS_DISABLED_KEY] ?: false

    override suspend fun setRemindersDisabled(disabled: Boolean) {
        context.deviceTokenDataStore.edit { prefs -> prefs[REMINDERS_DISABLED_KEY] = disabled }
    }
}

/**
 * Real [FcmTokenProvider]: reads the current token from
 * `FirebaseMessaging.getInstance()`.
 *
 * Guarded by `FirebaseApp.getApps(context).isEmpty()` so the app still runs
 * (returning `null` here, which [PushRegistrar] treats as "nothing to do")
 * on a checkout without `google-services.json` — see Global Constraints:
 * the google-services plugin is applied conditionally in `app/build.gradle.kts`.
 */
class FirebaseFcmTokenProvider @Inject constructor(
    @ApplicationContext private val context: Context,
) : FcmTokenProvider {

    override suspend fun currentToken(): String? {
        if (FirebaseApp.getApps(context).isEmpty()) return null
        return suspendCancellableCoroutine { cont ->
            FirebaseMessaging.getInstance().token
                .addOnCompleteListener { task ->
                    cont.resume(if (task.isSuccessful) task.result else null)
                }
        }
    }
}

/**
 * Registers/deregisters this device's FCM token with the backend
 * (`POST /devices/register`, `DELETE /devices/{token}`).
 *
 * [ensureRegistered] is called after sign-in (see `AppNavViewModel`) and
 * [registerToken] directly from [MealsyMessagingService.onNewToken]. Both
 * are idempotent against [DeviceTokenStore]'s last-sent value, so calling
 * either repeatedly with the same token is a no-op after the first success.
 */
@Singleton
class PushRegistrar @Inject constructor(
    private val api: MealsyApi,
    private val tokenStore: DeviceTokenStore,
    private val fcmTokenProvider: FcmTokenProvider,
) {

    /**
     * Fetches the current FCM token (if any) and registers it if it hasn't
     * been sent yet — unless the user has turned reminders off in Settings
     * ([DeviceTokenStore.isRemindersDisabled]), in which case this is a
     * no-op. Without that check, this being called unconditionally after
     * every sign-in (see `AppNavViewModel`) would silently re-register the
     * token a Settings toggle-off just deleted.
     */
    suspend fun ensureRegistered() {
        if (tokenStore.isRemindersDisabled()) return
        val token = try {
            fcmTokenProvider.currentToken()
        } catch (exc: CancellationException) {
            throw exc
        } catch (exc: Exception) {
            null
        } ?: return
        registerToken(token)
    }

    /**
     * Registers [token] with the backend unless it's already the last one sent.
     *
     * Best-effort: a network failure is swallowed rather than crashing the
     * caller (sign-in flow or [MealsyMessagingService.onNewToken]) — the next
     * [ensureRegistered]/[registerToken] call retries.
     */
    suspend fun registerToken(token: String) {
        if (token == tokenStore.getLastSentToken()) return
        try {
            api.registerDevice(RegisterDeviceRequest(token = token))
            tokenStore.setLastSentToken(token)
        } catch (exc: CancellationException) {
            throw exc
        } catch (exc: Exception) {
            // Best-effort — retried on the next ensureRegistered()/onNewToken.
        }
    }

    /**
     * Best-effort `DELETE /devices/{token}` for the last-registered token,
     * called from [SignOutHook] before the session is cleared.
     */
    suspend fun unregisterCurrentDevice() {
        val token = tokenStore.getLastSentToken() ?: return
        try {
            api.deleteDevice(token)
        } catch (exc: CancellationException) {
            throw exc
        } catch (exc: Exception) {
            // Best-effort — SessionManager.signOut() must not fail because
            // deregistration failed (e.g. offline sign-out).
        }
        tokenStore.clearLastSentToken()
    }
}

/**
 * Wires [PushRegistrar.unregisterCurrentDevice] as `:core:data`'s [SignOutHook] seam.
 *
 * Takes a `Provider<PushRegistrar>` rather than `PushRegistrar` directly to
 * break a real Dagger dependency cycle: `ApiModule.provideOkHttpClient`
 * needs `TokenProvider` -> `SessionManager` -> (this) `SignOutHook` ->
 * `PushRegistrar` -> `MealsyApi` -> `Retrofit` -> the same `OkHttpClient`.
 * A `Provider` injection point defers `PushRegistrar`'s construction past
 * that cycle; `.get()` still returns the same `@Singleton` instance.
 */
class PushRegistrarSignOutHook @Inject constructor(
    private val pushRegistrarProvider: Provider<PushRegistrar>,
) : SignOutHook {
    override suspend fun onDeviceSignOut() =
        pushRegistrarProvider.get().unregisterCurrentDevice()
}

@Module
@InstallIn(SingletonComponent::class)
abstract class PushModule {

    @Binds
    abstract fun bindDeviceTokenStore(impl: DataStoreDeviceTokenStore): DeviceTokenStore

    @Binds
    abstract fun bindFcmTokenProvider(impl: FirebaseFcmTokenProvider): FcmTokenProvider

    @Binds
    abstract fun bindSignOutHook(impl: PushRegistrarSignOutHook): SignOutHook
}
