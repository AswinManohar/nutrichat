package app.mealsy.data.offline

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * A `POST /meals/log-items` payload that could not be sent because the
 * device was offline, persisted so [ReplayWorker] can retry it later.
 *
 * [clientRequestId] is the primary key and is the exact same id that was
 * sent (and may or may not have been received) on the failed attempt — the
 * backend's dedup-on-`client_request_id` contract is what makes a later
 * successful replay of [payloadJson] safe even if the original attempt
 * actually landed server-side.
 */
@Entity(tableName = "pending_logs")
data class PendingLogEntity(
    @PrimaryKey val clientRequestId: String,
    val payloadJson: String,
    val createdAt: Long,
    val attempts: Int = 0,
)
