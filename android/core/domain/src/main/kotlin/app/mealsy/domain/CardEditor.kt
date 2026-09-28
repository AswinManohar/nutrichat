package app.mealsy.domain

/** Aggregate macros across a card's items, scaled per [CardEditor.totals]. */
data class Totals(
    val kcal: Double,
    val proteinG: Double,
    val carbsG: Double,
    val fatG: Double,
    val fiberG: Double,
)

/**
 * Pure edit operations over a [ConfirmationCard]. All functions return a new
 * card rather than mutating the input.
 */
object CardEditor {
    /** Returns a copy of [card] with the item at [index] removed. */
    fun removeItem(
        card: ConfirmationCard,
        index: Int,
    ): ConfirmationCard {
        val items = card.items.toMutableList()
        items.removeAt(index)
        return card.copy(items = items)
    }

    /**
     * Returns a copy of [card] with the item at [index]'s [CardItem.targetQtyG]
     * set to [newQtyG].
     *
     * @throws IllegalArgumentException if [newQtyG] is not positive.
     */
    fun editQty(
        card: ConfirmationCard,
        index: Int,
        newQtyG: Double,
    ): ConfirmationCard {
        require(newQtyG > 0) { "newQtyG must be positive, was $newQtyG" }
        val items = card.items.toMutableList()
        items[index] = items[index].copy(targetQtyG = newQtyG)
        return card.copy(items = items)
    }

    /**
     * Returns [CardItem.targetQtyG] scaled by [portion] — the actual grams
     * that will be logged for this item (and what `toSavedIngredientDto`
     * sends on the wire as `qtyG`). Item-row UIs must render this, not the
     * raw [CardItem.targetQtyG], or a portion change silently stops updating
     * the displayed grams while still updating kcal (#46).
     */
    fun scaledQtyG(
        item: CardItem,
        portion: Double,
    ): Double = item.targetQtyG * portion

    /** Returns a copy of [card] with its overall [ConfirmationCard.portion] set. */
    fun setPortion(
        card: ConfirmationCard,
        portion: Double,
    ): ConfirmationCard {
        return card.copy(portion = portion)
    }

    /**
     * Computes aggregate totals across [card]'s items, scaling each item's
     * macros by `(targetQtyG / qtyG) * portion`.
     *
     * A zero [CardItem.qtyG] (a malformed item that never got a real resolved
     * weight) would otherwise divide-by-zero into NaN/Infinity macros; that
     * item's factor is treated as `0` instead so one bad item can't poison
     * the whole card's totals.
     */
    fun totals(card: ConfirmationCard): Totals {
        var kcal = 0.0
        var proteinG = 0.0
        var carbsG = 0.0
        var fatG = 0.0
        var fiberG = 0.0
        for (item in card.items) {
            val factor =
                if (item.qtyG != 0.0) {
                    (item.targetQtyG / item.qtyG) * card.portion
                } else {
                    0.0
                }
            kcal += item.kcal * factor
            proteinG += item.proteinG * factor
            carbsG += item.carbsG * factor
            fatG += item.fatG * factor
            fiberG += item.fiberG * factor
        }
        return Totals(kcal = kcal, proteinG = proteinG, carbsG = carbsG, fatG = fatG, fiberG = fiberG)
    }

    /**
     * Returns a copy of [card] with the item at [index] marked as having a
     * pending correction to [newName].
     *
     * The authoritative swap of a food name happens server-side, via a
     * `use X instead of Y` text turn sent to the backend — this function does
     * NOT rename [CardItem.foodName] locally. It only records the intent in
     * [CardItem.pendingCandidate] so the UI can render a pending state while
     * that turn round-trips. [CardItem.pendingCandidate] is UI-only state and
     * must never be serialized to the wire.
     *
     * No-op (returns [card] unchanged) if [index] is out of range.
     */
    fun replaceCandidate(
        card: ConfirmationCard,
        index: Int,
        newName: String,
    ): ConfirmationCard {
        if (index !in card.items.indices) return card
        val items = card.items.toMutableList()
        items[index] = items[index].copy(pendingCandidate = newName)
        return card.copy(items = items)
    }

    /**
     * Swaps the item at [index] for [newItem] (typically fetched from
     * `GET /foods/{fdc_id}`), keeping the old item's [CardItem.targetQtyG]
     * and meal type (FR-004, U2), and recording a [FoodCorrection] so the
     * swap can be sent on `POST /meals/log-items`.
     *
     * If [index] already carries a [CardItem.pendingCorrection] (a repeat
     * swap), the new correction's `from*` fields still point at the
     * **originally** matched food, not the intermediate one — only one
     * correction is ever pending per item.
     *
     * No-op (returns [card] unchanged) if [index] is out of range or if
     * [newItem] is already the current match ([CardItem.fdcId] unchanged).
     */
    fun swapItem(
        card: ConfirmationCard,
        index: Int,
        newItem: CardItem,
        method: String,
        query: String? = null,
    ): ConfirmationCard {
        if (index !in card.items.indices) return card
        val old = card.items[index]
        if (old.fdcId == newItem.fdcId) return card

        val originalPhrase = old.pendingCorrection?.originalPhrase ?: (old.inputPhrase ?: old.foodName)
        val fromFdcId = old.pendingCorrection?.fromFdcId ?: (if (old.estimated) null else old.fdcId)
        val fromName = old.pendingCorrection?.fromName ?: old.foodName

        val swapped =
            newItem.copy(
                targetQtyG = old.targetQtyG,
                inputPhrase = old.inputPhrase,
                // A fresh USDA lookup for [newItem] knows nothing about the
                // composite dish it's replacing a part of — carry the old
                // item's group membership over so the rest of the group
                // stays intact (contracts, E2).
                sourceDish = old.sourceDish,
                isComposite = old.isComposite,
                pendingCorrection =
                    FoodCorrection(
                        originalPhrase = originalPhrase,
                        fromFdcId = fromFdcId,
                        fromName = fromName,
                        toFdcId = newItem.fdcId,
                        method = method,
                        query = query,
                    ),
            )
        val items = card.items.toMutableList()
        items[index] = swapped
        return card.copy(items = items)
    }

    /**
     * Restores the item at [index] to [previous] exactly, undoing the most
     * recent [swapItem] — including dropping its [CardItem.pendingCorrection].
     * No-op if [index] is out of range.
     */
    fun undoSwap(
        card: ConfirmationCard,
        index: Int,
        previous: CardItem,
    ): ConfirmationCard {
        if (index !in card.items.indices) return card
        val items = card.items.toMutableList()
        items[index] = previous
        return card.copy(items = items)
    }
}
