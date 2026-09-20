package app.mealsy.android.ui.common

/**
 * Shared vocabulary for the error states a ViewModel exposes in its UI
 * state.
 *
 * ViewModels never carry a user-facing English string directly (no
 * `Error(val message: String)`) — only an [ErrorKind]. The composable that
 * renders the error state resolves the actual copy via `stringResource`,
 * which keeps strings localizable and keeps ViewModel unit tests asserting
 * on a stable kind rather than on English prose.
 *
 * Two kinds cover every load-failure screen in the app:
 * - [Offline]: the request failed with an [java.io.IOException] (no
 *   connectivity, timeout, DNS, etc.). Every screen shows the same shared
 *   copy for this — see `R.string.error_offline`.
 * - [LoadFailed]: any other failure. The message differs per screen (e.g.
 *   "Something went wrong loading your meals." vs. "...this meal."), so
 *   each screen supplies its own string resource for it (e.g.
 *   `R.string.meal_detail_error_load_failed`,
 *   `R.string.trends_error_load_failed`) rather than this sealed interface
 *   trying to enumerate one kind per screen.
 *
 * Screens with their own domain-specific errors (e.g. login's email
 * validation and auth failures) define their own sealed kind instead of
 * extending this one — see `LoginErrorKind`.
 */
sealed interface ErrorKind {
    /** The request failed because the device has no usable connection. */
    data object Offline : ErrorKind

    /** The request failed for any other reason; the screen supplies its own message. */
    data object LoadFailed : ErrorKind
}
