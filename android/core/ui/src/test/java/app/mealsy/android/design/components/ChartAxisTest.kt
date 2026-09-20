package app.mealsy.android.design.components

import org.junit.Assert.assertEquals
import org.junit.Test

class ChartAxisTest {
    @Test
    fun `niceAxisMax returns zero for a nonpositive series`() {
        assertEquals(0f, niceAxisMax(0f), 1e-6f)
        assertEquals(0f, niceAxisMax(-5f), 1e-6f)
    }

    @Test
    fun `niceAxisMax rounds small values to the nearest 5`() {
        assertEquals(10f, niceAxisMax(8f), 1e-6f)
        assertEquals(20f, niceAxisMax(20f), 1e-6f)
    }

    @Test
    fun `niceAxisMax rounds mid values to the nearest 10`() {
        assertEquals(60f, niceAxisMax(55f), 1e-6f)
    }

    @Test
    fun `niceAxisMax rounds kcal-scale values to the nearest 200`() {
        assertEquals(400f, niceAxisMax(210f), 1e-6f)
        assertEquals(200f, niceAxisMax(200f), 1e-6f)
    }

    @Test
    fun `niceAxisMax rounds large values to the nearest 500`() {
        assertEquals(1500f, niceAxisMax(1200f), 1e-6f)
    }

    @Test
    fun `niceAxisMax always exceeds the input`() {
        assertEquals(true, niceAxisMax(1840f) > 1840f)
    }

    @Test
    fun `formatThousands inserts US-style separators`() {
        assertEquals("1,840", formatThousands(1840))
        assertEquals("0", formatThousands(0))
        assertEquals("999", formatThousands(999))
        assertEquals("1,000,000", formatThousands(1_000_000))
    }
}
