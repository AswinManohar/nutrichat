package app.mealsy.android.ui.mymeals

import org.junit.Assert.assertEquals
import org.junit.Test

/** Unit tests for [displayName]'s USDA-vs-user-name heuristic. */
class DisplayNameTest {
    @Test
    fun `comma separated USDA description is humanized`() {
        assertEquals(
            "Grilled chicken breast",
            displayName("Chicken, broiler or fryers, breast, meat only, cooked, grilled"),
        )
    }

    @Test
    fun `all caps name with no comma is humanized`() {
        assertEquals("Chicken breast", displayName("CHICKEN BREAST"))
    }

    @Test
    fun `user typed title case name passes through verbatim`() {
        assertEquals("Usual breakfast", displayName("Usual breakfast"))
    }

    @Test
    fun `user typed name with lowercase words passes through verbatim`() {
        assertEquals("my post-workout shake", displayName("my post-workout shake"))
    }

    @Test
    fun `blank input passes through`() {
        assertEquals("", displayName(""))
    }
}
