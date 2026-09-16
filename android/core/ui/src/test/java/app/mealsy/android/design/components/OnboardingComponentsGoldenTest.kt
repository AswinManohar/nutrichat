package app.mealsy.android.design.components

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.ScreenshotTestBase
import org.junit.Test

/**
 * Goldens for the T1 onboarding `design/components/` composables, light and
 * dark. `animate` flags are pinned false throughout for determinism.
 */
class OnboardingComponentsGoldenTest : ScreenshotTestBase() {

    // --- MealsySlider: min / mid / max --------------------------------------

    @Test
    fun mealsySlider_min_light() = captureMealsy("MealsySlider_min", false) {
        MealsySlider(value = 1400, onValueChange = {}, modifier = Modifier.fillMaxWidth())
    }

    @Test
    fun mealsySlider_min_dark() = captureMealsy("MealsySlider_min", true) {
        MealsySlider(value = 1400, onValueChange = {}, modifier = Modifier.fillMaxWidth())
    }

    @Test
    fun mealsySlider_mid_light() = captureMealsy("MealsySlider_mid", false) {
        MealsySlider(value = 2000, onValueChange = {}, modifier = Modifier.fillMaxWidth())
    }

    @Test
    fun mealsySlider_mid_dark() = captureMealsy("MealsySlider_mid", true) {
        MealsySlider(value = 2000, onValueChange = {}, modifier = Modifier.fillMaxWidth())
    }

    @Test
    fun mealsySlider_max_light() = captureMealsy("MealsySlider_max", false) {
        MealsySlider(value = 3200, onValueChange = {}, modifier = Modifier.fillMaxWidth())
    }

    @Test
    fun mealsySlider_max_dark() = captureMealsy("MealsySlider_max", true) {
        MealsySlider(value = 3200, onValueChange = {}, modifier = Modifier.fillMaxWidth())
    }

    // --- MealsyProgressBar: 0.25 / 0.5 / 1.0 --------------------------------

    @Test
    fun mealsyProgressBar_quarter_light() = captureMealsy("MealsyProgressBar_quarter", false) {
        MealsyProgressBar(progress = 0.25f, animate = false, modifier = Modifier.fillMaxWidth())
    }

    @Test
    fun mealsyProgressBar_quarter_dark() = captureMealsy("MealsyProgressBar_quarter", true) {
        MealsyProgressBar(progress = 0.25f, animate = false, modifier = Modifier.fillMaxWidth())
    }

    @Test
    fun mealsyProgressBar_half_light() = captureMealsy("MealsyProgressBar_half", false) {
        MealsyProgressBar(progress = 0.5f, animate = false, modifier = Modifier.fillMaxWidth())
    }

    @Test
    fun mealsyProgressBar_half_dark() = captureMealsy("MealsyProgressBar_half", true) {
        MealsyProgressBar(progress = 0.5f, animate = false, modifier = Modifier.fillMaxWidth())
    }

    @Test
    fun mealsyProgressBar_full_light() = captureMealsy("MealsyProgressBar_full", false) {
        MealsyProgressBar(progress = 1.0f, animate = false, modifier = Modifier.fillMaxWidth())
    }

    @Test
    fun mealsyProgressBar_full_dark() = captureMealsy("MealsyProgressBar_full", true) {
        MealsyProgressBar(progress = 1.0f, animate = false, modifier = Modifier.fillMaxWidth())
    }

    // --- SpeechBubble --------------------------------------------------------

    @Test
    fun speechBubble_light() = captureMealsy("SpeechBubble", false) {
        SpeechBubble(text = "HI, I'M OLLI")
    }

    @Test
    fun speechBubble_dark() = captureMealsy("SpeechBubble", true) {
        SpeechBubble(text = "HI, I'M OLLI")
    }

    // --- OliveSquiggle ---------------------------------------------------------

    @Test
    fun oliveSquiggle_light() = captureMealsy("OliveSquiggle", false) {
        OliveSquiggle()
    }

    @Test
    fun oliveSquiggle_dark() = captureMealsy("OliveSquiggle", true) {
        OliveSquiggle()
    }

    // --- DecorativeDots --------------------------------------------------------

    @Test
    fun decorativeDots_light() = captureMealsy("DecorativeDots", false) {
        Box(modifier = Modifier.size(390.dp, 400.dp)) {
            DecorativeDots()
        }
    }

    @Test
    fun decorativeDots_dark() = captureMealsy("DecorativeDots", true) {
        Box(modifier = Modifier.size(390.dp, 400.dp)) {
            DecorativeDots()
        }
    }

    // --- OutlinePill -------------------------------------------------------

    @Test
    fun outlinePill_light() = captureMealsy("OutlinePill", false) {
        OutlinePill(text = "IT'S EASIER TOGETHER")
    }

    @Test
    fun outlinePill_dark() = captureMealsy("OutlinePill", true) {
        OutlinePill(text = "IT'S EASIER TOGETHER")
    }
}
