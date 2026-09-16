package app.mealsy.android.design.icons

import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.ScreenshotTestBase
import app.mealsy.android.design.theme.MealsyTheme
import org.junit.Test

/** One grid golden covering every [MealsyIcons] vector, light and dark. */
class MealsyIconsGoldenTest : ScreenshotTestBase() {

    private val allIcons: List<Pair<String, androidx.compose.ui.graphics.vector.ImageVector>> = listOf(
        "Home" to MealsyIcons.Home,
        "Bowl" to MealsyIcons.Bowl,
        "BowlBars" to MealsyIcons.BowlBars,
        "LineChart" to MealsyIcons.LineChart,
        "Chat" to MealsyIcons.Chat,
        "Plus" to MealsyIcons.Plus,
        "ChevronRight" to MealsyIcons.ChevronRight,
        "ChevronLeft" to MealsyIcons.ChevronLeft,
        "Check" to MealsyIcons.Check,
        "Close" to MealsyIcons.Close,
        "Sparkle" to MealsyIcons.Sparkle,
        "Mic" to MealsyIcons.Mic,
        "Send" to MealsyIcons.Send,
        "Gear" to MealsyIcons.Gear,
        "Camera" to MealsyIcons.Camera,
        "Squiggle" to MealsyIcons.Squiggle,
    )

    @Composable
    private fun Grid() {
        LazyVerticalGrid(columns = GridCells.Fixed(4), modifier = Modifier.padding(4.dp)) {
            items(allIcons) { (_, icon) ->
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = MealsyTheme.colors.ink,
                    modifier = Modifier.padding(8.dp),
                )
            }
        }
    }

    @Test
    fun iconGrid_light() {
        captureMealsy("MealsyIcons_grid", darkTheme = false) { Grid() }
    }

    @Test
    fun iconGrid_dark() {
        captureMealsy("MealsyIcons_grid", darkTheme = true) { Grid() }
    }
}
