package app.mealsy.android.design.theme

import android.content.res.Configuration.UI_MODE_NIGHT_YES
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp

/**
 * A single color swatch entry paired with its token name and hex string, for
 * [MealsyTokenSheet].
 */
private data class Swatch(val name: String, val color: androidx.compose.ui.graphics.Color)

/** Builds the ordered swatch list for the current [MealsyColors]. */
private fun swatchesFor(c: MealsyColors): List<Swatch> = listOf(
    Swatch("canvas", c.canvas),
    Swatch("surface", c.surface),
    Swatch("surfacePressed", c.surfacePressed),
    Swatch("divider", c.divider),
    Swatch("hairline", c.hairline),
    Swatch("ink", c.ink),
    Swatch("inkPressed", c.inkPressed),
    Swatch("muted", c.muted),
    Swatch("inactive", c.inactive),
    Swatch("olive", c.olive),
    Swatch("oliveText", c.oliveText),
    Swatch("oliveTrack", c.oliveTrack),
    Swatch("olivePressed", c.olivePressed),
    Swatch("userBubble", c.userBubble),
    Swatch("userBubbleText", c.userBubbleText),
    Swatch("butter", c.butter),
    Swatch("butterText", c.butterText),
    Swatch("pink", c.pink),
    Swatch("pinkText", c.pinkText),
    Swatch("leaf", c.leaf),
    Swatch("leafText", c.leafText),
    Swatch("powder", c.powder),
    Swatch("powderText", c.powderText),
    Swatch("terracotta", c.terracotta),
    Swatch("terracottaText", c.terracottaText),
    Swatch("terracottaOutlineText", c.terracottaOutlineText),
    Swatch("navBar", c.navBar),
    Swatch("navActive", c.navActive),
    Swatch("navInactive", c.navInactive),
    Swatch("navBorder", c.navBorder),
    Swatch("fab", c.fab),
    Swatch("fabIcon", c.fabIcon),
    Swatch("fabShadow", c.fabShadow),
)

/** Formats a color as an `#AARRGGBB` hex string for the swatch label. */
private fun androidx.compose.ui.graphics.Color.toHexLabel(): String {
    val argb = (this.value shr 32).toInt()
    return "#%08X".format(argb)
}

/**
 * Renders every [MealsyColors] token as a labeled swatch, plus a type
 * specimen for every [MealsyType] role (including digits, to show off
 * tabular figures). Used by both light/dark previews below and by
 * screenshot tests that need a single entry point to capture the whole
 * token sheet.
 */
@Composable
fun MealsyTokenSheet() {
    val colors = MealsyTheme.colors
    Column(
        modifier = Modifier
            .background(colors.canvas)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("Color tokens", style = MealsyType.section, color = colors.ink)
        LazyColumn(
            modifier = Modifier.size(width = 320.dp, height = 400.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            items(swatchesFor(colors)) { swatch ->
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Box(swatch.color)
                    Text(
                        text = "${swatch.name}  ${swatch.color.toHexLabel()}",
                        style = MealsyType.label,
                        color = colors.ink,
                    )
                }
            }
        }

        Text("Type specimen", style = MealsyType.section, color = colors.ink)
        val sample = "Sample text 0123456789"
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(
                "hero" to MealsyType.hero,
                "display" to MealsyType.display,
                "screenTitle" to MealsyType.screenTitle,
                "section" to MealsyType.section,
                "body" to MealsyType.body,
                "label" to MealsyType.label,
                "eyebrow" to MealsyType.eyebrow,
                "button" to MealsyType.button,
                "badge" to MealsyType.badge,
                "tinyTag" to MealsyType.tinyTag,
                "bigNumber" to MealsyType.bigNumber,
                "bigNumberLarge" to MealsyType.bigNumberLarge,
            ).forEach { (name, style) ->
                Text(text = "$name: $sample", style = style, color = colors.ink)
            }
        }
    }
}

/** A small filled square used as a color swatch in [MealsyTokenSheet]. */
@Composable
private fun Box(color: androidx.compose.ui.graphics.Color) {
    androidx.compose.foundation.layout.Box(
        modifier = Modifier
            .size(24.dp)
            .background(color, RoundedCornerShape(4.dp)),
    )
}

/** Light-mode token sheet preview. */
@Preview(name = "Tokens light")
@Composable
private fun TokensLightPreview() {
    MealsyTheme(darkTheme = false) {
        MealsyTokenSheet()
    }
}

/** Dark-mode token sheet preview. */
@Preview(name = "Tokens dark", uiMode = UI_MODE_NIGHT_YES)
@Composable
private fun TokensDarkPreview() {
    MealsyTheme(darkTheme = true) {
        MealsyTokenSheet()
    }
}
