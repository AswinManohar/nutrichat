package app.mealsy.domain

import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class CardEditorTest {

    private fun item(
        foodName: String = "Chicken breast",
        qtyG: Double = 100.0,
        targetQtyG: Double = 100.0,
        kcal: Double = 200.0,
        proteinG: Double = 30.0,
        carbsG: Double = 0.0,
        fatG: Double = 5.0,
        fiberG: Double = 0.0,
        fdcId: Long = 1L,
    ): CardItem = CardItem(
        foodName = foodName,
        qtyG = qtyG,
        targetQtyG = targetQtyG,
        kcal = kcal,
        proteinG = proteinG,
        carbsG = carbsG,
        fatG = fatG,
        fiberG = fiberG,
        fdcId = fdcId,
        extras = JsonObject(emptyMap()),
    )

    @Test
    fun `removeItem drops the row`() {
        val card = ConfirmationCard(
            message = "Logged",
            items = listOf(item(foodName = "A"), item(foodName = "B")),
        )

        val result = CardEditor.removeItem(card, 0)

        assertEquals(1, result.items.size)
        assertEquals("B", result.items[0].foodName)
    }

    @Test
    fun `editQty rejects nonpositive`() {
        val card = ConfirmationCard(message = "Logged", items = listOf(item()))

        assertThrows(IllegalArgumentException::class.java) {
            CardEditor.editQty(card, 0, 0.0)
        }
        assertThrows(IllegalArgumentException::class.java) {
            CardEditor.editQty(card, 0, -10.0)
        }
    }

    @Test
    fun `totals scale linearly with targetQtyG`() {
        val card = ConfirmationCard(
            message = "Logged",
            items = listOf(item(qtyG = 100.0, targetQtyG = 100.0, kcal = 200.0)),
        )

        val edited = CardEditor.editQty(card, 0, 150.0)
        val totals = CardEditor.totals(edited)

        assertEquals(300.0, totals.kcal, 1e-9)
    }

    @Test
    fun `totals scale with portion`() {
        val card = ConfirmationCard(
            message = "Logged",
            items = listOf(item(qtyG = 100.0, targetQtyG = 100.0, kcal = 200.0, proteinG = 30.0)),
        )

        val halved = CardEditor.setPortion(card, 0.5)
        val totals = CardEditor.totals(halved)

        assertEquals(100.0, totals.kcal, 1e-9)
        assertEquals(15.0, totals.proteinG, 1e-9)
    }

    @Test
    fun `removing last item yields empty items`() {
        val card = ConfirmationCard(message = "Logged", items = listOf(item()))

        val result = CardEditor.removeItem(card, 0)

        assertTrue(result.items.isEmpty())
    }
}
