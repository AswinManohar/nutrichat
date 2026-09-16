package app.mealsy.domain

import org.junit.Assert.assertEquals
import org.junit.Test

class FoodNameHumanizerTest {

    private val cases: List<Pair<String, String>> = listOf(
        "Chicken, broiler or fryers, breast, skinless, boneless, meat only, cooked, grilled" to
            "Grilled chicken breast",
        "Egg, whole, cooked, scrambled" to "Scrambled egg",
        "Bread, whole-wheat, commercially prepared, toasted" to "Toasted whole-wheat bread",
        "Yogurt, Greek, plain, nonfat" to "Greek yogurt",
        "Rice, white, long-grain, regular, enriched, cooked" to "Cooked white rice",
        "Beef, ground, 80% lean meat / 20% fat, raw" to "Ground beef",
        "Oil, olive, salad or cooking" to "Olive oil",
        "Milk, whole, 3.25% milkfat, with added vitamin D" to "Whole milk",
        "Broccoli, raw" to "Broccoli",
        "Cheese, cheddar" to "Cheddar cheese",
        "Potatoes, russet, flesh and skin, baked" to "Baked russet potatoes",
        "Salmon, Atlantic, farmed, cooked, dry heat" to "Cooked Atlantic salmon",
        "Apples, raw, with skin" to "Apples with skin",
    )

    @Test
    fun `humanize matches the expected title for each USDA description`() {
        for ((raw, expected) in cases) {
            assertEquals("for input: $raw", expected, FoodNameHumanizer.humanize(raw))
        }
    }

    @Test
    fun `blank input returns the trimmed input`() {
        assertEquals("", FoodNameHumanizer.humanize("   "))
        assertEquals("", FoodNameHumanizer.humanize(""))
    }

    @Test
    fun `no-comma input passes through with only sentence-casing`() {
        assertEquals("Water", FoodNameHumanizer.humanize("Water"))
        assertEquals("Sourdough bread", FoodNameHumanizer.humanize("sourdough bread"))
    }

    @Test
    fun `humanize is idempotent`() {
        for ((raw, _) in cases) {
            val once = FoodNameHumanizer.humanize(raw)
            val twice = FoodNameHumanizer.humanize(once)
            assertEquals("idempotency for input: $raw", once, twice)
        }
    }
}
