package app.mealsy.data.repo

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.first
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Persists [ChatRepository]'s active `conversation_id` across process death
 * so [ChatRepository.recoverPending] targets the same backend thread a
 * previous app instance was talking to, instead of a brand-new UUID that
 * never existed server-side.
 */
interface ConversationIdStore {
    suspend fun get(): String?

    suspend fun set(id: String)
}

private val Context.conversationIdDataStore: DataStore<Preferences> by
    preferencesDataStore(name = "chat_conversation")

private val CONVERSATION_ID_KEY = stringPreferencesKey("conversation_id")

@Singleton
class DataStoreConversationIdStore
    @Inject
    constructor(
        @ApplicationContext private val context: Context,
    ) : ConversationIdStore {
        override suspend fun get(): String? {
            return context.conversationIdDataStore.data.first()[CONVERSATION_ID_KEY]
        }

        override suspend fun set(id: String) {
            context.conversationIdDataStore.edit { prefs -> prefs[CONVERSATION_ID_KEY] = id }
        }
    }
