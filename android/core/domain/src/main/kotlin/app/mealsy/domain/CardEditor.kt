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
    fun removeItem(card: ConfirmationCard, index: Int): ConfirmationCard {
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
    fun editQty(card: ConfirmationCard, index: Int, newQtyG: Double): ConfirmationCard {
        require(newQtyG > 0) { "newQtyG must be positive, was $newQtyG" }
        val items = card.items.toMutableList()
        items[index] = items[index].copy(targetQtyG = newQtyG)
        return card.copy(items = items)
    }

    /** Returns a copy of [card] with its overall [ConfirmationCard.portion] set. */
    fun setPortion(card: ConfirmationCard, portion: Double): ConfirmationCard {
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
            val factor = if (item.qtyG != 0.0) {
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
    fun replaceCandidate(card: ConfirmationCard, index: Int, newName: String): ConfirmationCard {
        if (index !in card.items.indices) return card
        val items = card.items.toMutableList()
        items[index] = items[index].copy(pendingCandidate = newName)
        return card.copy(items = items)
    }
}
