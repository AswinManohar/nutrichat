package app.mealsy.android.ui.journey

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import app.mealsy.android.ui.AppScreenshotTestBase
import app.mealsy.android.ui.common.ErrorKind
import app.mealsy.data.repo.DayPoint
import app.mealsy.domain.MicroDay
import app.mealsy.domain.MicroNutrient
import app.mealsy.domain.MicroTab
import app.mealsy.domain.buildMicroSummary
import org.junit.Test
import org.robolectric.annotation.Config
import java.time.LocalDate

/**
 * Goldens for Journey. The micronutrient list uses the design mock's 7-day
 * values (Vitamin C 96%, Vitamin D 34%, Iron 78%, Magnesium 61%, Potassium
 * 52%) with sodium over its limit (104%) to show the terracotta fill.
 */
class JourneyGoldenTest : AppScreenshotTestBase() {
    private val today = LocalDate.of(2026, 11, 10)

    private fun day(
        daysAgo: Long,
        p: Double,
        c: Double,
        f: Double,
    ) = DayPoint(
        date = today.minusDays(daysAgo).toString(),
        kcal = p * 4 + c * 4 + f * 9,
        proteinG = p,
        carbsG = c,
        fatG = f,
        fiberG = 20.0,
        nMeals = 3,
        junkMeals = 0,
    )

    /** Five of the last seven days logged, then older days for the 30/90-day views. */
    private val days =
        listOf(
            day(0, 86.0, 152.0, 48.0),
            day(1, 104.0, 230.0, 62.0),
            day(2, 121.0, 205.0, 70.0),
            day(4, 96.0, 260.0, 66.0),
            day(5, 72.0, 198.0, 58.0),
            day(12, 110.0, 214.0, 64.0),
            day(19, 95.0, 240.0, 72.0),
            day(26, 88.0, 190.0, 55.0),
            day(45, 100.0, 220.0, 60.0),
            day(70, 92.0, 230.0, 75.0),
        ).sortedBy { it.date }

    private fun n(
        key: String,
        name: String,
        dv: Double,
        limit: Boolean = false,
    ) = MicroNutrient(key, name, "mg", limit, dv)

    private val nutrients =
        listOf(
            n("vitamin_c", "Vitamin C", 90.0),
            n("vitamin_d", "Vitamin D", 20.0),
            n("iron", "Iron", 18.0),
            n("magnesium", "Magnesium", 420.0),
            n("potassium", "Potassium", 4700.0),
            n("sodium", "Sodium", 2300.0, limit = true),
        )
    private val pct = mapOf("vitamin_c" to 96, "vitamin_d" to 34, "iron" to 78, "magnesium" to 61, "potassium" to 52, "sodium" to 104)

    private val micros =
        buildMicroSummary(
            tabs = listOf(MicroTab("all", "All", nutrients)),
            days = listOf(MicroDay(true, nutrients.associate { it.key to pct.getValue(it.key) * it.dailyValue / 100 }, emptyList())),
            highlightKeys = nutrients.map { it.key },
        )!!

    private fun loaded(
        range: JourneyRange = JourneyRange.Week,
        micros: JourneyMicros = JourneyMicros.Loaded(this.micros),
        logged: List<DayPoint> = days,
    ) = JourneyUiState(
        range = range,
        content =
            JourneyContent.Loaded(
                days = logged.filter { !LocalDate.parse(it.date).isBefore(today.minusDays(range.days - 1L)) },
                today = today,
                kcalGoal = 2000.0,
                proteinGoal = 110.0,
                micros = micros,
            ),
    )

    @Composable
    private fun render(state: JourneyUiState) {
        JourneyScreenContent(
            state = state,
            onSelectRange = {},
            onRetry = {},
            onOpenMicronutrients = {},
            modifier = Modifier.fillMaxSize(),
        )
    }

    @Test
    fun week_light() = captureMealsy("Journey_week", false) { render(loaded()) }

    /** The whole page in one frame, so the micronutrient list and coach note below the fold are covered. */
    @Test
    @Config(qualifiers = "w390dp-h1640dp-xhdpi")
    fun weekFullPage_light() = captureMealsy("Journey_week_full", false) { render(loaded()) }

    @Test
    fun week_dark() = captureMealsy("Journey_week", true) { render(loaded()) }

    @Test
    fun month_light() = captureMealsy("Journey_month", false) { render(loaded(JourneyRange.Month)) }

    @Test
    fun quarter_dark() = captureMealsy("Journey_quarter", true) { render(loaded(JourneyRange.Quarter)) }

    @Test
    fun week_light_fontScale200() = captureMealsy("Journey_week", false, 2.0f) { render(loaded()) }

    @Test
    fun microsUnavailable_light() =
        captureMealsy("Journey_micros_unavailable", false) { render(loaded(micros = JourneyMicros.Unavailable)) }

    @Test
    fun nothingLogged_light() = captureMealsy("Journey_empty", false) { render(loaded(micros = JourneyMicros.Empty, logged = emptyList())) }

    @Test
    fun loading_light() = captureMealsy("Journey_loading", false) { render(JourneyUiState()) }

    @Test
    fun error_dark() = captureMealsy("Journey_error", true) { render(JourneyUiState(content = JourneyContent.Error(ErrorKind.LoadFailed))) }
}
