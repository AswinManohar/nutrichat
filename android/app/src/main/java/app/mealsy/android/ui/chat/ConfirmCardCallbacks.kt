package app.mealsy.android.ui.chat

/**
 * Everything the confirm card can ask its host (the chat view model) to do.
 * Card-scoped: only the newest paused card is ever interactive, so no card
 * identifier is needed — the host always knows which card these refer to.
 */
interface ConfirmCardCallbacks {
    /** The user changed the meal-type segment (e.g. "breakfast", "lunch"). */
    fun onMealTypeChange(mealType: String)

    /** The user changed the overall portion multiplier (e.g. 0.5, 1.0, 1.5, 2.0). */
    fun onPortionChange(portion: Double)

    /** The user edited an item's gram quantity via its [Stepper][app.mealsy.android.design.components.Stepper]. */
    fun onQtyChange(
        index: Int,
        newQtyG: Double,
    )

    /** The user tapped the remove ("×") affordance on an item row. */
    fun onRemoveItem(index: Int)

    /** The user tapped "Undo" on the remove toast, restoring the last-removed item. */
    fun onUndoRemove()

    /** The user picked a different food from an item's candidate list. */
    fun onSwapCandidate(
        index: Int,
        newName: String,
    )

    /**
     * The user typed a free-text replacement description for an item after
     * none of the candidate picker's rows matched ("None of these — describe
     * it differently").
     */
    fun onDescribeItemDifferently(
        index: Int,
        description: String,
    )

    /** The user tapped "Break into ingredients" on a composite dish. */
    fun onDecompose()

    /** The user tapped "Log as single item" to re-combine a decomposed dish. */
    fun onCombine()

    /** The user tapped "Confirm & log". */
    fun onConfirm()

    /** The user tapped "Cancel", dismissing the card without logging. */
    fun onCancel()

    /** The user tapped "Add to My Meals" with the given template name. */
    fun onSaveAsMyMeal(name: String)
}
