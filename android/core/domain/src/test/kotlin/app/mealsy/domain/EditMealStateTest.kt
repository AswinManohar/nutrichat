package app.mealsy.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class EditMealStateTest {
    private fun item(
        name: String,
        qty: Double = 100.0,
        kcal: Double = 200.0,
    ) = CardItem(
        foodName = name,
        qtyG = qty,
        targetQtyG = qty,
        kcal = kcal,
        proteinG = 10.0,
        carbsG = 20.0,
        fatG = 5.0,
        fiberG = 1.0,
        fdcId = 1L,
    )

    private fun state() =
        EditMealState.from("m1", "Biryani", "2026-10-01T09:00:00+00:00", listOf(item("Rice"), item("Chicken")))

    @Test
    fun `fresh state is clean and cannot save`() {
        val s = state()
        assertFalse(s.isDirty)
        assertFalse(s.canSave)
        assertEquals(400.0, s.totals.kcal, 1e-9)
    }

    @Test
    fun `setQty scales totals and marks dirty`() {
        val s = state().setQty(0, 50.0)
        assertTrue(s.isDirty)
        assertTrue(s.canSave)
        assertEquals(300.0, s.totals.kcal, 1e-9)
    }

    @Test
    fun `restoring the original weight is clean again`() {
        assertFalse(state().setQty(0, 50.0).setQty(0, 100.0).isDirty)
    }

    @Test
    fun `rename dirty and blank or symbol-only name blocks save`() {
        val s = state().rename("Biryani 2")
        assertTrue(s.canSave)
        assertFalse(s.rename("  --  ").canSave)
        assertFalse(s.rename("").canSave)
    }

    @Test
    fun `whitespace-only rename is not dirty`() {
        assertFalse(state().rename(" Biryani ").isDirty)
    }

    @Test
    fun `zero weight on a kept row blocks save`() {
        assertFalse(state().setQty(0, 0.0).canSave)
    }

    @Test
    fun `zero weight on a removed row does not block save`() {
        assertTrue(state().setQty(0, 0.0).remove(0).canSave)
    }

    @Test
    fun `remove drops from totals and undo restores`() {
        val removed = state().remove(1)
        assertEquals(200.0, removed.totals.kcal, 1e-9)
        assertTrue(removed.isDirty)
        val undone = removed.undoRemove(1)
        assertEquals(400.0, undone.totals.kcal, 1e-9)
        assertFalse(undone.isDirty)
    }

    @Test
    fun `remove refuses the last kept row`() {
        val s = state().remove(0).remove(1)
        assertEquals(1, s.keptRows.size)
        assertFalse(s.rows[1].removed)
    }

    @Test
    fun `keptItemsForSave sets targetQtyG to edited weight and omits removed`() {
        val kept = state().setQty(0, 150.0).remove(1).keptItemsForSave()
        assertEquals(1, kept.size)
        assertEquals("Rice", kept[0].foodName)
        assertEquals(150.0, kept[0].targetQtyG, 1e-9)
        assertEquals(100.0, kept[0].qtyG, 1e-9)
    }

    @Test
    fun `out-of-range indices are no-ops`() {
        val s = state()
        assertEquals(s, s.setQty(9, 1.0))
        assertEquals(s, s.remove(9))
        assertEquals(s, s.undoRemove(9))
    }

    @Test
    fun `reset replaces name baseline and rows`() {
        val s = state().setQty(0, 1.0).reset("Other", "2026-10-02T00:00:00+00:00", listOf(item("Egg")))
        assertEquals("m1", s.mealId)
        assertEquals("Other", s.name)
        assertEquals("2026-10-02T00:00:00+00:00", s.baseUpdatedAt)
        assertEquals(1, s.rows.size)
        assertFalse(s.isDirty)
    }
}
