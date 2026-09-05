package app.mealsy.android.ui.chat

import app.mealsy.data.repo.ConversationIdStore

/** In-memory [ConversationIdStore] for ChatViewModel tests — no DataStore/Robolectric needed. */
private class FakeConversationIdStore : ConversationIdStore {
    private var value: String? = null

    override suspend fun get(): String? = value

    override suspend fun set(id: String) {
        value = id
    }
}

internal fun fakeConversationIdStore(): ConversationIdStore = FakeConversationIdStore()
