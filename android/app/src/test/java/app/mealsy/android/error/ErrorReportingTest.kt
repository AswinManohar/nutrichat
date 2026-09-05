package app.mealsy.android.error

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Exercises [ErrorReporting.record] against fakes for [FirebaseAppsPresence]
 * and [CrashRecorder] — a real `FirebaseCrashlytics.getInstance()` needs a
 * live Firebase app and native init that don't run cleanly in a plain JUnit
 * test, same rationale as [app.mealsy.android.push.PushRegistrarTest] faking
 * `FcmTokenProvider` instead of touching `FirebaseMessaging` directly.
 */
class ErrorReportingTest {

    private class RecordingCrashRecorder : CrashRecorder {
        val calls = mutableListOf<Pair<Throwable, Map<String, String>>>()
        override fun record(t: Throwable, keys: Map<String, String>) {
            calls += t to keys
        }
    }

    @Test
    fun `no-ops without Firebase configured`() {
        val recorder = RecordingCrashRecorder()
        val reporting = ErrorReporting(
            appsPresence = FirebaseAppsPresence { false },
            recorder = recorder,
        )

        reporting.record(IllegalStateException("boom"))

        assertTrue(recorder.calls.isEmpty())
    }

    @Test
    fun `records the exception and keys when Firebase is configured`() {
        val recorder = RecordingCrashRecorder()
        val reporting = ErrorReporting(
            appsPresence = FirebaseAppsPresence { true },
            recorder = recorder,
        )
        val exc = IllegalStateException("boom")

        reporting.record(exc, mapOf("client_request_id" to "req-1"))

        assertEquals(1, recorder.calls.size)
        assertEquals(exc, recorder.calls[0].first)
        assertEquals(mapOf("client_request_id" to "req-1"), recorder.calls[0].second)
    }

    @Test
    fun `a recorder that throws does not escape record`() {
        val reporting = ErrorReporting(
            appsPresence = FirebaseAppsPresence { true },
            recorder = CrashRecorder { _, _ -> throw IllegalStateException("Crashlytics not configured") },
        )

        // Must return normally — see ErrorReporting's doc comment: this is
        // called from SessionManager.currentToken's 401-retry path
        // (runBlocking inside an OkHttp interceptor) and from ReplayWorker
        // right before dao.delete, where a thrown exception here would
        // become an actual crash or abort a queue cleanup, not just a
        // missed non-fatal report.
        reporting.record(IllegalStateException("boom"))
    }

    @Test
    fun `keys default to empty`() {
        val recorder = RecordingCrashRecorder()
        val reporting = ErrorReporting(
            appsPresence = FirebaseAppsPresence { true },
            recorder = recorder,
        )

        reporting.record(IllegalStateException("boom"))

        assertEquals(emptyMap<String, String>(), recorder.calls.single().second)
    }
}
