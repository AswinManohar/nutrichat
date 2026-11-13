package app.mealsy.domain

/**
 * A confirmation card presented to the user after meal extraction, holding
 * the resolved [items] pending edit and confirmation.
 *
 * @property portion Overall multiplier applied on top of each item's own
 *   qty edit — e.g. "half of this meal".
 * @property warnings The backend's Care profile check of these items
 *   (spec 013 FR-044), most serious first.
 */
data class ConfirmationCard(
    val message: String,
    val items: List<CardItem>,
    val mealType: String = "unspecified",
    val portion: Double = 1.0,
    val warnings: List<CardWarning> = emptyList(),
) {
    /** An allergy or medication interaction: the meal saves only on "Log anyway". */
    val needsAck: Boolean get() = warnings.any { it.needsAck }
}

/**
 * One Care profile reminder on a card.
 *
 * @property needsAck True for an allergy, a medication-food interaction, or a
 *   check that could not run; false for a reminder that logs normally.
 */
data class CardWarning(
    val text: String,
    val needsAck: Boolean,
)
