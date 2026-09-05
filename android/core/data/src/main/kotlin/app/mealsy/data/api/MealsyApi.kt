package app.mealsy.data.api

import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * Retrofit interface for the Mealsy backend, per the frozen contract in
 * `docs/reference/mobile-api.md`.
 *
 * Retry safety varies by endpoint — see that doc's "Retry rules" section.
 * Notably, [logTurn] must never be auto-retried by callers; on timeout,
 * recover via [pending] instead. [logItems] is the only write safe to
 * blind-retry, and only when a `client_request_id` is supplied.
 */
interface MealsyApi {
    @POST("meals/log")
    suspend fun logTurn(@Body body: LogTurnRequest): LogTurnResponse

    @GET("meals/pending")
    suspend fun pending(@Query("conversation_id") id: String): LogTurnResponse

    @POST("meals/log-items")
    suspend fun logItems(@Body body: LogItemsRequest): LogItemsResponse

    @GET("meals/today")
    suspend fun today(): TodayResponse

    @GET("goals")
    suspend fun goals(): GoalsResponse

    @POST("goals")
    suspend fun createGoals(@Body body: GoalRequest): GoalsResponse

    @PUT("goals")
    suspend fun updateGoals(@Body body: GoalRequest): GoalsResponse

    @GET("quota")
    suspend fun quota(): QuotaResponse

    @POST("devices/register")
    suspend fun registerDevice(@Body body: RegisterDeviceRequest)

    @DELETE("devices/{token}")
    suspend fun deleteDevice(@Path("token") token: String)

    @GET("meta/app")
    suspend fun appMeta(): AppMetaResponse
}
