package app.mealsy.android.ui.profile

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import app.mealsy.android.ui.AppScreenshotTestBase
import app.mealsy.data.api.HardEntryDto
import app.mealsy.data.api.LoggedMealDto
import app.mealsy.data.api.ProfileMealsDto
import app.mealsy.data.api.RecommendationDto
import app.mealsy.data.api.SoftFactDto
import org.junit.Test

/** Goldens for the Preferences, Meal history, Entry history and Care profile review labels, light and dark. */
class ProfileSubScreensGoldenTest : AppScreenshotTestBase() {
    private fun fact(
        id: String,
        kind: String,
        text: String,
        created: String,
    ) = SoftFactDto(id = id, kind = kind, text = text, source = "stated", createdAt = created)

    private val preferences =
        LoadState.Loaded(
            listOf(
                fact("1", "like", "Oatmeal with berries", "2026-11-02T12:00:00Z"),
                fact("2", "like", "Grilled fish", "2026-11-05T12:00:00Z"),
                fact("3", "dislike", "Coriander", "2026-11-03T12:00:00Z"),
                fact("4", "cuisine", "Mediterranean", "2026-11-04T12:00:00Z"),
                fact("5", "budget", "About 8 dollars a meal", "2026-11-06T12:00:00Z"),
                fact("6", "cooking_time", "Under 20 minutes on weekdays", "2026-11-07T12:00:00Z"),
                fact("7", "habit", "Skips breakfast", "2026-11-08T12:00:00Z"),
                fact("8", "context", "Cooks for two", "2026-11-09T12:00:00Z"),
            ),
        )

    private val meals =
        LoadState.Loaded(
            ProfileMealsDto(
                recommendations =
                    listOf(
                        RecommendationDto("r1", "Soft oat bowl", "accepted", null, "2026-11-12T12:00:00Z"),
                        RecommendationDto("r2", "Lentil soup", "rejected", "Too salty for me", "2026-11-10T12:00:00Z"),
                        RecommendationDto("r3", "Baked cod with greens", "shown", null, "2026-11-08T12:00:00Z"),
                    ),
                logged =
                    listOf(
                        LoggedMealDto("Breakfast: oatmeal, banana", "2026-11-12T12:00:00Z"),
                        LoggedMealDto("Lunch: rice, chicken, broccoli", "2026-11-11T12:00:00Z"),
                    ),
            ),
        )

    private val history =
        LoadState.Loaded(
            listOf(
                HardEntryDto("h1", "nutrient_limit", "Sodium up to 1,500 mg a day", createdAt = "2026-11-12T12:00:00Z", replacesId = "h2"),
                HardEntryDto(
                    "h2",
                    "nutrient_limit",
                    "Sodium up to 2,000 mg a day",
                    createdAt = "2026-10-01T12:00:00Z",
                    retiredAt = "2026-11-12T12:00:00Z",
                    retiredReason = "replaced",
                ),
                HardEntryDto("h3", "allergy", "Sesame allergy", state = "confirmed", createdAt = "2026-10-20T12:00:00Z"),
                HardEntryDto(
                    "h4",
                    "allergy",
                    "Soy allergy",
                    createdAt = "2026-10-05T12:00:00Z",
                    retiredAt = "2026-10-06T12:00:00Z",
                    retiredReason = "denied",
                ),
            ),
        )

    private val review =
        CareProfileUiState.Loaded(
            CareProfileData(
                entries =
                    listOf(
                        HardEntryDto("a1", "allergy", "Peanut allergy"),
                        HardEntryDto("a2", "allergy", "Sesame allergy", state = "pending"),
                        HardEntryDto("d1", "diagnosis", "Type 2 diabetes", source = "inferred"),
                        HardEntryDto("d2", "diagnosis", "High blood pressure", source = "inferred", acknowledged = true),
                    ),
            ),
        )

    @Composable
    private fun preferences() = PreferencesContent(preferences, onBack = {}, onRetry = {}, onEdit = {}, modifier = Modifier.fillMaxSize())

    @Composable
    private fun meals() = MealHistoryContent(meals, onBack = {}, onRetry = {}, modifier = Modifier.fillMaxSize())

    @Composable
    private fun history() = EntryHistoryContent(history, onBack = {}, onRetry = {}, modifier = Modifier.fillMaxSize())

    @Composable
    private fun review() =
        CareProfileContent(
            uiState = review,
            onBack = {},
            onRetry = {},
            onAdd = {},
            onEdit = {},
            modifier = Modifier.fillMaxSize(),
            initiallyExpanded = setOf(CareType.Allergy, CareType.Diagnosis),
        )

    @Test
    fun preferences_light() = captureMealsy("Preferences", false) { preferences() }

    @Test
    fun preferences_dark() = captureMealsy("Preferences", true) { preferences() }

    @Test
    fun mealHistory_light() = captureMealsy("MealHistory", false) { meals() }

    @Test
    fun mealHistory_dark() = captureMealsy("MealHistory", true) { meals() }

    @Test
    fun entryHistory_light() = captureMealsy("EntryHistory", false) { history() }

    @Test
    fun entryHistory_dark() = captureMealsy("EntryHistory", true) { history() }

    @Test
    fun careProfileReview_light() = captureMealsy("CareProfile_review", false) { review() }

    @Test
    fun careProfileReview_dark() = captureMealsy("CareProfile_review", true) { review() }
}
