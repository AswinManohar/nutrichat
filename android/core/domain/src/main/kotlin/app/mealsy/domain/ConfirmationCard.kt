package app.mealsy.domain

/**
 * A confirmation card presented to the user after meal extraction, holding
 * the resolved [items] pending edit and confirmation.
 *
 * @property portion Overall multiplier applied on top of each item's own
 *   qty edit — e.g. "half of this meal".
 */
data class ConfirmationCard(
    val message: String,
    val items: List<CardItem>,
    val mealType: String = "unspecified",
    val portion: Double = 1.0,
)
