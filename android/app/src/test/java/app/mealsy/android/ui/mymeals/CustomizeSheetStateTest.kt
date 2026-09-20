package app.mealsy.android.ui.mymeals

import app.mealsy.domain.CardItem
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Unit tests for [CustomizeSheetState]'s pure edit/removal/totals logic. */
class CustomizeSheetStateTest {
    private fun ingredient(
        index: Int,
        qtyG: Double,
        kcal: Double,
        proteinG: Double = 0.0,
    ): CustomizeIngredient =
        CustomizeIngredient(
            index = index,
            item =
                CardItem(
                    foodName = "food-$index",
                    qtyG = qtyG,
                    targetQtyG = qtyG,
                    kcal = kcal,
                    proteinG = proteinG,
                    carbsG = 0.0,
                    fatG = 0.0,
                    fiberG = 0.0,
                    fdcId = index.toLong(),
                    estimated = false,
                    extras = JsonObject(emptyMap()),
                ),
            humanizedName = "Food $index",
            rawNameIfDifferent = null,
        )

    private fun initialState() =
        CustomizeSheetState.initial(
            ingredients =
                listOf(
                    ingredient(index = 0, qtyG = 100.0, kcal = 200.0, proteinG = 10.0),
                    ingredient(index = 1, qtyG = 50.0, kcal = 100.0, proteinG = 5.0),
                    ingredient(index = 2, qtyG = 80.0, kcal = 150.0, proteinG = 8.0),
                ),
            mealType = "lunch",
        )

    @Test
    fun `removing a row omits it from the payload without renumbering remaining indices`() {
        val state = initialState().withRemoved(1)

        val indices = state.overridePayload.map { it.index }
        assertEquals(listOf(0, 2), indices)
    }

    @Test
    fun `changing a stepper value changes that row's qtyG in the payload`() {
        val state = initialState().withQty(0, 150)

        val override = state.overridePayload.first { it.index == 0 }
        assertEquals(150.0, override.qtyG, 0.0001)
        // Sibling rows are untouched.
        val sibling = state.overridePayload.first { it.index == 1 }
        assertEquals(50.0, sibling.qtyG, 0.0001)
    }

    @Test
    fun `portion and gram edits both flow into live totals`() {
        val base = initialState()
        val baseKcal = base.totals.kcal

        val doubledQty = base.withQty(0, 200) // was 100g -> 200g, doubling that row's contribution
        assertTrue(doubledQty.totals.kcal > baseKcal)

        val halfPortion = base.withPortion(0.5)
        assertEquals(baseKcal * 0.5, halfPortion.totals.kcal, 0.0001)
    }

    @Test
    fun `totals equal CardEditor totals over the kept scaled items`() {
        val state = initialState().withRemoved(1).withQty(0, 200).withPortion(0.5)

        val expected =
            app.mealsy.domain.CardEditor.totals(
                app.mealsy.domain.ConfirmationCard(
                    message = "",
                    items = state.keptIngredients.map { it.item },
                    mealType = state.mealType,
                    portion = state.portion,
                ),
            )

        assertEquals(expected.kcal, state.totals.kcal, 0.0001)
        assertEquals(expected.proteinG, state.totals.proteinG, 0.0001)
        assertEquals(expected.carbsG, state.totals.carbsG, 0.0001)
        assertEquals(expected.fatG, state.totals.fatG, 0.0001)
        assertEquals(expected.fiberG, state.totals.fiberG, 0.0001)
    }

    @Test
    fun `removed row is excluded from kept ingredients`() {
        val state = initialState().withRemoved(2)
        assertFalse(state.keptIngredients.any { it.index == 2 })
        assertEquals(2, state.keptIngredients.size)
    }
}
