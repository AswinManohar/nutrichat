package app.mealsy.android.ui.micronutrients

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import app.mealsy.android.ui.AppScreenshotTestBase
import app.mealsy.android.ui.common.ErrorKind
import app.mealsy.domain.MicroDay
import app.mealsy.domain.MicroFood
import app.mealsy.domain.MicroNutrient
import app.mealsy.domain.MicroRange
import app.mealsy.domain.MicroTab
import app.mealsy.domain.buildMicroSummary
import org.junit.Test

/**
 * Goldens for the Micronutrients screen, seeded with the design mock's own
 * percentages (`Mealsy Micronutrients.dc.html`): a limit (sodium), a label
 * inside its bar (phosphorus 88%), an over-axis bar (vitamin C 112%) and an
 * outlined low bar (vitamin D 18%).
 */
class MicronutrientsGoldenTest : AppScreenshotTestBase() {
    private fun n(
        key: String,
        name: String,
        unit: String,
        dv: Double,
        limit: Boolean = false,
    ) = MicroNutrient(key, name, unit, limit, dv)

    private val tabs =
        listOf(
            MicroTab(
                "electrolytes",
                "Electrolytes",
                listOf(
                    n("sodium", "Sodium", "mg", 2300.0, limit = true),
                    n("potassium", "Potassium", "mg", 4700.0),
                    n("calcium", "Calcium", "mg", 1300.0),
                    n("magnesium", "Magnesium", "mg", 420.0),
                    n("phosphorus", "Phosphorus", "mg", 1250.0),
                ),
            ),
            MicroTab(
                "vitamins",
                "Vitamins",
                listOf(
                    n("vitamin_a", "Vitamin A", "mcg", 900.0),
                    n("vitamin_c", "Vitamin C", "mg", 90.0),
                    n("vitamin_d", "Vitamin D", "mcg", 20.0),
                    n("vitamin_e", "Vitamin E", "mg", 15.0),
                    n("vitamin_k", "Vitamin K", "mcg", 120.0),
                    n("vitamin_b12", "Vitamin B12", "mcg", 2.4),
                    n("folate", "Folate", "mcg", 400.0),
                ),
            ),
            MicroTab(
                "minerals",
                "Minerals",
                listOf(
                    n("iron", "Iron", "mg", 18.0),
                    n("zinc", "Zinc", "mg", 11.0),
                    n("selenium", "Selenium", "mcg", 55.0),
                    n("iodine", "Iodine", "mcg", 150.0),
                ),
            ),
        )

    private val pct =
        mapOf(
            "sodium" to 62, "potassium" to 38, "calcium" to 45, "magnesium" to 71, "phosphorus" to 88,
            "vitamin_a" to 54, "vitamin_c" to 112, "vitamin_d" to 18, "vitamin_e" to 40, "vitamin_k" to 96,
            "vitamin_b12" to 130, "folate" to 47, "iron" to 58, "zinc" to 66, "selenium" to 104, "iodine" to 22,
        )

    private val summary =
        buildMicroSummary(
            tabs,
            listOf(
                MicroDay(
                    logged = true,
                    totals = tabs.flatMap { it.nutrients }.associate { it.key to pct.getValue(it.key) * it.dailyValue / 100 },
                    foods =
                        listOf(
                            MicroFood("Green goddess dressing", mapOf("sodium" to 800.0)),
                            MicroFood("Bread, whole-wheat", mapOf("sodium" to 450.0)),
                            MicroFood("Lentils, mature seeds, cooked", mapOf("potassium" to 900.0)),
                            MicroFood("banana", mapOf("potassium" to 420.0)),
                        ),
                ),
            ),
        )!!

    private fun loaded(
        tabId: String? = null,
        selectedKey: String? = null,
        range: MicroRange = MicroRange.Today,
    ) = MicronutrientsUiState(
        range = range,
        tabId = tabId,
        selectedKey = selectedKey,
        content = MicronutrientsContent.Loaded(summary),
    )

    @Composable
    private fun render(state: MicronutrientsUiState) {
        MicronutrientsScreenContent(
            state = state,
            onBack = {},
            onSelectRange = {},
            onSelectTab = {},
            onToggleNutrient = {},
            onRetry = {},
            modifier = Modifier.fillMaxSize(),
        )
    }

    @Test
    fun electrolytes_light() = captureMealsy("Micros_electrolytes", false) { render(loaded()) }

    @Test
    fun electrolytes_dark() = captureMealsy("Micros_electrolytes", true) { render(loaded()) }

    @Test
    fun electrolytesSelected_light() = captureMealsy("Micros_electrolytes_selected", false) { render(loaded(selectedKey = "potassium")) }

    @Test
    fun electrolytesSelected_dark() = captureMealsy("Micros_electrolytes_selected", true) { render(loaded(selectedKey = "potassium")) }

    @Test
    fun vitaminsWeekLimitSelected_light() =
        captureMealsy("Micros_vitamins_week", false) { render(loaded(tabId = "vitamins", range = MicroRange.Week)) }

    @Test
    fun sodiumSelected_light() = captureMealsy("Micros_sodium_selected", false) { render(loaded(selectedKey = "sodium")) }

    @Test
    fun electrolytes_light_fontScale130() = captureMealsy("Micros_electrolytes", false, 1.3f) { render(loaded()) }

    @Test
    fun electrolytes_light_fontScale200() = captureMealsy("Micros_electrolytes", false, 2.0f) { render(loaded()) }

    @Test
    fun empty_light() = captureMealsy("Micros_empty", false) { render(MicronutrientsUiState(content = MicronutrientsContent.Empty)) }

    @Test
    fun error_dark() =
        captureMealsy("Micros_error", true) {
            render(MicronutrientsUiState(content = MicronutrientsContent.Error(ErrorKind.Offline)))
        }
}
