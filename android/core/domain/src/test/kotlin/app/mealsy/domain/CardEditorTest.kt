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
    ): CardItem =
        CardItem(
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
        val card =
            ConfirmationCard(
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
        val card =
            ConfirmationCard(
                message = "Logged",
                items = listOf(item(qtyG = 100.0, targetQtyG = 100.0, kcal = 200.0)),
            )

        val edited = CardEditor.editQty(card, 0, 150.0)
        val totals = CardEditor.totals(edited)

        assertEquals(300.0, totals.kcal, 1e-9)
    }

    @Test
    fun `totals scale with portion`() {
        val card =
            ConfirmationCard(
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
        val card =
            ConfirmationCard(
                message = "Logged",
                items =
                    listOf(
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
        val card =
            ConfirmationCard(
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
        val estimatedHighFat =
            item(kcal = 100.0, proteinG = 0.0, carbsG = 0.0, fatG = 20.0)
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
        assertEquals("snack", defaultMealCategory(java.time.LocalTime.of(4, 59)))
        assertEquals("breakfast", defaultMealCategory(java.time.LocalTime.of(5, 0)))
        assertEquals("breakfast", defaultMealCategory(java.time.LocalTime.of(10, 59)))
        assertEquals("lunch", defaultMealCategory(java.time.LocalTime.of(11, 0)))
        assertEquals("lunch", defaultMealCategory(java.time.LocalTime.of(14, 59)))
        assertEquals("snack", defaultMealCategory(java.time.LocalTime.of(15, 0)))
        assertEquals("snack", defaultMealCategory(java.time.LocalTime.of(16, 59)))
        assertEquals("dinner", defaultMealCategory(java.time.LocalTime.of(17, 0)))
        assertEquals("dinner", defaultMealCategory(java.time.LocalTime.of(21, 59)))
        assertEquals("snack", defaultMealCategory(java.time.LocalTime.of(22, 0)))
        assertEquals("snack", defaultMealCategory(java.time.LocalTime.of(23, 59)))
        assertEquals("snack", defaultMealCategory(java.time.LocalTime.of(0, 0)))
    }

    @Test
    fun `scaledQtyG multiplies targetQtyG by the card's portion`() {
        val i = item(targetQtyG = 127.0)

        assertEquals(127.0, CardEditor.scaledQtyG(i, portion = 1.0), 0.0001)
        assertEquals(254.0, CardEditor.scaledQtyG(i, portion = 2.0), 0.0001)
        assertEquals(63.5, CardEditor.scaledQtyG(i, portion = 0.5), 0.0001)
    }

    private fun card(items: List<CardItem>): ConfirmationCard =
        ConfirmationCard(message = "", items = items, mealType = "lunch", portion = 1.0)

    @Test
    fun `swapItem keeps targetQtyG and meal type, replacing the matched food`() {
        val old = item(foodName = "Shrimp toast", qtyG = 28.0, targetQtyG = 56.0, fdcId = 2345L)
        val newFood = item(foodName = "Bread, white, toasted", qtyG = 28.0, targetQtyG = 28.0, fdcId = 172687L)
        val c = card(listOf(old))

        val result = CardEditor.swapItem(c, 0, newFood, method = "search", query = "white bread toasted")

        assertEquals("lunch", result.mealType)
        assertEquals(56.0, result.items[0].targetQtyG, 0.0001)
        assertEquals(172687L, result.items[0].fdcId)
        val correction = result.items[0].pendingCorrection
        assertEquals(2345L, correction?.fromFdcId)
        assertEquals("Shrimp toast", correction?.fromName)
        assertEquals(172687L, correction?.toFdcId)
        assertEquals("search", correction?.method)
    }

    @Test
    fun `swapItem twice keeps from_ pointing at the originally matched food`() {
        val original = item(foodName = "Shrimp toast", fdcId = 2345L)
        var c = card(listOf(original))

        val first = item(foodName = "Melba toast", fdcId = 111L)
        c = CardEditor.swapItem(c, 0, first, method = "suggestion")
        val second = item(foodName = "Bread, white, toasted", fdcId = 172687L)
        c = CardEditor.swapItem(c, 0, second, method = "search", query = "white bread toasted")

        val correction = c.items[0].pendingCorrection
        assertEquals(2345L, correction?.fromFdcId)
        assertEquals("Shrimp toast", correction?.fromName)
        assertEquals(172687L, correction?.toFdcId)
    }

    @Test
    fun `swapItem is a no-op when selecting the current match`() {
        val current = item(fdcId = 42L)
        val c = card(listOf(current))

        val result = CardEditor.swapItem(c, 0, item(fdcId = 42L, foodName = "Same food"), method = "search")

        assertEquals(c, result)
    }

    @Test
    fun `swapItem from an estimate leaves from_fdc_id null`() {
        val estimate =
            CardItem(
                foodName = "Homemade soup",
                qtyG = 200.0,
                targetQtyG = 200.0,
                kcal = 150.0,
                proteinG = 8.0,
                carbsG = 10.0,
                fatG = 5.0,
                fiberG = 2.0,
                fdcId = 0L,
                estimated = true,
                extras = JsonObject(emptyMap()),
            )
        val c = card(listOf(estimate))

        val result = CardEditor.swapItem(c, 0, item(fdcId = 555L, foodName = "Chicken soup"), method = "search")

        assertEquals(null, result.items[0].pendingCorrection?.fromFdcId)
    }

    @Test
    fun `swapping one part of a composite dish keeps the rest of the group intact (E2)`() {
        val chicken =
            item(foodName = "Chicken, broilers or fryers, breast, meat only, cooked, roasted", fdcId = 1L)
                .copy(sourceDish = "Chicken caesar salad")
        val lettuce =
            item(foodName = "Lettuce, cos or romaine, raw", fdcId = 2L)
                .copy(sourceDish = "Chicken caesar salad")
        val c = card(listOf(chicken, lettuce))

        val replacement = item(foodName = "Chicken, broilers or fryers, breast, meat only, cooked, grilled", fdcId = 9L)
        val result = CardEditor.swapItem(c, 0, replacement, method = "search", query = "grilled chicken breast")

        // The swapped item keeps its place in the composite group...
        assertEquals("Chicken caesar salad", result.items[0].sourceDish)
        assertEquals(9L, result.items[0].fdcId)
        // ...and the untouched sibling is unaffected.
        assertEquals("Chicken caesar salad", result.items[1].sourceDish)
        assertEquals(2L, result.items[1].fdcId)
        assertEquals(lettuce, result.items[1])
    }

    @Test
    fun `undoSwap restores the previous item exactly`() {
        val old = item(fdcId = 2345L, foodName = "Shrimp toast")
        val c = card(listOf(old))
        val swapped = CardEditor.swapItem(c, 0, item(fdcId = 172687L, foodName = "Bread, white, toasted"), method = "search")

        val restored = CardEditor.undoSwap(swapped, 0, old)

        assertEquals(old, restored.items[0])
    }
}
