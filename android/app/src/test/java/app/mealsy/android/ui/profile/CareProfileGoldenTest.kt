package app.mealsy.android.ui.profile

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import app.mealsy.android.ui.AppScreenshotTestBase
import app.mealsy.data.api.HardEntryDto
import app.mealsy.data.api.LimitProgressDto
import app.mealsy.data.api.LimitsTodayDto
import kotlinx.serialization.json.JsonObject
import org.junit.Test
import java.time.LocalDate

/** Hand-built Care profile data shared by the Care profile and Profile tab goldens. */
internal object CareFixtures {
    private fun entry(
        id: String,
        type: String,
        label: String,
        state: String = "confirmed",
    ) = HardEntryDto(id = id, type = type, label = label, value = JsonObject(emptyMap()), state = state)

    private fun limit(
        id: String,
        nutrient: String,
        label: String,
        amount: Double,
        soFar: Double,
        unit: String = "mg",
    ) = LimitProgressDto(
        entryId = id,
        nutrient = nutrient,
        label = label,
        amount = amount,
        unit = unit,
        soFar = soFar,
        onTrack = soFar <= amount,
    )

    val typical =
        CareProfileData(
            entries =
                listOf(
                    entry("a1", "allergy", "Peanut allergy"),
                    entry("a2", "allergy", "Shellfish allergy"),
                    entry("a3", "allergy", "Sesame allergy", state = "pending"),
                    entry("d1", "diagnosis", "Chronic kidney disease"),
                    entry("d2", "diagnosis", "Type 2 diabetes"),
                    entry("m1", "medication", "Warfarin"),
                    entry("p1", "physical_limitation", "Trouble chewing"),
                    entry("n1", "nutrient_limit", "Sodium"),
                    entry("n2", "nutrient_limit", "Potassium"),
                    entry("n3", "nutrient_limit", "Protein"),
                    entry("f1", "food_exclusion", "Coriander"),
                ),
            limits =
                LimitsTodayDto(
                    onTrack = 2,
                    total = 3,
                    limits =
                        listOf(
                            limit("n1", "sodium", "Up to 1,500 mg a day", 1500.0, 920.0),
                            limit("n2", "potassium", "Up to 2,000 mg a day", 2000.0, 2300.0),
                            limit("n3", "protein", "50-60 g a day", 60.0, 38.0, unit = "g"),
                        ),
                ),
            updatedOn = LocalDate.of(2026, 11, 20),
        )
}

/** Goldens for the Care profile screen (empty, typical, nutrient limits expanded), light and dark. */
class CareProfileGoldenTest : AppScreenshotTestBase() {
    @Composable
    private fun render(
        state: CareProfileUiState,
        expanded: Set<CareType> = emptySet(),
    ) = CareProfileContent(
        uiState = state,
        onBack = {},
        onRetry = {},
        onAdd = {},
        onEdit = {},
        modifier = Modifier.fillMaxSize(),
        initiallyExpanded = expanded,
    )

    private val empty = CareProfileUiState.Loaded(CareProfileData(entries = emptyList()))
    private val typical = CareProfileUiState.Loaded(CareFixtures.typical)

    @Test
    fun careProfile_empty_light() = captureMealsy("CareProfile_empty", false) { render(empty) }

    @Test
    fun careProfile_empty_dark() = captureMealsy("CareProfile_empty", true) { render(empty) }

    @Test
    fun careProfile_typical_light() = captureMealsy("CareProfile_typical", false) { render(typical, setOf(CareType.Allergy)) }

    @Test
    fun careProfile_typical_dark() = captureMealsy("CareProfile_typical", true) { render(typical, setOf(CareType.Allergy)) }

    @Test
    fun careProfile_limits_light() = captureMealsy("CareProfile_limits", false) { render(typical, setOf(CareType.NutrientLimit)) }

    @Test
    fun careProfile_limits_dark() = captureMealsy("CareProfile_limits", true) { render(typical, setOf(CareType.NutrientLimit)) }
}
