package app.mealsy.data.offline

import android.content.Context
import android.util.Log
import androidx.hilt.work.HiltWorker
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import app.mealsy.data.api.LogItemsRequest
import app.mealsy.data.api.MealsyApi
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlinx.serialization.json.Json
import retrofit2.HttpException

/**
 * Replays queued `POST /meals/log-items` payloads (see [PendingLogEntity])
 * once the device is back online.
 *
 * Per row: a successful response (2xx — Retrofit throws [HttpException] for
 * anything else, whether or not the server reports `deduplicated=true`)
 * deletes the row. A client error other than 429/408 (most notably 422 —
 * the payload itself is malformed and will never succeed; a poison message)
 * also deletes the row, after logging it. An [IOException], a 5xx, or a
 * 429/408 increments the attempt count and leaves the row for a later run,
 * with the whole worker returning [Result.retry] so WorkManager's exponential
 * backoff (configured in [enqueue]) applies. A row is given up on — deleted,
 * with a warning logged — once it has been attempted [MAX_ATTEMPTS] times or
 * is older than [MAX_AGE_MS], regardless of the error.
 */
@HiltWorker
class ReplayWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val dao: PendingLogDao,
    private val api: MealsyApi,
    private val json: Json,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        var anyRetryable = false

        for (row in dao.getAll()) {
            val age = System.currentTimeMillis() - row.createdAt
            if (row.attempts >= MAX_ATTEMPTS || age >= MAX_AGE_MS) {
                Log.w(
                    TAG,
                    "Giving up on pending log ${row.clientRequestId} " +
                        "after ${row.attempts} attempts (age ${age}ms)",
                )
                dao.delete(row.clientRequestId)
                continue
            }

            val request = try {
                json.decodeFromString(LogItemsRequest.serializer(), row.payloadJson)
            } catch (exc: Exception) {
                Log.e(TAG, "Corrupt pending log payload ${row.clientRequestId}, discarding", exc)
                dao.delete(row.clientRequestId)
                continue
            }

            try {
                api.logItems(request)
                dao.delete(row.clientRequestId)
            } catch (exc: IOException) {
                dao.incrementAttempts(row.clientRequestId)
                anyRetryable = true
            } catch (exc: HttpException) {
                val code = exc.code()
                if (code == 429 || code == 408 || code >= 500) {
                    dao.incrementAttempts(row.clientRequestId)
                    anyRetryable = true
                } else {
                    Log.e(
                        TAG,
                        "Pending log ${row.clientRequestId} rejected with HTTP $code, " +
                            "discarding (poison payload)",
                        exc,
                    )
                    dao.delete(row.clientRequestId)
                }
            }
        }

        return if (anyRetryable) Result.retry() else Result.success()
    }

    companion object {
        const val WORK_NAME = "replay-pending-logs"
        const val MAX_ATTEMPTS = 50
        val MAX_AGE_MS: Long = TimeUnit.DAYS.toMillis(7)
        private const val TAG = "ReplayWorker"

        /** Enqueues (or leaves in place) the unique [WORK_NAME] replay job. */
        fun enqueue(workManager: WorkManager) {
            val request = OneTimeWorkRequestBuilder<ReplayWorker>()
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build(),
                )
                .setBackoffCriteria(
                    BackoffPolicy.EXPONENTIAL,
                    30,
                    TimeUnit.SECONDS,
                )
                .build()
            workManager.enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.KEEP, request)
        }
    }
}
