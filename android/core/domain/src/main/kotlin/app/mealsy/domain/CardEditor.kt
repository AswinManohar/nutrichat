package app.mealsy.domain

/** Aggregate macros across a card's items, scaled per [CardEditor.totals]. */
data class Totals(val kcal: Double, val proteinG: Double)

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
     */
    fun totals(card: ConfirmationCard): Totals {
        var kcal = 0.0
        var proteinG = 0.0
        for (item in card.items) {
            val factor = (item.targetQtyG / item.qtyG) * card.portion
            kcal += item.kcal * factor
            proteinG += item.proteinG * factor
        }
        return Totals(kcal = kcal, proteinG = proteinG)
    }
}
