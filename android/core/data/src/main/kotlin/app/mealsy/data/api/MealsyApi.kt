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
    suspend fun logTurn(
        @Body body: LogTurnRequest,
    ): LogTurnResponse

    @GET("meals/pending")
    suspend fun pending(
        @Query("conversation_id") id: String,
    ): LogTurnResponse

    @POST("meals/log-items")
    suspend fun logItems(
        @Body body: LogItemsRequest,
    ): LogItemsResponse

    /** Free-text search of the bundled USDA reference DB (spec 003). */
    @GET("foods/search")
    suspend fun searchFoods(
        @Query("q") q: String,
        @Query("qty_g") qtyG: Double,
        @Query("limit") limit: Int = 10,
    ): FoodSearchResponseDto

    /** Builds a ready-to-log card item for [fdcId] scaled to [qtyG] (spec 003). */
    @GET("foods/{fdcId}")
    suspend fun getFood(
        @Path("fdcId") fdcId: Long,
        @Query("qty_g") qtyG: Double,
    ): ItemDto

    @GET("meals/today")
    suspend fun today(): TodayResponse

    @GET("goals")
    suspend fun goals(): GoalsResponse

    @POST("goals")
    suspend fun createGoals(
        @Body body: GoalRequest,
    ): GoalsResponse

    @PUT("goals")
    suspend fun updateGoals(
        @Body body: GoalRequest,
    ): GoalsResponse

    @GET("quota")
    suspend fun quota(): QuotaResponse

    @POST("devices/register")
    suspend fun registerDevice(
        @Body body: RegisterDeviceRequest,
    )

    @DELETE("devices/{token}")
    suspend fun deleteDevice(
        @Path("token") token: String,
    )

    @GET("meta/app")
    suspend fun appMeta(): AppMetaResponse

    @GET("meals/trends")
    suspend fun trends(
        @Query("days") days: Int,
    ): List<DayTrendDto>

    @GET("meals/categories")
    suspend fun categories(
        @Query("days") days: Int,
    ): List<CategoryStatDto>

    @GET("my-meals")
    suspend fun myMeals(): List<SavedMealDto>

    @GET("my-meals/{id}")
    suspend fun myMeal(
        @Path("id") id: String,
    ): MyMealDetailDto

    @POST("my-meals")
    suspend fun saveMeal(
        @Body body: SaveMealRequest,
    ): SavedMealDto

    @PUT("my-meals/{id}")
    suspend fun updateMyMeal(
        @Path("id") id: String,
        @Body body: UpdateMealRequest,
    ): MyMealDetailDto

    @POST("my-meals/{id}/log")
    suspend fun logMyMeal(
        @Path("id") id: String,
        @Body body: LogMyMealRequest,
    ): LogItemsResponse

    @DELETE("my-meals/{id}")
    suspend fun deleteMyMeal(
        @Path("id") id: String,
    )

    @GET("meals/log")
    suspend fun listMealLogs(
        @Query("date") date: String? = null,
        @Query("meal_type") mealType: String? = null,
    ): List<MealLogSummaryDto>

    @GET("meals/log/{meal_id}")
    suspend fun mealLog(
        @Path("meal_id") id: String,
    ): MealLogDetailDto

    @DELETE("meals/log/{meal_id}")
    suspend fun deleteMealLog(
        @Path("meal_id") id: String,
    )

    @DELETE("account")
    suspend fun deleteAccount()

    /**
     * Submits feedback on a coaching reply. Does not exist on this branch's
     * backend (it ships with the coaching work on `andorid_prod`) — callers
     * must only invoke this when a turn actually carried a `response_id`.
     */
    @POST("coaching/{id}/feedback")
    suspend fun coachingFeedback(
        @Path("id") id: String,
        @Body body: CoachingFeedbackRequest,
    )
}
