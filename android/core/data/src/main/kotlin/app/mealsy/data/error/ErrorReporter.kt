package app.mealsy.data.error

/**
 * Seam for recording a non-fatal failure into Crashlytics from `:core:data`
 * code (currently [app.mealsy.data.auth.SessionManager]'s two best-effort
 * swallow paths). `:core:data` cannot depend on `:app`, where the real
 * Crashlytics wrapper (`app.mealsy.android.error.ErrorReporting`) lives, so
 * `:app` supplies the real binding — same pattern as
 * [app.mealsy.data.auth.SignOutHook] and
 * [app.mealsy.data.offline.ReplayFailureReporter]. Defaults to a no-op
 * (`ErrorReporter {}`) at call sites that don't wire one through Hilt, e.g.
 * plain-constructor test fakes.
 */
fun interface ErrorReporter {
    fun record(t: Throwable)
}
