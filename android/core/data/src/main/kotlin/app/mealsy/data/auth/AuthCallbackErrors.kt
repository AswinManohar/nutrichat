package app.mealsy.data.auth

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import java.net.URLDecoder
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Coarse kind of an `error`/`error_code` Supabase puts on the
 * `mealsy://auth-callback` deep link (#34). [LoginViewModel]
 * [app.mealsy.android.ui.login.LoginViewModel] maps this down to its own
 * [app.mealsy.android.ui.login.LoginErrorKind] for display.
 */
enum class AuthCallbackErrorKind {
    /** `otp_expired` — the magic link was already used or its TTL elapsed. */
    LINK_EXPIRED_OR_USED,

    /** `over_email_send_rate_limit` (also seen as an HTTP 429 body). */
    RATE_LIMITED,

    /** Any other `error`/`error_code` Supabase might send. */
    OTHER,
}

/** A parsed auth-callback error, kept generic enough to log if needed. */
data class AuthCallbackError(
    val kind: AuthCallbackErrorKind,
    val errorCode: String?,
    val description: String?,
)

/**
 * Publishes auth-callback deep-link errors from
 * [MainActivity][app.mealsy.android.MainActivity] — which owns the raw
 * `Intent` handed to it by the OS — to
 * [LoginViewModel][app.mealsy.android.ui.login.LoginViewModel], which owns
 * the login screen's UI state and has no reason to know about `Intent`.
 *
 * A `SharedFlow` with no replay (rather than the `StateFlow` pattern used
 * elsewhere in this package) so an error already shown to the user doesn't
 * replay into a new `LoginViewModel` created later (e.g. after the user
 * dismisses it and navigates away and back). `extraBufferCapacity = 1` lets
 * [publish] succeed via `tryEmit` from `MainActivity`'s UI thread even
 * before `LoginViewModel` has started collecting.
 */
@Singleton
class AuthCallbackErrors
    @Inject
    constructor() {
        private val _errors = MutableSharedFlow<AuthCallbackError>(extraBufferCapacity = 1)
        val errors: SharedFlow<AuthCallbackError> = _errors

        fun publish(error: AuthCallbackError) {
            _errors.tryEmit(error)
        }
    }

/**
 * Parses `error` / `error_code` / `error_description` off a
 * `mealsy://auth-callback` deep link, checking both the query string and
 * the fragment.
 *
 * supabase-kt's PKCE flow (which this app uses, see `AuthModule`) puts these
 * on the query string, but Supabase's own redirect for some failures
 * (notably an expired/reused `otp_expired` link, which never reaches the
 * PKCE code-exchange step) uses the fragment instead — the same place the
 * legacy implicit flow puts `access_token`. Checking both keeps this
 * correct regardless of which path produced the error.
 *
 * Returns null when neither part carries an `error` param — i.e. this is a
 * normal, successful callback that `handleDeeplinks` already handles.
 *
 * @param uri The raw deep-link URI, e.g. as `Intent.data.toString()`.
 */
fun parseAuthCallbackError(uri: String): AuthCallbackError? {
    val queryPart = uri.substringAfter('?', missingDelimiterValue = "").substringBefore('#')
    val fragmentPart = uri.substringAfter('#', missingDelimiterValue = "")

    // Fragment params win on a key present in both — Supabase never sends
    // the same key in both places in practice, but if it did, the fragment
    // is the newer implicit-flow-style location and the more likely to be
    // authoritative for an error redirect.
    val params = parseParams(queryPart) + parseParams(fragmentPart)

    val error = params["error"] ?: return null
    val errorCode = params["error_code"]
    val description = params["error_description"]

    val kind =
        when (errorCode ?: error) {
            "otp_expired" -> AuthCallbackErrorKind.LINK_EXPIRED_OR_USED
            "over_email_send_rate_limit" -> AuthCallbackErrorKind.RATE_LIMITED
            else -> AuthCallbackErrorKind.OTHER
        }

    return AuthCallbackError(kind = kind, errorCode = errorCode, description = description)
}

/** Parses a `key=value&key2=value2`-shaped string (no leading `?`/`#`) into a map. */
private fun parseParams(part: String): Map<String, String> {
    if (part.isEmpty()) return emptyMap()
    return part
        .split('&')
        .mapNotNull { pair ->
            if (pair.isEmpty()) return@mapNotNull null
            val key = pair.substringBefore('=')
            val value = pair.substringAfter('=', missingDelimiterValue = "")
            key.decodeUriComponentOrSelf() to value.decodeUriComponentOrSelf()
        }.toMap()
}

private fun String.decodeUriComponentOrSelf(): String =
    try {
        URLDecoder.decode(this, "UTF-8")
    } catch (exc: IllegalArgumentException) {
        this
    }
