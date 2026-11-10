package app.mealsy.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class MicronutrientSummaryTest {
    private val sodium = MicroNutrient("sodium", "Sodium", "mg", isLimit = true, dailyValue = 2300.0)
    private val iron = MicroNutrient("iron", "Iron", "mg", isLimit = false, dailyValue = 18.0)
    private val zinc = MicroNutrient("zinc", "Zinc", "mg", isLimit = false, dailyValue = 11.0)
    private val iodine = MicroNutrient("iodine", "Iodine", "mcg", isLimit = false, dailyValue = 150.0)

    private val tabs =
        listOf(
            MicroTab("electrolytes", "Electrolytes", listOf(sodium)),
            MicroTab("minerals", "Minerals", listOf(iron, zinc, iodine)),
        )

    private fun day(
        totals: Map<String, Double>,
        foods: List<MicroFood> = emptyList(),
    ) = MicroDay(logged = true, totals = totals, foods = foods)

    private val empty = MicroDay(logged = false, totals = emptyMap(), foods = emptyList())

    @Test
    fun noLoggedDay_isNoData() {
        assertNull(buildMicroSummary(tabs, listOf(empty, empty)))
    }

    @Test
    fun averagesOnlyOverLoggedDays() {
        val summary = buildMicroSummary(tabs, listOf(day(mapOf("iron" to 9.0)), empty, day(mapOf("iron" to 27.0))))!!
        val row = summary.tabs[1].rows.first { it.nutrient.key == "iron" }
        assertEquals(18.0, row.avgAmount!!, 1e-9)
        assertEquals(100, row.pct)
        assertEquals(2, summary.daysLogged)
    }

    @Test
    fun unknownKey_isNullNotZero() {
        val summary = buildMicroSummary(tabs, listOf(day(mapOf("iron" to 9.0))))!!
        val iodineRow = summary.tabs[1].rows.first { it.nutrient.key == "iodine" }
        assertNull(iodineRow.avgAmount)
        assertNull(iodineRow.pct)
    }

    @Test
    fun hero_countsTargetsWithDataAndSkipsLimits() {
        // iron 50% (counts), zinc 20% (doesn't), iodine unknown (excluded), sodium is a limit.
        val summary =
            buildMicroSummary(tabs, listOf(day(mapOf("iron" to 9.0, "zinc" to 2.2, "sodium" to 2300.0))))!!
        assertEquals(1, summary.heroCount)
        assertEquals(2, summary.heroTotal)
    }

    @Test
    fun topFoods_rankByAmountMergedAcrossDaysByHumanizedName() {
        val days =
            listOf(
                day(
                    mapOf("iron" to 6.0),
                    listOf(
                        MicroFood("Lentils, mature seeds, cooked, boiled", mapOf("iron" to 3.0)),
                        MicroFood("spinach", mapOf("iron" to 2.0)),
                    ),
                ),
                day(
                    mapOf("iron" to 6.0),
                    listOf(
                        MicroFood("lentils", mapOf("iron" to 3.0)),
                        MicroFood("bread", mapOf("iron" to 2.5)),
                        MicroFood("water", mapOf("iron" to 0.0)),
                    ),
                ),
            )
        val row = buildMicroSummary(tabs, days)!!.tabs[1].rows.first { it.nutrient.key == "iron" }
        assertEquals(listOf("Lentils", "Bread"), row.topFoods)
    }

    @Test
    fun lowestTarget_isTheLowestTargetUnderHalf() {
        val summary =
            buildMicroSummary(tabs, listOf(day(mapOf("iron" to 7.2, "zinc" to 2.2, "sodium" to 100.0))))!!
        assertEquals("zinc", lowestTarget(summary.tabs[1])!!.nutrient.key)
        // The electrolytes tab only has a limit, which never gets a tip.
        assertNull(lowestTarget(summary.tabs[0]))
    }

    @Test
    fun lowestTarget_nullWhenAllPastHalf() {
        val summary = buildMicroSummary(tabs, listOf(day(mapOf("iron" to 18.0, "zinc" to 11.0, "iodine" to 150.0))))!!
        assertNull(lowestTarget(summary.tabs[1]))
    }
}
