package app.mealsy.data.api

import app.mealsy.domain.CardItem
import app.mealsy.domain.ConfirmationCard
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

// ---------------------------------------------------------------------------
// POST /meals/log, GET /meals/pending
// ---------------------------------------------------------------------------

@Serializable
data class LogTurnRequest(
    @SerialName("user_input") val userInput: String,
    @SerialName("conversation_id") val conversationId: String? = null,
    @SerialName("image_b64") val imageB64: String? = null,
    @SerialName("meal_type") val mealType: String? = null,
    val action: String? = null,
)

@Serializable
data class LogTurnResponse(
    val status: String,
    val message: String,
    val paused: Boolean,
    val items: List<ItemDto> = emptyList(),
    val deduplicated: Boolean = false,
)

/**
 * A single resolved food entity as sent by the backend on `POST /meals/log`,
 * `GET /meals/pending`, and echoed by `POST /meals/log-items`.
 *
 * Unrecognized keys land in [extras] rather than failing parsing — the
 * mobile API contract (docs/reference/mobile-api.md) requires clients to
 * ignore fields they don't model.
 */
@Serializable
data class ItemDto(
    @SerialName("food_name") val foodName: String,
    @SerialName("qty_g") val qtyG: Double,
    @SerialName("target_qty_g") val targetQtyG: Double? = null,
    val kcal: Double,
    @SerialName("protein_g") val proteinG: Double,
    @SerialName("carbs_g") val carbsG: Double,
    @SerialName("fat_g") val fatG: Double,
    @SerialName("fiber_g") val fiberG: Double,
    @SerialName("fdc_id") val fdcId: Long,
    val estimated: Boolean = false,
    val extras: JsonObject = JsonObject(emptyMap()),
)

/**
 * Maps a `POST /meals/log` / `GET /meals/pending` response into the domain
 * [ConfirmationCard], or `null` when there is nothing pending to confirm.
 *
 * For a fresh card off the wire, `targetQtyG` starts equal to `qtyG` (no
 * user edit has happened yet) unless the server already supplied one.
 */
fun LogTurnResponse.toCard(): ConfirmationCard? {
    if (!paused) return null
    return ConfirmationCard(
        message = message,
        items = items.map { it.toCardItem() },
    )
}

private fun ItemDto.toCardItem(): CardItem = CardItem(
    foodName = foodName,
    qtyG = qtyG,
    targetQtyG = targetQtyG ?: qtyG,
    kcal = kcal,
    proteinG = proteinG,
    carbsG = carbsG,
    fatG = fatG,
    fiberG = fiberG,
    fdcId = fdcId,
    estimated = estimated,
    extras = extras,
)

// ---------------------------------------------------------------------------
// POST /meals/log-items
// ---------------------------------------------------------------------------

@Serializable
data class LogItemsRequest(
    @SerialName("meal_type") val mealType: String,
    val portion: Double = 1.0,
    val items: List<ItemDto>,
    @SerialName("client_request_id") val clientRequestId: String? = null,
)

@Serializable
data class LogItemsResponse(
    @SerialName("meal_id") val mealId: String,
    @SerialName("meal_type") val mealType: String,
    @SerialName("n_items") val nItems: Int,
    val kcal: Double,
    @SerialName("protein_g") val proteinG: Double,
    @SerialName("carbs_g") val carbsG: Double,
    @SerialName("fat_g") val fatG: Double,
    @SerialName("fiber_g") val fiberG: Double,
    val message: String,
    val deduplicated: Boolean = false,
)

// ---------------------------------------------------------------------------
// GET /meals/today
// ---------------------------------------------------------------------------

@Serializable
data class TodayResponse(
    val kcal: Double,
    @SerialName("protein_g") val proteinG: Double,
    @SerialName("fiber_g") val fiberG: Double,
    @SerialName("n_meals") val nMeals: Int,
    @SerialName("by_type") val byType: List<ByTypeDto> = emptyList(),
)

@Serializable
data class ByTypeDto(
    @SerialName("meal_type") val mealType: String,
    val kcal: Double,
    val summary: String,
)

// ---------------------------------------------------------------------------
// GET/POST/PUT /goals
// ---------------------------------------------------------------------------

@Serializable
data class GoalsResponse(
    @SerialName("tracking_mode") val trackingMode: String,
    @SerialName("kcal_goal") val kcalGoal: Double? = null,
    @SerialName("protein_goal") val proteinGoal: Double? = null,
    @SerialName("fiber_goal") val fiberGoal: Double? = null,
    @SerialName("dietary_prefs") val dietaryPrefs: JsonObject = JsonObject(emptyMap()),
    @SerialName("first_meal_time") val firstMealTime: String? = null,
    @SerialName("streak_days") val streakDays: Int = 0,
)

// ---------------------------------------------------------------------------
// GET /quota
// ---------------------------------------------------------------------------

@Serializable
data class QuotaResponse(
    val used: Int,
    val limit: Int,
    val remaining: Int,
    val exhausted: Boolean,
    val tier: String,
)

// ---------------------------------------------------------------------------
// POST /devices/register
// ---------------------------------------------------------------------------

@Serializable
data class RegisterDeviceRequest(
    val token: String,
    val platform: String = "fcm",
)

// ---------------------------------------------------------------------------
// GET /meta/app
// ---------------------------------------------------------------------------

@Serializable
data class AppMetaResponse(
    @SerialName("min_supported_version_code") val minSupportedVersionCode: Int,
    @SerialName("latest_version_code") val latestVersionCode: Int,
)
