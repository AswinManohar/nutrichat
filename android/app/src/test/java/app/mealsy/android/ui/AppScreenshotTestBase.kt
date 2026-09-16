package app.mealsy.android.ui

import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.test.isDialog
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onRoot
import app.mealsy.android.design.theme.MealsyTheme
import com.github.takahirom.roborazzi.captureRoboImage
import org.junit.Rule
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/**
 * Shared Roborazzi screenshot harness for `:app` screen-level goldens.
 *
 * Mirrors `core/ui/src/test/java/app/mealsy/android/design/ScreenshotTestBase.kt`,
 * but captures the full screen with no inset box, since these goldens are
 * whole screens (e.g. onboarding), not isolated components.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = "w390dp-h844dp-xhdpi")
abstract class AppScreenshotTestBase {

    // See TestHostActivity's kdoc for why a plain ComponentActivity can't be
    // used directly here.
    @get:Rule
    val composeRule = createAndroidComposeRule<TestHostActivity>()

    /**
     * Renders [content] inside [MealsyTheme] on the canvas surface, full
     * screen, then captures it as a Roborazzi golden at
     * `src/test/screenshots/<name>_<light|dark>.png`.
     *
     * [LocalInspectionMode] is forced `true` so [app.mealsy.android.design.mascot.Olli]
     * renders its deterministic static frame instead of loading the animated
     * WebP through Coil.
     */
    protected fun captureMealsy(
        name: String,
        darkTheme: Boolean,
        content: @Composable () -> Unit,
    ) {
        composeRule.setContent {
            CompositionLocalProvider(LocalInspectionMode provides true) {
                MealsyTheme(darkTheme = darkTheme) {
                    Surface(color = MealsyTheme.colors.canvas) {
                        content()
                    }
                }
            }
        }
        val suffix = if (darkTheme) "dark" else "light"
        composeRule.onRoot().captureRoboImage("src/test/screenshots/${name}_$suffix.png")
    }

    /**
     * Like [captureMealsy], but for content that renders into a `Popup`/`Dialog`
     * compose root (e.g. `ModalBottomSheet`) — [androidx.compose.ui.test.isDialog]
     * finds that separate root instead of the main screen root, which would
     * otherwise capture an empty frame.
     */
    protected fun captureMealsyDialog(
        name: String,
        darkTheme: Boolean,
        content: @Composable () -> Unit,
    ) {
        composeRule.setContent {
            CompositionLocalProvider(LocalInspectionMode provides true) {
                MealsyTheme(darkTheme = darkTheme) {
                    Surface(color = MealsyTheme.colors.canvas) {
                        content()
                    }
                }
            }
        }
        val suffix = if (darkTheme) "dark" else "light"
        composeRule.onNode(isDialog()).captureRoboImage("src/test/screenshots/${name}_$suffix.png")
    }
}
