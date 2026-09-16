package app.mealsy.android.design.mascot

import app.mealsy.android.design.ScreenshotTestBase
import org.junit.Test

/**
 * Goldens for [Olli] at all four [OlliSize] values.
 *
 * [ScreenshotTestBase.captureMealsy] forces `LocalInspectionMode` to `true`,
 * which is what makes Olli render its deterministic static frame
 * ([app.mealsy.android.design.R.drawable.olli_static]) instead of loading
 * the animated WebP through Coil. `bob = false` additionally pins the idle
 * bob animation off, though inspection mode alone already disables it per
 * `Olli.kt`'s own doc comment.
 */
class OlliGoldenTest : ScreenshotTestBase() {

    @Test
    fun olli_header_light() {
        captureMealsy("Olli_header", darkTheme = false) {
            Olli(size = OlliSize.Header, bob = false)
        }
    }

    @Test
    fun olli_header_dark() {
        captureMealsy("Olli_header", darkTheme = true) {
            Olli(size = OlliSize.Header, bob = false)
        }
    }

    @Test
    fun olli_bite_light() {
        captureMealsy("Olli_bite", darkTheme = false) {
            Olli(size = OlliSize.Bite, bob = false)
        }
    }

    @Test
    fun olli_bite_dark() {
        captureMealsy("Olli_bite", darkTheme = true) {
            Olli(size = OlliSize.Bite, bob = false)
        }
    }

    @Test
    fun olli_done_light() {
        captureMealsy("Olli_done", darkTheme = false) {
            Olli(size = OlliSize.Done, bob = false)
        }
    }

    @Test
    fun olli_done_dark() {
        captureMealsy("Olli_done", darkTheme = true) {
            Olli(size = OlliSize.Done, bob = false)
        }
    }

    @Test
    fun olli_welcome_light() {
        captureMealsy("Olli_welcome", darkTheme = false) {
            Olli(size = OlliSize.Welcome, bob = false)
        }
    }

    @Test
    fun olli_welcome_dark() {
        captureMealsy("Olli_welcome", darkTheme = true) {
            Olli(size = OlliSize.Welcome, bob = false)
        }
    }
}
