package app.mealsy.android.ui.chat

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.unit.dp

/**
 * The chat bar's mic and camera glyphs. `MealsyIcons.Mic`/`Camera` are not used
 * here: the shared mic path packs SVG arc flags ("0014") which Compose's
 * `PathParser` misreads, and the shared camera is a bare ring. These follow the
 * "Mealsy Chat Bar" design (1.8 stroke, round caps, 24 grid) with explicit
 * arc flags.
 */
internal object ChatBarIcons {
    private fun icon(
        name: String,
        vararg paths: String,
    ): ImageVector =
        ImageVector
            .Builder(name, 24.dp, 24.dp, 24f, 24f)
            .apply {
                paths.forEach { d ->
                    addPath(
                        pathData = PathParser().parsePathString(d).toNodes(),
                        stroke = SolidColor(Color.Black),
                        strokeLineWidth = 1.8f,
                        strokeLineCap = StrokeCap.Round,
                        strokeLineJoin = StrokeJoin.Round,
                    )
                }
            }.build()

    val Mic: ImageVector by lazy {
        icon(
            "Mic",
            "M12 3 a3 3 0 0 0 -3 3 v5 a3 3 0 0 0 6 0 V6 a3 3 0 0 0 -3 -3 z",
            "M5 11 a7 7 0 0 0 14 0",
            "M12 18 v3",
        )
    }

    val Camera: ImageVector by lazy {
        icon(
            "Camera",
            "M4 8 h3 l1.5 -2 h7 l1.5 2 h3 v11 H4 z",
            "M12 9.5 a3.5 3.5 0 1 0 0 7 a3.5 3.5 0 1 0 0 -7 z",
        )
    }
}
