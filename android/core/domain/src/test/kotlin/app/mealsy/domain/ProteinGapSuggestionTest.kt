package app.mealsy.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ProteinGapSuggestionTest {
    @Test
    fun `no nudge before the first meal of the day`() {
        assertNull(
            proteinGapSuggestion(
                gapG = 110,
                mealsLoggedToday = 0,
                dayPart = ProteinGapDayPart.Afternoon,
                dietaryPrefs = emptyMap(),
            ),
        )
    }

    @Test
    fun `gap below the threshold is not worth a note`() {
        assertNull(
            proteinGapSuggestion(
                gapG = PROTEIN_GAP_THRESHOLD_G - 1,
                mealsLoggedToday = 1,
                dayPart = ProteinGapDayPart.Afternoon,
                dietaryPrefs = emptyMap(),
            ),
        )
    }

    @Test
    fun `gap exactly at the threshold is a single-food suggestion`() {
        val result =
            proteinGapSuggestion(
                gapG = PROTEIN_GAP_THRESHOLD_G,
                mealsLoggedToday = 1,
                dayPart = ProteinGapDayPart.Afternoon,
                dietaryPrefs = emptyMap(),
            )
        assertEquals(ProteinGapSuggestion.SingleFood(PROTEIN_GAP_THRESHOLD_G, ProteinFood.GreekYogurt), result)
    }

    @Test
    fun `gap exactly at the single-food max is still a single-food suggestion`() {
        val result =
            proteinGapSuggestion(
                gapG = PROTEIN_GAP_SINGLE_FOOD_MAX_G,
                mealsLoggedToday = 1,
                dayPart = ProteinGapDayPart.Morning,
                dietaryPrefs = emptyMap(),
            )
        assertEquals(ProteinGapSuggestion.SingleFood(PROTEIN_GAP_SINGLE_FOOD_MAX_G, ProteinFood.Egg), result)
    }

    @Test
    fun `gap above the single-food max spreads across meals instead`() {
        val result =
            proteinGapSuggestion(
                gapG = 110,
                mealsLoggedToday = 1,
                dayPart = ProteinGapDayPart.Afternoon,
                dietaryPrefs = emptyMap(),
            )
        assertEquals(ProteinGapSuggestion.Spread(110), result)
    }

    @Test
    fun `day part picks the everyday food when no prefs are set`() {
        val prefs = emptyMap<String, Boolean>()
        assertEquals(
            ProteinFood.Egg,
            (proteinGapSuggestion(15, 1, ProteinGapDayPart.Morning, prefs) as ProteinGapSuggestion.SingleFood).food,
        )
        assertEquals(
            ProteinFood.GreekYogurt,
            (proteinGapSuggestion(15, 1, ProteinGapDayPart.Afternoon, prefs) as ProteinGapSuggestion.SingleFood).food,
        )
        assertEquals(
            ProteinFood.Milk,
            (proteinGapSuggestion(15, 1, ProteinGapDayPart.Evening, prefs) as ProteinGapSuggestion.SingleFood).food,
        )
    }

    @Test
    fun `vegan never gets egg or dairy`() {
        val prefs = mapOf("vegan" to true)
        for (dayPart in ProteinGapDayPart.entries) {
            val food = (proteinGapSuggestion(15, 1, dayPart, prefs) as ProteinGapSuggestion.SingleFood).food
            assertEquals(ProteinFood.Tofu, food)
        }
    }

    @Test
    fun `vegetarian can still get egg or dairy`() {
        val prefs = mapOf("vegetarian" to true)
        assertEquals(
            ProteinFood.Egg,
            (proteinGapSuggestion(15, 1, ProteinGapDayPart.Morning, prefs) as ProteinGapSuggestion.SingleFood).food,
        )
    }

    @Test
    fun `pescatarian is treated like vegetarian for protein-gap food (no meat candidates exist)`() {
        val prefs = mapOf("pescatarian" to true)
        assertEquals(
            ProteinFood.GreekYogurt,
            (proteinGapSuggestion(15, 1, ProteinGapDayPart.Afternoon, prefs) as ProteinGapSuggestion.SingleFood).food,
        )
    }

    @Test
    fun `no dairy skips yogurt and milk but keeps egg`() {
        val prefs = mapOf("no_dairy" to true)
        assertEquals(
            ProteinFood.Egg,
            (proteinGapSuggestion(15, 1, ProteinGapDayPart.Afternoon, prefs) as ProteinGapSuggestion.SingleFood).food,
        )
        assertEquals(
            ProteinFood.Egg,
            (proteinGapSuggestion(15, 1, ProteinGapDayPart.Evening, prefs) as ProteinGapSuggestion.SingleFood).food,
        )
    }

    @Test
    fun `vegan and no dairy combined still falls back to tofu`() {
        val prefs = mapOf("vegan" to true, "no_dairy" to true)
        assertEquals(
            ProteinFood.Tofu,
            (proteinGapSuggestion(15, 1, ProteinGapDayPart.Morning, prefs) as ProteinGapSuggestion.SingleFood).food,
        )
    }

    @Test
    fun `zero meals logged suppresses the note even with a huge gap`() {
        assertNull(
            proteinGapSuggestion(
                gapG = 110,
                mealsLoggedToday = 0,
                dayPart = ProteinGapDayPart.Afternoon,
                dietaryPrefs = mapOf("vegan" to true),
            ),
        )
    }
}
