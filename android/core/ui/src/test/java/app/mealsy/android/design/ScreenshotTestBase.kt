package app.mealsy.android.design

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyTheme
import com.github.takahirom.roborazzi.captureRoboImage
import org.junit.Rule
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/**
 * Shared Roborazzi screenshot harness for `:core:ui` goldens.
 *
 * Every golden test in this module should extend [ScreenshotTestBase] and
 * call [captureMealsy] rather than driving Roborazzi directly, so that all
 * goldens share the same theme wrapper, canvas background, inset padding,
 * and deterministic rendering setup.
 *
 * ### Determinism
 * - [GraphicsMode.Mode.NATIVE] is also set globally in
 *   `src/test/resources/robolectric.properties`; the `@Config`/`@GraphicsMode`
 *   annotations here are redundant belt-and-suspenders for tests that don't
 *   pick up resource files for some reason (e.g. run via other tooling).
 * - The device qualifiers pin to the design's reference width, 390dp, so
 *   goldens are stable across machines regardless of the host's default
 *   Robolectric device config.
 * - [LocalInspectionMode] is forced `true` inside the captured content.
 *   `Olli` (see `design/mascot/Olli.kt`) explicitly keys its deterministic
 *   static-frame rendering off `LocalInspectionMode`, and Robolectric does
 *   NOT set this to true by default the way `@Preview` rendering does — so
 *   without this override, Olli would attempt to load the animated WebP
 *   through Coil, which is both slow and non-deterministic under
 *   Robolectric. Forcing inspection mode is what keeps Olli goldens stable.
 *
 * [RunWith] is applied here (rather than per test class) because JUnit4's
 * `@RunWith` is `@Inherited`, so every subclass picks up
 * [RobolectricTestRunner] automatically. Without a `RobolectricTestRunner`,
 * `Build.FINGERPRINT` and friends are unshadowed nulls and
 * `createAndroidComposeRule` fails with a `NullPointerException` before any
 * content is even composed.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = "w390dp-h844dp-xhdpi")
abstract class ScreenshotTestBase {

    @get:Rule
    val composeRule = createAndroidComposeRule<androidx.activity.ComponentActivity>()

    /**
     * Renders [content] inside [MealsyTheme] on the canvas surface with a
     * standard 16dp inset, then captures it as a Roborazzi golden at
     * `src/test/screenshots/<name>_<light|dark>.png`.
     *
     * @param name The golden's base file name, e.g. `MealsyButton_primary_enabled`.
     *   The `_light`/`_dark` suffix is appended automatically from [darkTheme].
     * @param darkTheme Whether to render the dark Mealsy palette.
     * @param content The composable under test.
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
                        Box(Modifier.padding(16.dp)) {
                            content()
                        }
                    }
                }
            }
        }
        val suffix = if (darkTheme) "dark" else "light"
        composeRule.onRoot().captureRoboImage("src/test/screenshots/${name}_$suffix.png")
    }
}
