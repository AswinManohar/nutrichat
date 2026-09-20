package app.mealsy.data.offline

import javax.inject.Inject

/**
 * Persists a failed `POST /meals/log-items` payload for later replay.
 *
 * Abstracted behind an interface (rather than [ChatRepository][app.mealsy.data.repo.ChatRepository]
 * depending on [PendingLogDao]/`WorkManager` directly) so the repository stays
 * testable with plain fakes, independent of Room/WorkManager's Android
 * runtime dependencies.
 */
interface PendingLogQueue {
    /** Persists [payloadJson] keyed by [clientRequestId] and schedules a replay attempt. */
    suspend fun enqueue(
        clientRequestId: String,
        payloadJson: String,
    )
}

class RoomPendingLogQueue
    @Inject
    constructor(
        private val dao: PendingLogDao,
        private val workEnqueuer: ReplayWorkEnqueuer,
    ) : PendingLogQueue {
        override suspend fun enqueue(
            clientRequestId: String,
            payloadJson: String,
        ) {
            dao.insert(
                PendingLogEntity(
                    clientRequestId = clientRequestId,
                    payloadJson = payloadJson,
                    createdAt = System.currentTimeMillis(),
                ),
            )
            workEnqueuer.enqueueReplay()
        }
    }

/**
 * Thin seam around `WorkManager.enqueueUniqueWork` so [RoomPendingLogQueue]
 * doesn't need a direct `WorkManager` dependency in tests.
 */
interface ReplayWorkEnqueuer {
    fun enqueueReplay()
}
