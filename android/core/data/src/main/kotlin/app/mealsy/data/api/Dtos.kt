package app.mealsy.data.api

import app.mealsy.domain.CardItem
import app.mealsy.domain.ConfirmationCard
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
