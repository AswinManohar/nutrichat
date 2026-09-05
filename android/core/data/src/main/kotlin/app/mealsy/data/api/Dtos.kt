package app.mealsy.data.api

import app.mealsy.domain.CardItem
import app.mealsy.domain.ConfirmationCard
import app.mealsy.domain.Goals
import kotlinx.serialization.EncodeDefault
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.descriptors.buildClassSerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.JsonEncoder
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long

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
 * Unrecognized keys are captured verbatim into [extras] by [ItemDtoSerializer]
 * rather than dropped — the mobile API contract (docs/reference/mobile-api.md)
 * requires the client to round-trip fields it doesn't model (nutrients,
 * `source`, etc.) from a `GET`/paused card straight back into
 * `POST /meals/log-items`. On encode, [extras] is flattened back to
 * top-level keys — the wire format never nests an `"extras"` object.
 */
@Serializable(with = ItemDtoSerializer::class)
data class ItemDto(
    val foodName: String,
    val qtyG: Double,
    val targetQtyG: Double? = null,
    val kcal: Double,
    val proteinG: Double,
    val carbsG: Double,
    val fatG: Double,
    val fiberG: Double,
    val fdcId: Long,
    val estimated: Boolean = false,
    val extras: JsonObject = JsonObject(emptyMap()),
)

/** Wire keys [ItemDto] models explicitly; everything else round-trips via [ItemDto.extras]. */
private val ITEM_DTO_KNOWN_KEYS = setOf(
    "food_name", "qty_g", "target_qty_g", "kcal", "protein_g",
    "carbs_g", "fat_g", "fiber_g", "fdc_id", "estimated",
)

object ItemDtoSerializer : KSerializer<ItemDto> {
    override val descriptor: SerialDescriptor = buildClassSerialDescriptor("ItemDto")

    override fun deserialize(decoder: Decoder): ItemDto {
        val jsonDecoder = decoder as? JsonDecoder
            ?: error("ItemDtoSerializer only supports JSON")
        val obj = jsonDecoder.decodeJsonElement().jsonObject

        return ItemDto(
            foodName = obj.getValue("food_name").jsonPrimitive.content,
            qtyG = obj.getValue("qty_g").jsonPrimitive.double,
            targetQtyG = obj["target_qty_g"]?.jsonPrimitive?.doubleOrNull,
            kcal = obj.getValue("kcal").jsonPrimitive.double,
            proteinG = obj.getValue("protein_g").jsonPrimitive.double,
            carbsG = obj.getValue("carbs_g").jsonPrimitive.double,
            fatG = obj.getValue("fat_g").jsonPrimitive.double,
            fiberG = obj.getValue("fiber_g").jsonPrimitive.double,
            fdcId = obj.getValue("fdc_id").jsonPrimitive.long,
            estimated = obj["estimated"]?.jsonPrimitive?.booleanOrNull ?: false,
            extras = JsonObject(obj.filterKeys { it !in ITEM_DTO_KNOWN_KEYS }),
        )
    }

    override fun serialize(encoder: Encoder, value: ItemDto) {
        val jsonEncoder = encoder as? JsonEncoder
            ?: error("ItemDtoSerializer only supports JSON")

        val fields = LinkedHashMap<String, kotlinx.serialization.json.JsonElement>()
        fields["food_name"] = JsonPrimitive(value.foodName)
        fields["qty_g"] = JsonPrimitive(value.qtyG)
        value.targetQtyG?.let { fields["target_qty_g"] = JsonPrimitive(it) }
        fields["kcal"] = JsonPrimitive(value.kcal)
        fields["protein_g"] = JsonPrimitive(value.proteinG)
        fields["carbs_g"] = JsonPrimitive(value.carbsG)
        fields["fat_g"] = JsonPrimitive(value.fatG)
        fields["fiber_g"] = JsonPrimitive(value.fiberG)
        fields["fdc_id"] = JsonPrimitive(value.fdcId)
        fields["estimated"] = JsonPrimitive(value.estimated)
        // Flatten extras back to top level — never nest an "extras" object,
        // and never let a stale extras key shadow a field we set explicitly.
        value.extras.forEach { (key, element) ->
            if (key !in ITEM_DTO_KNOWN_KEYS) fields[key] = element
        }

        jsonEncoder.encodeJsonElement(JsonObject(fields))
    }
}

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

