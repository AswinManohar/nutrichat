package app.mealsy.data.api

import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.Response

/**
 * Supplies a bearer token for [AuthInterceptor], with an explicit
 * force-refresh flag.
 *
 * This is a placeholder seam: Task 4 binds a real implementation backed by
 * `SessionManager.currentToken(forceRefresh)` in `AuthModule`. Task 4 should
 * bind `SessionManager::currentToken` (a `suspend fun currentToken(forceRefresh:
 * Boolean = false): String?` method reference) directly against this
 * functional interface.
 */
fun interface TokenProvider {
    suspend fun token(forceRefresh: Boolean): String?
}

/**
 * OkHttp [Interceptor] that attaches `Authorization: Bearer <token>` to every
 * request and retries once, with a forced token refresh, on a 401 response.
 *
 * OkHttp interceptors are synchronous by contract — `intercept` runs on an
 * OkHttp dispatcher thread, not a coroutine. `runBlocking` here is the
 * standard OkHttp pattern for bridging a suspend token provider (e.g. one
 * backed by Supabase's coroutine-based session refresh) into that
 * synchronous call chain; it blocks only the OkHttp worker thread, not the
 * caller's coroutine.
 */
class AuthInterceptor(private val tokenProvider: TokenProvider) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val token = runBlocking { tokenProvider.token(forceRefresh = false) }
        val request = chain.request().withAuth(token)
        val response = chain.proceed(request)

        if (response.code != 401) return response

        response.close()
        val refreshedToken = runBlocking { tokenProvider.token(forceRefresh = true) }
        val retriedRequest = chain.request().withAuth(refreshedToken)
        return chain.proceed(retriedRequest)
    }

    private fun okhttp3.Request.withAuth(token: String?): okhttp3.Request {
        val builder = newBuilder()
        if (token != null) {
            builder.header("Authorization", "Bearer $token")
        }
        return builder.build()
    }
}
