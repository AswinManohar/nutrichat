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
import app.mealsy.data.repo.TodayRefreshSignal
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.Json
import retrofit2.HttpException
import java.io.IOException
import java.util.concurrent.TimeUnit

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
 *
 * Both silent-data-loss paths (poison-delete and give-up) call
 * [ReplayFailureReporter.report] (Crashlytics in production, so an
 * unexpectedly high drop rate is visible) and [DroppedLogStore.markDropped]
 * (so [app.mealsy.android.ui.chat.ChatViewModel] can surface a one-time
 * "a queued meal couldn't be synced" notice in the chat transcript) — a row
 * silently vanishing from the user's perspective was the gap this closes.
 * The corrupt-payload-decode path just above is left as `Log.e`-only: a
 * malformed local `payloadJson` blob is a bug in what this device itself
 * wrote, not a meal ever meaningfully "in flight" from the user's point of
 * view (it never reached even the request-building stage on a real attempt).
 *
 * [doWork] re-queries [PendingLogDao.getAll] in a loop (tracking which
 * `clientRequestId`s it has already processed this run) rather than reading
 * the table once: `ExistingWorkPolicy.KEEP` means a confirm that queues a
 * row while a replay run is already in flight does NOT get a follow-up
 * `enqueue` — without the loop that row would sit unprocessed until some
 * *other* future replay run happens to fire.
 */
@HiltWorker
class ReplayWorker
    @AssistedInject
    constructor(
        @Assisted context: Context,
        @Assisted params: WorkerParameters,
        private val dao: PendingLogDao,
        private val api: MealsyApi,
        private val json: Json,
        private val failureReporter: ReplayFailureReporter,
        private val droppedLogStore: DroppedLogStore,
        private val todayRefreshSignal: TodayRefreshSignal,
    ) : CoroutineWorker(context, params) {
        override suspend fun doWork(): Result {
            var anyRetryable = false
            val processed = mutableSetOf<String>()

            // Loop until a pass finds nothing new: a row queued by a confirm
            // that races with this run (see the class doc) must still be picked
            // up in the SAME run, since ExistingWorkPolicy.KEEP means no
            // follow-up run is guaranteed to happen otherwise.
            while (true) {
                val rows = dao.getAll().filterNot { it.clientRequestId in processed }
                if (rows.isEmpty()) break

                for (row in rows) {
                    processed += row.clientRequestId
                    val age = System.currentTimeMillis() - row.createdAt
                    if (row.attempts >= MAX_ATTEMPTS || age >= MAX_AGE_MS) {
                        Log.w(
                            TAG,
                            "Giving up on pending log ${row.clientRequestId} " +
                                "after ${row.attempts} attempts (age ${age}ms)",
                        )
                        // Distinguish which condition tripped — a spike in
                        // "give-up:age" (a device offline for a full week) reads
                        // very differently from "give-up:attempts" (a request
                        // that keeps failing every retry).
                        val reason = if (age >= MAX_AGE_MS) "give-up:age" else "give-up:attempts=${row.attempts}"
                        notifyDropped(row.clientRequestId, reason)
                        dao.delete(row.clientRequestId)
                        continue
                    }

                    val request =
                        try {
                            json.decodeFromString(LogItemsRequest.serializer(), row.payloadJson)
                        } catch (exc: Exception) {
                            Log.e(
                                TAG,
                                "Corrupt pending log payload ${row.clientRequestId}, discarding",
                                exc,
                            )
                            dao.delete(row.clientRequestId)
                            continue
                        }

                    try {
                        api.logItems(request)
                        dao.delete(row.clientRequestId)
                        todayRefreshSignal.notifyLogged()
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
                            notifyDropped(row.clientRequestId, "poison:$code")
                            dao.delete(row.clientRequestId)
                        }
                    }
                }
            }

            return if (anyRetryable) Result.retry() else Result.success()
        }

        /**
         * Best-effort: calls [failureReporter]/[droppedLogStore] for a
         * silent-data-loss row, but a failure in either (e.g. Crashlytics
         * misconfigured, DataStore I/O error) must not prevent [dao.delete] —
         * losing the *reporting* of a drop is much less bad than aborting
         * `doWork` and leaving the row (which is never going to succeed) stuck
         * in the queue forever.
         */
        private suspend fun notifyDropped(
            clientRequestId: String,
            reason: String,
        ) {
            try {
                failureReporter.report(clientRequestId, reason)
                droppedLogStore.markDropped()
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                Log.w(TAG, "Failed to report/mark dropped log $clientRequestId ($reason)", exc)
            }
        }

        companion object {
            const val WORK_NAME = "replay-pending-logs"
            const val MAX_ATTEMPTS = 50
            val MAX_AGE_MS: Long = TimeUnit.DAYS.toMillis(7)
            private const val TAG = "ReplayWorker"

            /** Enqueues (or leaves in place) the unique [WORK_NAME] replay job. */
            fun enqueue(workManager: WorkManager) {
                val request =
                    OneTimeWorkRequestBuilder<ReplayWorker>()
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
