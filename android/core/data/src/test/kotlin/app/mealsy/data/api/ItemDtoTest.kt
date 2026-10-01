package app.mealsy.data.api

import app.mealsy.domain.CardItem
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
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

    @Test
    fun `UpdateMealRequest emits expected_updated_at and target_qty_g, save dto omits it`() {
        val json = Json { explicitNulls = false }
        val item =
            CardItem(
                foodName = "Rice", qtyG = 200.0, targetQtyG = 150.0, kcal = 260.0, proteinG = 5.0,
                carbsG = 56.0, fatG = 0.6, fiberG = 0.0, fdcId = 1L,
            )
        val body =
            json.encodeToJsonElement(
                UpdateMealRequest.serializer(),
                UpdateMealRequest("Biryani", "2026-10-01T09:12:44.123456+00:00", listOf(item.toUpdateIngredientDto())),
            ).jsonObject
        assertEquals("2026-10-01T09:12:44.123456+00:00", body["expected_updated_at"]!!.jsonPrimitive.content)
        val ing = body["ingredients"]!!.jsonArray[0].jsonObject
        assertEquals(150.0, ing["target_qty_g"]!!.jsonPrimitive.content.toDouble(), 1e-9)
        assertEquals(200.0, ing["qty_g"]!!.jsonPrimitive.content.toDouble(), 1e-9)

        val saved = json.encodeToJsonElement(ItemDto.serializer(), item.toSavedIngredientDto(1.0)).jsonObject
        assertEquals(false, saved.containsKey("target_qty_g"))
    }
}
