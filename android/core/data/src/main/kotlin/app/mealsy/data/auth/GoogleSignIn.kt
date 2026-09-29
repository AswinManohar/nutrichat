package app.mealsy.data.auth

import android.app.Activity
import io.github.jan.supabase.gotrue.exception.AuthRestException
import kotlinx.coroutines.CancellationException
import java.io.IOException
import java.security.MessageDigest
import java.security.SecureRandom

/** Why a native Google sign-in did not produce a session (#32). */
enum class GoogleSignInError {
    /** The user dismissed the account picker. Callers show nothing. */
    Cancelled,

    /** No Google account is signed in on this device. */
    NoAccount,

    /** `GOOGLE_WEB_CLIENT_ID` is blank in this build. */
    NotConfigured,

    /** Supabase rejected the ID token because the Google provider is off. */
    ProviderDisabled,

    /** The device could not reach Supabase. */
    Network,

    /** Anything else. */
    Failed,
}

/** Thrown by [GoogleSignIn] with a [GoogleSignInError] the UI can map to copy. */
class GoogleSignInException(
    val error: GoogleSignInError,
    cause: Throwable? = null,
) : Exception("Google sign-in failed: $error", cause)

/**
 * Seam over Credential Manager: asks the user to pick a Google account and
 * returns a Google ID token whose `nonce` claim is [hashedNonce].
 *
 * Implementations throw [GoogleSignInException] for every failure.
 */
interface GoogleCredentialSource {
    suspend fun requestIdToken(
        activity: Activity,
        serverClientId: String,
        hashedNonce: String,
    ): String
}

/** Seam over supabase-kt's `signInWith(IDToken)` so [GoogleSignIn] stays a plain JVM unit. */
fun interface IdTokenSignIn {
    suspend fun signIn(
        idToken: String,
        rawNonce: String,
    )
}

/**
 * Native Google sign-in: Credential Manager ID token -> Supabase session.
 *
 * A fresh random nonce is generated per attempt. Google receives its SHA-256
 * hex digest (so it lands in the token's `nonce` claim); Supabase receives
 * the raw value and re-hashes it to verify the claim, which stops a stolen
 * token from being replayed.
 */
class GoogleSignIn(
    private val credentialSource: GoogleCredentialSource,
    private val idTokenSignIn: IdTokenSignIn,
    private val serverClientId: String,
    private val nonceFactory: () -> String = ::generateRawNonce,
) {
    /**
     * Runs the whole flow.
     *
     * @throws GoogleSignInException on any failure, including user cancel.
     */
    suspend fun signIn(activity: Activity) {
        if (serverClientId.isBlank()) throw GoogleSignInException(GoogleSignInError.NotConfigured)
        val rawNonce = nonceFactory()
        val idToken = credentialSource.requestIdToken(activity, serverClientId, sha256Hex(rawNonce))
        try {
            idTokenSignIn.signIn(idToken, rawNonce)
        } catch (exc: CancellationException) {
            throw exc
        } catch (exc: GoogleSignInException) {
            throw exc
        } catch (exc: Exception) {
            throw GoogleSignInException(mapSupabaseFailure(exc), exc)
        }
    }
}

/** Maps a failure from Supabase's ID-token exchange to a [GoogleSignInError]. */
internal fun mapSupabaseFailure(exc: Exception): GoogleSignInError =
    when {
        exc is AuthRestException &&
            exc.statusCode == 400 &&
            exc.description.orEmpty().contains("provider is not enabled", ignoreCase = true) ->
            GoogleSignInError.ProviderDisabled
        exc is AuthRestException &&
            exc.error.contains("provider is not enabled", ignoreCase = true) ->
            GoogleSignInError.ProviderDisabled
        exc is IOException -> GoogleSignInError.Network
        exc.cause is IOException -> GoogleSignInError.Network
        exc.javaClass.name.endsWith("HttpRequestException") -> GoogleSignInError.Network
        else -> GoogleSignInError.Failed
    }

private const val NONCE_BYTES = 32

/** 32 random bytes as lowercase hex. */
internal fun generateRawNonce(): String {
    val bytes = ByteArray(NONCE_BYTES).also { SecureRandom().nextBytes(it) }
    return bytes.joinToString("") { "%02x".format(it) }
}

/** SHA-256 of [input] as lowercase hex, the form Supabase expects for the nonce claim. */
internal fun sha256Hex(input: String): String =
    MessageDigest.getInstance("SHA-256")
        .digest(input.toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it) }
