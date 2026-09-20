package app.mealsy.data.api

import app.mealsy.domain.CardItem
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Test

/** Verifies [CardItem.toSavedIngredientDto] carries every field the backend's POST /my-meals expects. */
class ItemDtoTest {
    @Test
    fun `toSavedIngredientDto carries carbs fat fiber source estimated candidates and fdcId`() {
        val item =
            CardItem(
                foodName = "Chicken breast",
                qtyG = 100.0,
                targetQtyG = 100.0,
                kcal = 200.0,
                proteinG = 30.0,
                carbsG = 10.0,
                fatG = 5.0,
                fiberG = 2.0,
                fdcId = 12345L,
                estimated = true,
                extras = JsonObject(emptyMap()),
                candidates = listOf("Chicken breast, roasted", "Chicken breast, grilled"),
                source = "usda",
            )

        val dto = item.toSavedIngredientDto(portion = 1.0)

        assertEquals(10.0, dto.carbsG, 1e-9)
        assertEquals(5.0, dto.fatG, 1e-9)
        assertEquals(2.0, dto.fiberG, 1e-9)
        assertEquals("usda", dto.source)
        assertEquals(true, dto.estimated)
        assertEquals(listOf("Chicken breast, roasted", "Chicken breast, grilled"), dto.candidates)
        assertEquals(12345L, dto.fdcId)
    }
}
