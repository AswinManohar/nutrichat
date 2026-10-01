package app.mealsy.domain

/**
 * One editable ingredient row of [EditMealState].
 *
 * @property item The stored ingredient. [CardItem.targetQtyG] is the
 *   weight loaded from the server and is the dirty-check baseline; it is
 *   never changed by edits.
 * @property qtyG The current edited gram weight.
 * @property removed Whether the row is removed (undoable until saved).
 */
data class EditRow(
    val item: CardItem,
    val qtyG: Double,
    val removed: Boolean = false,
)

/**
 * Pure, framework-free state for editing a saved meal (spec 006, US1),
 * modeled on `CustomizeSheetState`: every op returns a new instance.
 *
 * Lives in `core:domain`, which cannot see `SavedMealDetail` (core:data),
 * so [from]/[reset] take the detail's plain parts (name, `updatedAt`,
 * items as [CardItem]s with `targetQtyG = qtyG`).
 *
 * @property mealId The saved meal's id.
 * @property baseUpdatedAt The `updated_at` loaded; sent as
 *   `expected_updated_at` on save.
 * @property baseName The name as loaded (dirty-check baseline).
 * @property name The current edited name.
 */
data class EditMealState(
    val mealId: String,
    val baseUpdatedAt: String,
    val baseName: String,
    val name: String,
    val rows: List<EditRow>,
) {
    companion object {
        /** Builds the initial state from a loaded saved meal's parts. */
        fun from(
            mealId: String,
            name: String,
            updatedAt: String,
            items: List<CardItem>,
        ): EditMealState =
            EditMealState(
                mealId = mealId,
                baseUpdatedAt = updatedAt,
                baseName = name,
                name = name,
                rows = items.map { EditRow(item = it, qtyG = it.targetQtyG) },
            )
    }

    /** Rows not removed. */
    val keptRows: List<EditRow> get() = rows.filterNot { it.removed }

    /** Live totals over [keptRows] at their edited weights, via [CardEditor.totals]. */
    val totals: Totals
        get() =
            CardEditor.totals(
                ConfirmationCard(
                    message = "",
                    items = keptRows.map { it.item.copy(targetQtyG = it.qtyG) },
                ),
            )

    /** Whether the name, any weight, or any removal differs from what was loaded. */
    val isDirty: Boolean
        get() =
            name.trim() != baseName.trim() ||
                rows.any { it.removed || it.qtyG != it.item.targetQtyG }

    /**
     * Save is allowed when dirty, the trimmed name has a letter or digit,
     * at least one row is kept, and every kept row has `qtyG > 0`.
     */
    val canSave: Boolean
        get() =
            isDirty &&
                name.trim().any { it.isLetterOrDigit() } &&
                keptRows.isNotEmpty() &&
                keptRows.all { it.qtyG > 0.0 }

    /** Kept items, each with `targetQtyG` set to its edited weight. */
    fun keptItemsForSave(): List<CardItem> = keptRows.map { it.item.copy(targetQtyG = it.qtyG) }

    fun rename(newName: String): EditMealState = copy(name = newName)

    /** Sets the edited weight of the row at [index]; out-of-range is a no-op. */
    fun setQty(
        index: Int,
        qtyG: Double,
    ): EditMealState = mapRow(index) { it.copy(qtyG = qtyG) }

    /** Removes the row at [index], except the last kept row, which is refused (no-op). */
    fun remove(index: Int): EditMealState {
        val row = rows.getOrNull(index) ?: return this
        if (row.removed || keptRows.size <= 1) return this
        return mapRow(index) { it.copy(removed = true) }
    }

    fun undoRemove(index: Int): EditMealState = mapRow(index) { it.copy(removed = false) }

    /** Replaces name, baseline and rows with a fresh server version (e.g. after `meal_changed`). */
    fun reset(
        name: String,
        updatedAt: String,
        items: List<CardItem>,
    ): EditMealState = from(mealId = mealId, name = name, updatedAt = updatedAt, items = items)

    private fun mapRow(
        index: Int,
        transform: (EditRow) -> EditRow,
    ): EditMealState =
        if (index !in rows.indices) {
            this
        } else {
            copy(rows = rows.mapIndexed { i, r -> if (i == index) transform(r) else r })
        }
}
