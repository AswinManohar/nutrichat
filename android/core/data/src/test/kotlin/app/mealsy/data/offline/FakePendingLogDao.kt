package app.mealsy.data.offline

/** In-memory [PendingLogDao] fake — no Room/SQLite involved. */
class FakePendingLogDao : PendingLogDao {
    private val rows = LinkedHashMap<String, PendingLogEntity>()

    fun seed(entity: PendingLogEntity) {
        rows[entity.clientRequestId] = entity
    }

    override suspend fun insert(entity: PendingLogEntity) {
        rows[entity.clientRequestId] = entity
    }

    override suspend fun getAll(): List<PendingLogEntity> = rows.values.toList()

    override suspend fun delete(clientRequestId: String) {
        rows.remove(clientRequestId)
    }

    override suspend fun incrementAttempts(clientRequestId: String) {
        rows[clientRequestId]?.let { rows[clientRequestId] = it.copy(attempts = it.attempts + 1) }
    }
}
