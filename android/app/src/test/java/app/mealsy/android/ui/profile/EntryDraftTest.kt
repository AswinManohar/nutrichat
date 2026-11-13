package app.mealsy.android.ui.profile

import app.mealsy.data.api.HardEntryDto
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class EntryDraftTest {
    @Test
    fun `allergen group and custom allergy build the right value`() {
        assertEquals("peanut", EntryDraft(allergen = "peanut").toValue()?.get("allergen_group")?.jsonPrimitive?.content)
        assertNull(EntryDraft(allergen = "other", custom = "  ").toValue())
        assertTrue(EntryDraft(allergen = "other", custom = "kiwi").toValue()?.get("custom_terms") is JsonArray)
    }

    @Test
    fun `nutrient limit needs a positive amount and a minimum below it`() {
        val base = EntryDraft(type = CareType.NutrientLimit, nutrient = "protein", unit = "g")
        assertNull(base.toValue())
        assertNull(base.copy(amount = "0").toValue())
        assertNotNull(base.copy(amount = "60").toValue())
        val bad = base.copy(amount = "60", minAmount = "60")
        assertNull(bad.toValue())
        assertTrue(bad.rangeInvalid)
        val ok = base.copy(amount = "60", minAmount = "50").toValue()
        assertEquals("50.0", ok?.get("min_amount")?.jsonPrimitive?.content)
    }

    @Test
    fun `minutes only apply to standing time and must be positive`() {
        val stand = EntryDraft(type = CareType.PhysicalLimitation, limitation = "standing_time")
        assertNotNull(stand.toValue())
        assertNull(stand.copy(minutes = "0").toValue())
        assertEquals("15", stand.copy(minutes = "15").toValue()?.get("max_active_minutes")?.jsonPrimitive?.content)
        assertNull(
            EntryDraft(type = CareType.PhysicalLimitation, limitation = "chewing", minutes = "9").toValue()?.get("max_active_minutes"),
        )
    }

    @Test
    fun `editing prefills the draft from the stored value`() {
        val entry =
            HardEntryDto(
                id = "x",
                type = "nutrient_limit",
                value =
                    JsonObject(
                        mapOf(
                            "nutrient" to JsonPrimitive("sodium"),
                            "amount" to JsonPrimitive(1500.0),
                            "unit" to JsonPrimitive("mg"),
                            "period" to JsonPrimitive("per_day"),
                        ),
                    ),
            )
        val draft = EntryDraft.from(entry)
        assertEquals("1500", draft?.amount)
        assertEquals("sodium", draft?.nutrient)
    }
}
