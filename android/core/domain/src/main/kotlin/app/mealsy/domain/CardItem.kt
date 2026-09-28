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
 * @property inputPhrase The user's original words for this item, when not
 *   already derivable from [foodName] (spec 003, research R9). Used to
 *   pre-fill the food picker's search field.
 * @property candidateDetails Per-candidate nutrition for [candidates], same
 *   order and names (spec 003, US2 "Compare the suggested alternatives").
 *   Empty for estimated items and the live-FDC path (data-model.md
 *   CandidateDetail) — the picker sheet falls back to name-only rows then.
 * @property pendingCorrection UI/wire state set by
 *   [CardEditor.swapItem] (spec 003's local swap path, distinct from
 *   [pendingCandidate]'s chat round-trip): records the picker-driven
 *   correction so `POST /meals/log-items` can send it on this item. Its
 *   `from*` fields always point at the item's **originally** matched food,
 *   preserved across repeat swaps.
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
    val inputPhrase: String? = null,
    val pendingCorrection: FoodCorrection? = null,
    val candidateDetails: List<CandidateDetail> = emptyList(),
)

/**
 * One [CardItem.candidates] alternative's nutrition, for the picker sheet's
 * Suggestions section (spec 003, US2). Matches the wire shape of
 * `FoodSearchResult` minus the request-scaled fields — the client scales
 * for preview at the item's current grams (data-model.md).
 *
 * @property fdcId USDA FoodData Central id.
 * @property name Equals the matching entry in the sibling `candidates`,
 *   same order.
 * @property dataType One of `"foundation"`, `"sr_legacy"`, `"survey_fndds"`.
 * @property kcalPer100g Energy per 100 g, unscaled.
 * @property proteinGPer100g Protein per 100 g, unscaled.
 */
@Serializable
data class CandidateDetail(
    val fdcId: Long,
    val name: String,
    val dataType: String,
    val kcalPer100g: Double,
    val proteinGPer100g: Double,
)

/**
 * A pending correction of one card item's USDA match, recorded locally by
 * [CardEditor.swapItem] and sent on `POST /meals/log-items` as the item's
 * `correction` field (spec 003).
 *
 * @property originalPhrase The user's words for the item.
 * @property fromFdcId The **originally** matched food's fdc id, or `null` if
 *   that match was an estimate.
 * @property fromName The originally matched food's display name.
 * @property toFdcId The newly chosen food's fdc id.
 * @property method How the user picked the replacement: `"suggestion"` or
 *   `"search"`.
 * @property query The search text, when [method] is `"search"`.
 */
@Serializable
data class FoodCorrection(
    val originalPhrase: String,
    val fromFdcId: Long?,
    val fromName: String,
    val toFdcId: Long,
    val method: String,
    val query: String? = null,
)
