package app.mealsy.data.repo

/** In-memory [ConversationIdStore] standing in for DataStore across repository instances. */
class FakeConversationIdStore : ConversationIdStore {
    private var value: String? = null

    override suspend fun get(): String? = value

    override suspend fun set(id: String) {
        value = id
    }
}
