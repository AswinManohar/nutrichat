package app.mealsy.android.error

import android.content.Context
import app.mealsy.data.error.ErrorReporter
import app.mealsy.data.offline.ReplayFailureReporter
import com.google.firebase.FirebaseApp
import com.google.firebase.crashlytics.FirebaseCrashlytics
import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Seam over `FirebaseApp.getApps(context).isEmpty()` — the same no-Firebase
 * guard [app.mealsy.android.push.PushRegistrar]'s `FirebaseFcmTokenProvider`
 * uses — isolated so [ErrorReportingTest] can exercise both the "no
 * Firebase" and "Firebase present" branches of [ErrorReporting.record]
 * without depending on FirebaseApp's real static state or standing up a
 * real Crashlytics SDK in a JVM test.
 */
fun interface FirebaseAppsPresence {
    fun hasApps(): Boolean
}

class RealFirebaseAppsPresence @Inject constructor(
    @ApplicationContext private val context: Context,
) : FirebaseAppsPresence {
    override fun hasApps(): Boolean = FirebaseApp.getApps(context).isNotEmpty()
}

/**
 * The actual Crashlytics SDK call, isolated behind an interface for the same
 * testability reason as [FirebaseAppsPresence] — [ErrorReportingTest] can
 * verify it's invoked (or not) without a live `FirebaseCrashlytics` instance,
 * which requires a real Firebase app and native init that don't run cleanly
 * under Robolectric/JUnit.
 */
fun interface CrashRecorder {
    fun record(t: Throwable, keys: Map<String, String>)
}

class FirebaseCrashRecorder @Inject constructor() : CrashRecorder {
    override fun record(t: Throwable, keys: Map<String, String>) {
        val crashlytics = FirebaseCrashlytics.getInstance()
        keys.forEach { (key, value) -> crashlytics.setCustomKey(key, value) }
        crashlytics.recordException(t)
    }
}

/**
 * Crashlytics wrapper: records a non-fatal [Throwable] (optionally with
 * custom keys for context, e.g. `client_request_id`) unless the app has no
 * `google-services.json` configured — [appsPresence] mirrors the guard
 * `PushRegistrar`'s FCM token provider uses for the exact same reason (a
 * checkout without Firebase set up must still build and run; see Global
 * Constraints and `app/build.gradle.kts`'s conditional plugin application).
 *
 * Bound as [app.mealsy.data.error.ErrorReporter] for `:core:data` callers
 * (currently `SessionManager`'s two best-effort swallow paths) via
 * [ErrorReportingModule].
 */
@Singleton
class ErrorReporting @Inject constructor(
    private val appsPresence: FirebaseAppsPresence,
    private val recorder: CrashRecorder,
) {
    fun record(t: Throwable, keys: Map<String, String> = emptyMap()) {
        if (!appsPresence.hasApps()) return
        recorder.record(t, keys)
    }
}

/**
 * Real [ReplayFailureReporter]: records the drop into Crashlytics with the
 * `client_request_id`/`reason` as custom keys, so a spike in
 * `ReplayWorker`-dropped logs is visible without depending on device logs.
 */
class RealReplayFailureReporter @Inject constructor(
    private val errorReporting: ErrorReporting,
) : ReplayFailureReporter {
    override fun report(clientRequestId: String, reason: String) {
        errorReporting.record(
            IllegalStateException("ReplayWorker dropped a queued meal log: $reason"),
            mapOf("client_request_id" to clientRequestId, "reason" to reason),
        )
    }
}

@Module
@InstallIn(SingletonComponent::class)
abstract class ErrorReportingModule {

    @Binds
    abstract fun bindFirebaseAppsPresence(impl: RealFirebaseAppsPresence): FirebaseAppsPresence

    @Binds
    abstract fun bindCrashRecorder(impl: FirebaseCrashRecorder): CrashRecorder

    @Binds
    abstract fun bindReplayFailureReporter(impl: RealReplayFailureReporter): ReplayFailureReporter

    companion object {
        /** Adapts [ErrorReporting] to `:core:data`'s narrower [ErrorReporter] seam. */
        @Provides
        @Singleton
        fun provideCoreErrorReporter(errorReporting: ErrorReporting): ErrorReporter =
            ErrorReporter { t -> errorReporting.record(t) }
    }
}
