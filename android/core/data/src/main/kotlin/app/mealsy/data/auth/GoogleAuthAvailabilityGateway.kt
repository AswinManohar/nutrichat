package app.mealsy.data.auth

import app.mealsy.android.data.BuildConfig
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Request
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Reports whether Supabase's Google OAuth provider is enabled for this
 * project (#32) — the login screen hides/disables "Continue with Google"
 * when it isn't, rather than sending the user to a Supabase 400 JSON page.
 *
 * Deliberately its own tiny OkHttp client rather than the Retrofit
 * [app.mealsy.data.api.MealsyApi] client: that client points at the Mealsy
 * backend and its `AuthInterceptor` attaches a Supabase *user* bearer
 * token, neither of which apply to Supabase's own `/auth/v1/settings`
 * endpoint (unauthenticated, keyed by the project's anon `apikey` header).
 */
interface GoogleAuthAvailabilityGateway {
    /**
     * Fetched once per process and cached — this is a project-level
     * configuration flag, not something that changes while the app is
     * running. Fails open (returns `true`, i.e. show the button) on any
     * network error, timeout, or unexpected response shape, so a flaky or
     * slow `/auth/v1/settings` call never hides a working sign-in option.
     */
    suspend fun isGoogleSignInEnabled(): Boolean
}

@Singleton
class SupabaseGoogleAuthAvailabilityGateway
    @Inject
    constructor() : GoogleAuthAvailabilityGateway {
        private val client =
            OkHttpClient.Builder()
                .build()
        private val mutex = Mutex()

        @Volatile
        private var cached: Boolean? = null

        override suspend fun isGoogleSignInEnabled(): Boolean {
            cached?.let { return it }
            return mutex.withLock {
                cached?.let { return it }
                fetch().also { cached = it }
            }
        }

        private suspend fun fetch(): Boolean =
            withContext(Dispatchers.IO) {
                try {
                    val baseUrl = BuildConfig.SUPABASE_URL.trimEnd('/')
                    val request =
                        Request.Builder()
                            .url("$baseUrl/auth/v1/settings")
                            .header("apikey", BuildConfig.SUPABASE_ANON_KEY)
                            .build()
                    client.newCall(request).execute().use { response ->
                        if (!response.isSuccessful) {
                            true
                        } else {
                            parseGoogleEnabled(response.body?.string().orEmpty())
                        }
                    }
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: Exception) {
                    // Network error, timeout, malformed JSON, etc. — fail
                    // open, see [isGoogleSignInEnabled] kdoc.
                    true
                }
            }
    }

/**
 * Parses `{"external": {"google": false, ...}, ...}` from a
 * `/auth/v1/settings` response body. Missing/malformed shape defaults to
 * `true` (fail open).
 */
internal fun parseGoogleEnabled(body: String): Boolean {
    if (body.isBlank()) return true
    return try {
        val root = Json.parseToJsonElement(body).jsonObject
        root["external"]?.jsonObject?.get("google")?.jsonPrimitive?.booleanOrNull ?: true
    } catch (exc: Exception) {
        true
    }
}
