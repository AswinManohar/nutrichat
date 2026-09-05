package app.mealsy.domain

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

/**
 * A single resolved food entity on a confirmation card.
 *
 * @property qtyG Resolved base weight in grams — the scaling base for macros.
 * @property targetQtyG User-edited weight in grams. Macros scale by
 *   `(targetQtyG / qtyG) * portion`.
 * @property extras Verbatim passthrough of any additional fields the backend
 *   sent that the app does not otherwise model.
 */
@Serializable
data class CardItem(
    val foodName: String,
    val qtyG: Double,
    val targetQtyG: Double,
    val kcal: Double,
    val proteinG: Double,
    val carbsG: Double,
    val fatG: Double,
    val fiberG: Double,
    val fdcId: Long,
    val estimated: Boolean = false,
    val extras: JsonObject = JsonObject(emptyMap()),
)
