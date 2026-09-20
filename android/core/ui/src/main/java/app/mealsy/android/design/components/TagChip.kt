package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * The four pastel tones used across tiny tags and icon circles.
 *
 * Per `android/CLAUDE.md`, pastels are allowed ONLY in tiny tags
 * ([TagChip], [MetaTag]) and 32-36dp icon circles ([PastelIconCircle]) —
 * never as fills, backgrounds, or button colors elsewhere.
 */
enum class TagTone {
    Butter,
    Pink,
    Leaf,
    Powder,
}

internal data class ToneColors(val fill: Color, val text: Color)

@Composable
internal fun TagTone.resolve(): ToneColors {
    val colors = MealsyTheme.colors
    return when (this) {
        TagTone.Butter -> ToneColors(colors.butter, colors.butterText)
        TagTone.Pink -> ToneColors(colors.pink, colors.pinkText)
        TagTone.Leaf -> ToneColors(colors.leaf, colors.leafText)
        TagTone.Powder -> ToneColors(colors.powder, colors.powderText)
    }
}

/**
 * A tiny pastel metadata tag, used for meal tags like `412 kcal` or
 * `estimated` on food rows in the meal confirm card and meal detail.
 *
 * Reminder: pastels are allowed ONLY in tiny tags and 32-36dp icon circles —
 * see `android/CLAUDE.md`. Do not reuse these colors as a fill elsewhere.
 *
 * @param text The tag's label.
 * @param tone Which pastel tone to render.
 * @param modifier The modifier applied to the tag's pill container.
 */
@Composable
fun TagChip(
    text: String,
    tone: TagTone,
    modifier: Modifier = Modifier,
) {
    val resolved = tone.resolve()
    Surface(
        modifier = modifier,
        shape = MealsyShapes.pill,
        color = resolved.fill,
    ) {
        Text(
            text = text,
            style = MealsyType.tinyTag,
            color = resolved.text,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(vertical = 2.dp, horizontal = 8.dp),
        )
    }
}

/**
 * The larger pastel tag variant used on the meal detail screen (e.g.
 * `412 kcal`, `28g protein`, `USDA verified`).
 *
 * Reminder: pastels are allowed ONLY in tiny tags and 32-36dp icon circles —
 * see `android/CLAUDE.md`.
 *
 * @param text The tag's label.
 * @param tone Which pastel tone to render.
 * @param modifier The modifier applied to the tag's pill container.
 */
@Composable
fun MetaTag(
    text: String,
    tone: TagTone,
    modifier: Modifier = Modifier,
) {
    val resolved = tone.resolve()
    Surface(
        modifier = modifier,
        shape = MealsyShapes.pill,
        color = resolved.fill,
    ) {
        Text(
            text = text,
            style = MealsyType.badge,
            color = resolved.text,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(vertical = 4.dp, horizontal = 11.dp),
        )
    }
}

@Preview(name = "TagChip light", widthDp = 390)
@Composable
private fun TagChipLightPreview() {
    MealsyTheme {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Row(
                modifier = Modifier.padding(20.dp),
                horizontalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(6.dp),
            ) {
                TagChip(text = "estimated", tone = TagTone.Powder)
                MetaTag(text = "412 kcal", tone = TagTone.Butter)
                MetaTag(text = "28g protein", tone = TagTone.Leaf)
            }
        }
    }
}

@Preview(
    name = "TagChip dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun TagChipDarkPreview() {
    MealsyTheme(darkTheme = true) {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Row(
                modifier = Modifier.padding(20.dp),
                horizontalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(6.dp),
            ) {
                TagChip(text = "estimated", tone = TagTone.Powder)
                MetaTag(text = "USDA verified", tone = TagTone.Powder)
            }
        }
    }
}
