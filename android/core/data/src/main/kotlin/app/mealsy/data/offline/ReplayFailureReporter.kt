package app.mealsy.data.offline

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.first
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Seam over Crashlytics reporting for [ReplayWorker]'s two silent-data-loss
 * paths (poison-delete on a 4xx, give-up past [ReplayWorker.MAX_ATTEMPTS]/
 * [ReplayWorker.MAX_AGE_MS]) — `:core:data` cannot depend on `:app`, where
 * the real Crashlytics wrapper (`app.mealsy.android.error.ErrorReporting`)
 * lives, so `:app` supplies the real binding (same pattern as
 * [app.mealsy.data.auth.SignOutHook]). [reason] is a short, stable tag
 * (e.g. `"poison:422"`, `"give-up:attempts"`) rather than free text, so
 * Crashlytics custom keys stay low-cardinality.
 */
fun interface ReplayFailureReporter {
    fun report(clientRequestId: String, reason: String)
}

/**
 * Whether a queued meal log was ever silently dropped (poison-deleted or
 * given up on) by [ReplayWorker], for [app.mealsy.android.ui.chat.ChatViewModel]
 * to surface once as a chat notice. Entirely within `:core:data` (unlike
 * [ReplayFailureReporter]) since it's just a persisted flag — no Crashlytics
 * dependency needed to write or read it.
 *
 * [consumeDropped] both reads and clears the flag atomically-enough for this
 * use (single-writer-at-a-time DataStore edit) so the notice surfaces
 * exactly once, not on every `ChatViewModel` init thereafter.
 */
interface DroppedLogStore {
    suspend fun markDropped()
    suspend fun consumeDropped(): Boolean
}

private val Context.droppedLogDataStore: DataStore<Preferences> by
    preferencesDataStore(name = "dropped_pending_log")

private val DROPPED_KEY = booleanPreferencesKey("has_dropped_log")

@Singleton
class DataStoreDroppedLogStore @Inject constructor(
    @ApplicationContext private val context: Context,
) : DroppedLogStore {

    override suspend fun markDropped() {
        context.droppedLogDataStore.edit { prefs -> prefs[DROPPED_KEY] = true }
    }

    override suspend fun consumeDropped(): Boolean {
        val wasDropped = context.droppedLogDataStore.data.first()[DROPPED_KEY] ?: false
        if (wasDropped) {
            context.droppedLogDataStore.edit { prefs -> prefs[DROPPED_KEY] = false }
        }
        return wasDropped
    }
}
