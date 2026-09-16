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
 * @property candidates Alternate food names the resolver considered, for a
 *   "did you mean" correction affordance. Degrades to names-only even when
 *   the backend sends richer candidate objects (see `ItemDtoSerializer`).
 * @property source Where this item's macros came from (e.g. `"usda"`,
 *   `"estimate"`), as reported by the backend.
 * @property confidence The resolver's match confidence for [foodName],
 *   `0.0`–`1.0` when present.
 * @property sourceDish For a decomposed composite dish, the name of the
 *   parent dish this item was extracted from.
 * @property isComposite Whether this item is itself a composite dish rather
 *   than a single resolved food.
 * @property pendingCandidate UI-only state: set by
 *   [CardEditor.replaceCandidate] to show a pending correction while the
 *   authoritative swap round-trips through a `use X instead of Y` text turn.
 *   This is never sent to the backend — it is deliberately absent from
 *   [app.mealsy.data.api.ItemDto], and `toItemDto()` ignores it.
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
    val candidates: List<String> = emptyList(),
    val source: String? = null,
    val confidence: Double? = null,
    val sourceDish: String? = null,
    val isComposite: Boolean = false,
    val pendingCandidate: String? = null,
)