/**
 * Wire body for `POST /goals` and `PUT /goals` — both endpoints share the
 * same request shape (`GoalCreate`/`GoalUpdate` in `src/backend/api/goals.py`
 * are field-for-field identical). `streak_days` is never sent: the backend
 * computes it and neither request model accepts it.
 */
@Serializable
data class GoalRequest(
    @SerialName("tracking_mode") val trackingMode: String,
    @SerialName("kcal_goal") val kcalGoal: Double? = null,
    @SerialName("protein_goal") val proteinGoal: Double? = null,
    @SerialName("fiber_goal") val fiberGoal: Double? = null,
    @SerialName("dietary_prefs") val dietaryPrefs: JsonObject = JsonObject(emptyMap()),
    @SerialName("first_meal_time") val firstMealTime: String? = null,
)

fun GoalsResponse.toGoals(): Goals = Goals(
    trackingMode = trackingMode,
    kcalGoal = kcalGoal,
    proteinGoal = proteinGoal,
    fiberGoal = fiberGoal,
    dietaryPrefs = dietaryPrefs.mapValues { (_, v) -> v.jsonPrimitive.booleanOrNull ?: true },
    firstMealTime = firstMealTime,
    streakDays = streakDays,
)

fun Goals.toGoalRequest(): GoalRequest = GoalRequest(
    trackingMode = trackingMode,
    kcalGoal = kcalGoal,
    proteinGoal = proteinGoal,
    fiberGoal = fiberGoal,
    dietaryPrefs = JsonObject(dietaryPrefs.mapValues { (_, v) -> JsonPrimitive(v) }),
    firstMealTime = firstMealTime,
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

@OptIn(ExperimentalSerializationApi::class)
@Serializable
data class RegisterDeviceRequest(
    val token: String,
    // The backend's Pydantic model declares `platform: Literal["fcm"]` with
    // `extra="forbid"` — it's required on the wire even though every caller
    // in practice wants "fcm". @EncodeDefault forces it to always be
    // serialized regardless of the shared Json's encodeDefaults setting, so
    // this default value doesn't silently drop the field and 422 the request.
    @EncodeDefault(EncodeDefault.Mode.ALWAYS)
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

// ---------------------------------------------------------------------------
// GET /meals/trends, GET /meals/categories
// ---------------------------------------------------------------------------

/**
 * One day's aggregate, per `DayTrend` in `src/backend/api/meals.py`. Days
 * with no logged meals are omitted server-side — the response is a bare
 * JSON array, never wrapped in an envelope object.
 */
@Serializable
data class DayTrendDto(
    val date: String,
    val kcal: Double,
    @SerialName("protein_g") val proteinG: Double,
    @SerialName("carbs_g") val carbsG: Double,
    @SerialName("fiber_g") val fiberG: Double,
    @SerialName("n_meals") val nMeals: Int,
    @SerialName("junk_meals") val junkMeals: Int,
)

/**
 * Per-category macro averages/frequency, per `CategoryStat` in
 * `src/backend/api/meals.py`. Also a bare JSON array on the wire.
 */
@Serializable
data class CategoryStatDto(
    @SerialName("meal_type") val mealType: String,
    @SerialName("n_meals") val nMeals: Int,
    @SerialName("days_logged") val daysLogged: Int,
    @SerialName("avg_kcal") val avgKcal: Double,
    @SerialName("avg_protein_g") val avgProteinG: Double,
    @SerialName("avg_carbs_g") val avgCarbsG: Double,
    @SerialName("avg_fat_g") val avgFatG: Double,
    @SerialName("avg_fiber_g") val avgFiberG: Double,
    @SerialName("total_kcal") val totalKcal: Double,
    @SerialName("share_kcal_pct") val shareKcalPct: Double,
)

// ---------------------------------------------------------------------------
// GET/POST/DELETE /my-meals, POST /my-meals/{id}/log
// ---------------------------------------------------------------------------

/**
 * One saved "quick log" meal, per `MyMealSummary` in
 * `src/backend/api/my_meals.py`. `GET /my-meals` returns a bare JSON array of
 * these (same bare-array contract as trends/categories above).
 */
@Serializable
data class SavedMealDto(
    val id: String,
    val name: String,
    val kcal: Double,
    @SerialName("protein_g") val proteinG: Double,
    @SerialName("carbs_g") val carbsG: Double,
    @SerialName("fat_g") val fatG: Double,
    @SerialName("fiber_g") val fiberG: Double,
    @SerialName("n_ingredients") val nIngredients: Int,
    @SerialName("logged_today") val loggedToday: Boolean = false,
)

/**
 * Body for `POST /my-meals`. `ingredients` reuses [ItemDto]/[ItemDtoSerializer]
 * — the backend's `IngredientIn` (`src/backend/api/my_meals.py`) declares the
 * same `food_name`/`qty_g`/macro fields and allows (and stores verbatim) any
 * extra keys, so [ItemDto]'s `food_name`/`qty_g`/macros/`fdc_id`/`estimated`
 * plus flattened `extras` round-trips cleanly into it. `target_qty_g` is
 * omitted here (each [ItemDto] is built with `targetQtyG = null`) since a
 * saved meal has no separate "edited" weight — [ItemDto.qtyG] alone is the
 * ingredient's stored gram weight.
 */
@Serializable
data class SaveMealRequest(
    val name: String,
    val ingredients: List<ItemDto>,
)

/** One kept ingredient (by stored index) with its edited gram weight, for a customized quick-log. */
@Serializable
data class IngredientOverrideDto(
    val index: Int,
    @SerialName("qty_g") val qtyG: Double,
)

/**
 * Body for `POST /my-meals/{id}/log`. Omit [ingredients] for a 1x quick-log
 * of the meal exactly as saved; `explicitNulls = false` (see [ApiModule])
 * means a `null` here is dropped from the wire entirely, matching the
 * backend's "omit for quick-log" contract rather than sending `"ingredients": null`.
 */
@Serializable
data class LogMyMealRequest(
    @SerialName("meal_type") val mealType: String,
    val portion: Double = 1.0,
    val ingredients: List<IngredientOverrideDto>? = null,
)

/**
 * Maps a [CardItem] into the [ItemDto] shape `POST /my-meals` expects,
 * scaling its macros by the same `(targetQtyG / qtyG) * portion` factor
 * [app.mealsy.domain.CardEditor.totals] uses — a saved meal stores each
 * ingredient at its current, already-edited weight, not the original
 * resolved one.
 */
fun CardItem.toSavedIngredientDto(portion: Double): ItemDto {
    // qtyG is normally a positive resolved gram weight, but a malformed/edge
    // card (e.g. a decompose sub-item that never got a real weight) could
    // carry a 0 — dividing by it would put NaN macros on the wire. Falling
    // back to an unscaled factor keeps the request well-formed rather than
    // failing the whole save over one bad item.
    val factor = if (qtyG != 0.0) (targetQtyG / qtyG) * portion else portion
    return ItemDto(
        foodName = foodName,
        qtyG = targetQtyG * portion,
        targetQtyG = null,
        kcal = kcal * factor,
        proteinG = proteinG * factor,
        carbsG = carbsG * factor,
        fatG = fatG * factor,
        fiberG = fiberG * factor,
        fdcId = fdcId,
        estimated = estimated,
        extras = extras,
    )
}
