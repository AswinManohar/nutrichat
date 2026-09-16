package app.mealsy.android.ui

import android.os.Bundle
import androidx.activity.ComponentActivity

/**
 * Test-only host activity for [AppScreenshotTestBase].
 *
 * `:app`'s manifest applies `Theme.Mealsy` to any unlisted activity
 * (including the plain `ComponentActivity` Compose's own test rule would
 * otherwise use), which requests an action bar. On `onCreate`, the action
 * bar tries to load the real adaptive launcher icon
 * (`@mipmap/ic_launcher`) as its icon — Robolectric's NATIVE graphics mode
 * cannot decode that `<adaptive-icon>` (it has a `<monochrome>` child) and
 * every screenshot test crashes with `Resources$NotFoundException` before
 * any Compose content is rendered.
 *
 * Setting a plain `NoActionBar` theme before `super.onCreate` avoids the
 * action bar (and its icon lookup) entirely, without touching the real
 * manifest or launcher assets used by the shipped app.
 */
class TestHostActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        setTheme(android.R.style.Theme_Material_Light_NoActionBar)
        super.onCreate(savedInstanceState)
    }
}
