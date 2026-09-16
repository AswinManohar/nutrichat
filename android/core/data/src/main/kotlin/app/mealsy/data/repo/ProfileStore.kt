package app.mealsy.data.repo

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

/** Locally cached copy of the Supabase user-metadata profile (plan Assumption 1). */
data class Profile(val firstName: String? = null, val goalFocus: String? = null)

/**
 * Local mirror of the `first_name`/`goal_focus` Supabase user-metadata
 * fields onboarding writes (plan Assumption 1), so the app can render a
 * personalized greeting offline / before the next metadata fetch completes,
 * without waiting on a network round trip.
 *
 * Modelled on [ConversationIdStore] — a thin DataStore-backed cache, not the
 * source of truth (Supabase user metadata is).
 */
interface ProfileStore {
    /** Emits the cached profile, starting with whatever is on disk. */
    val profile: Flow<Profile>

    suspend fun get(): Profile

    /**
     * Writes [firstName]/[goalFocus] into the cache. A `null` argument
     * leaves the corresponding stored key unchanged, rather than clearing
     * it — a metadata refresh that only carries one of the two fields
     * (e.g. a partial [app.mealsy.data.auth.ProfileMetadata]) must not wipe
     * out the other one already on disk. Use [clear] to remove both.
     */
    suspend fun set(firstName: String?, goalFocus: String?)

    /** Removes both cached fields. */
    suspend fun clear()
}

private val Context.profileDataStore: DataStore<Preferences> by
    preferencesDataStore(name = "profile")

private val FIRST_NAME_KEY = stringPreferencesKey("first_name")
private val GOAL_FOCUS_KEY = stringPreferencesKey("goal_focus")

@Singleton
class DataStoreProfileStore @Inject constructor(
    @ApplicationContext private val context: Context,
) : ProfileStore {

    override val profile: Flow<Profile> =
        context.profileDataStore.data.map { prefs ->
            Profile(firstName = prefs[FIRST_NAME_KEY], goalFocus = prefs[GOAL_FOCUS_KEY])
        }

    override suspend fun get(): Profile = profile.first()

    override suspend fun set(firstName: String?, goalFocus: String?) {
        context.profileDataStore.edit { prefs ->
            if (firstName != null) prefs[FIRST_NAME_KEY] = firstName
            if (goalFocus != null) prefs[GOAL_FOCUS_KEY] = goalFocus
        }
    }

    override suspend fun clear() {
        context.profileDataStore.edit { prefs ->
            prefs.remove(FIRST_NAME_KEY)
            prefs.remove(GOAL_FOCUS_KEY)
        }
    }
}
