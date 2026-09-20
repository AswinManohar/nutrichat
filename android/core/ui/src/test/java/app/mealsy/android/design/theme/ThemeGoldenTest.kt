package app.mealsy.android.design.theme

import app.mealsy.android.design.ScreenshotTestBase
import org.junit.Test

/** Goldens for the whole token + type specimen sheet, light and dark. */
class ThemeGoldenTest : ScreenshotTestBase() {
    @Test
    fun tokenSheet_light() {
        captureMealsy("MealsyTokenSheet", darkTheme = false) {
            MealsyTokenSheet()
        }
    }

    @Test
    fun tokenSheet_dark() {
        captureMealsy("MealsyTokenSheet", darkTheme = true) {
            MealsyTokenSheet()
        }
    }
}
