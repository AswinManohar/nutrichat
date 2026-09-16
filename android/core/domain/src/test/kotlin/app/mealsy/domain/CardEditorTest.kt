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

    @Test
    fun `totals fills all five macros under grams edit times portion`() {
        val card = ConfirmationCard(
            message = "Logged",
            items = listOf(
                item(
                    qtyG = 100.0,
                    targetQtyG = 100.0,
                    kcal = 200.0,
                    proteinG = 30.0,
                    carbsG = 10.0,
                    fatG = 5.0,
                    fiberG = 2.0,
                ),
            ),
            portion = 1.0,
        )

        val edited = CardEditor.editQty(card, 0, 200.0)
        val halved = CardEditor.setPortion(edited, 0.5)
        val totals = CardEditor.totals(halved)

        // factor = (200/100) * 0.5 = 1.0 -> totals equal the base macros.
        assertEquals(200.0, totals.kcal, 1e-9)
        assertEquals(30.0, totals.proteinG, 1e-9)
        assertEquals(10.0, totals.carbsG, 1e-9)
        assertEquals(5.0, totals.fatG, 1e-9)
        assertEquals(2.0, totals.fiberG, 1e-9)
    }

    @Test
    fun `totals treats a zero qtyG item as a zero factor instead of NaN`() {
        val card = ConfirmationCard(
            message = "Logged",
            items = listOf(item(qtyG = 0.0, targetQtyG = 100.0, kcal = 200.0)),
        )

        val totals = CardEditor.totals(card)

        assertEquals(0.0, totals.kcal, 1e-9)
        assertTrue(totals.kcal.isFinite())
    }

    @Test
    fun `replaceCandidate sets pendingCandidate without touching foodName`() {
        val card = ConfirmationCard(message = "Logged", items = listOf(item(foodName = "Chicken")))

        val result = CardEditor.replaceCandidate(card, 0, "Turkey")

        assertEquals("Chicken", result.items[0].foodName)
        assertEquals("Turkey", result.items[0].pendingCandidate)
    }

    @Test
    fun `replaceCandidate is a no-op when index is out of range`() {
        val card = ConfirmationCard(message = "Logged", items = listOf(item()))

        val result = CardEditor.replaceCandidate(card, 5, "Turkey")

        assertEquals(card, result)
    }

    @Test
    fun `pastelToneFor picks Powder for estimated items regardless of macros`() {
        val estimatedHighFat = item(kcal = 100.0, proteinG = 0.0, carbsG = 0.0, fatG = 20.0)
            .copy(estimated = true)

        assertEquals(PastelTone.Powder, pastelToneFor(estimatedHighFat))
    }

    @Test
    fun `pastelToneFor picks Butter when fat share is at least 0_4`() {
        // fat kcal = 9*10 = 90, total kcal = 100 -> share 0.9
        val highFat = item(kcal = 100.0, proteinG = 1.0, carbsG = 0.0, fatG = 10.0)

        assertEquals(PastelTone.Butter, pastelToneFor(highFat))
    }

    @Test
    fun `pastelToneFor picks Leaf when protein share is at least 0_3 and fat share is low`() {
        // protein kcal = 4*20 = 80, total kcal = 100 -> share 0.8; fat share 0
        val highProtein = item(kcal = 100.0, proteinG = 20.0, carbsG = 5.0, fatG = 0.0)

        assertEquals(PastelTone.Leaf, pastelToneFor(highProtein))
    }

    @Test
    fun `pastelToneFor falls back to Leaf when neither threshold is met`() {
        // fat share 9*1/100 = 0.09, protein share 4*1/100 = 0.04
        val balanced = item(kcal = 100.0, proteinG = 1.0, carbsG = 20.0, fatG = 1.0)

        assertEquals(PastelTone.Leaf, pastelToneFor(balanced))
    }

    @Test
    fun `pastelToneFor derives denominator from macros when kcal is zero`() {
        // macro kcal = 4*0 + 4*0 + 9*10 = 90 -> fat share 1.0 -> Butter
        val zeroKcalHighFat = item(kcal = 0.0, proteinG = 0.0, carbsG = 0.0, fatG = 10.0)

        assertEquals(PastelTone.Butter, pastelToneFor(zeroKcalHighFat))
    }

    @Test
    fun `pastelToneFor returns Leaf when both kcal and macros are zero`() {
        val allZero = item(kcal = 0.0, proteinG = 0.0, carbsG = 0.0, fatG = 0.0)

        assertEquals(PastelTone.Leaf, pastelToneFor(allZero))
    }

    @Test
    fun `defaultMealCategory boundaries`() {
        assertEquals("breakfast", defaultMealCategory(java.time.LocalTime.of(9, 0)))
        assertEquals("breakfast", defaultMealCategory(java.time.LocalTime.of(10, 29)))
        assertEquals("lunch", defaultMealCategory(java.time.LocalTime.of(10, 30)))
        assertEquals("lunch", defaultMealCategory(java.time.LocalTime.of(14, 59)))
        assertEquals("dinner", defaultMealCategory(java.time.LocalTime.of(15, 0)))
        assertEquals("dinner", defaultMealCategory(java.time.LocalTime.of(19, 59)))
        assertEquals("snack", defaultMealCategory(java.time.LocalTime.of(20, 0)))
        assertEquals("snack", defaultMealCategory(java.time.LocalTime.of(23, 59)))
        assertEquals("breakfast", defaultMealCategory(java.time.LocalTime.of(0, 0)))
    }
}
