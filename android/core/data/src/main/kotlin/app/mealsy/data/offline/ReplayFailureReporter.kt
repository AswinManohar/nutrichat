package app.mealsy.data.offline

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Seam over Crashlytics reporting for [ReplayWorker]'s two silent-data-loss
 * paths (poison-delete on a 4xx, give-up past [ReplayWorker.MAX_ATTEMPTS]/
 * [ReplayWorker.MAX_AGE_MS]) — `:core:data` cannot depend on `:app`, where
 * the real Crashlytics wrapper (`app.mealsy.android.error.ErrorReporting`)
 * lives, so `:app` supplies the real binding (same pattern as
 * [app.mealsy.data.auth.SignOutHook]). [reason] is a short, stable tag
 * (e.g. `"poison:422"`, `"give-up:attempts=50"`, `"give-up:age"`) rather
 * than free text, so Crashlytics custom keys stay low-cardinality.
 */
fun interface ReplayFailureReporter {
    fun report(
        clientRequestId: String,
        reason: String,
    )
}

/**
 * How many queued meal logs have been silently dropped (poison-deleted or
 * given up on) by [ReplayWorker] since the last time
 * [app.mealsy.android.ui.chat.ChatViewModel] surfaced (and cleared) the
 * count as a chat notice. Entirely within `:core:data` (unlike
 * [ReplayFailureReporter]) since it's just a persisted counter — no
 * Crashlytics dependency needed to write or read it.
 *
 * A count (not a boolean) so the notice can say "2 queued meals" rather than
 * collapsing multiple drops into one generic message.
 *
 * [consumeDropped] reads and clears the counter inside a single
 * `DataStore.edit {}` block, so a `markDropped()` racing a `consumeDropped()`
 * (e.g. a second `ReplayWorker` run overlapping `ChatViewModel` startup)
 * can't land its increment between a separate read and a separate clear and
 * get silently lost — `edit {}` serializes concurrent transforms of the same
 * DataStore.
 */
interface DroppedLogStore {
    suspend fun markDropped()

    /** Returns however many drops had accumulated, clearing the counter to 0. */
    suspend fun consumeDropped(): Int
}

private val Context.droppedLogDataStore: DataStore<Preferences> by
    preferencesDataStore(name = "dropped_pending_log")

private val DROPPED_COUNT_KEY = intPreferencesKey("dropped_log_count")

@Singleton
class DataStoreDroppedLogStore
    @Inject
    constructor(
        @ApplicationContext private val context: Context,
    ) : DroppedLogStore {
        override suspend fun markDropped() {
            context.droppedLogDataStore.edit { prefs ->
                prefs[DROPPED_COUNT_KEY] = (prefs[DROPPED_COUNT_KEY] ?: 0) + 1
            }
        }

        override suspend fun consumeDropped(): Int {
            var count = 0
            context.droppedLogDataStore.edit { prefs ->
                count = prefs[DROPPED_COUNT_KEY] ?: 0
                prefs[DROPPED_COUNT_KEY] = 0
            }
            return count
        }
    }
