package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * One column of a [TotalsStrip]: a macro label (e.g. `Protein`) and its
 * computed value (e.g. `28g`).
 *
 * @param label The column's uppercase label.
 * @param value The column's tabular-numeral value.
 * @param isZero Whether this macro totals zero; zero columns render at
 *   reduced opacity per the confirm-card spec rather than being hidden, so
 *   the grid stays visually balanced.
 */
data class TotalsStripEntry(val label: String, val value: String, val isZero: Boolean)

/**
 * The meal confirm card's totals strip (`Meal Confirm Card.html`, "Totals"
 * block): an `oliveTrack`-filled bar of N equal-weight columns, one per
 * macro, recomputed live as the user edits food-row grams and portion.
 *
 * The whole strip is exposed to TalkBack as a single merged announcement
 * (e.g. "412 kcal, 28 g protein, ...") via [clearAndSetSemantics], rather
 * than letting each column announce separately, since the columns are one
 * logical fact (today's/this-meal's totals) and reading them one at a time
 * is worse UX than one combined read.
 *
 * @param entries The macro columns to render, in display order (the design
 *   uses kcal, Protein, Carbs, Fat, Fiber).
 * @param modifier The modifier applied to the strip's container.
 */
@Composable
fun TotalsStrip(
    entries: List<TotalsStripEntry>,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    val mergedDescription = entries.joinToString(", ") { "${it.value} ${it.label}" }

    val density = LocalDensity.current
    // Columns per row. Starts at one row of every macro; whenever a label or
    // value overflows its column (large font scale), drop a column per row so
    // the strip wraps onto a second/third row instead of breaking words (#53).
    var perRow by remember(density.fontScale, entries.size) { mutableIntStateOf(entries.size.coerceAtLeast(1)) }
    val onOverflow: () -> Unit = {
        if (perRow > MIN_COLUMNS) {
            // First step balances the rows (5 -> 3+2) instead of orphaning one macro.
            perRow = if (perRow == entries.size) maxOf(MIN_COLUMNS, (entries.size + 1) / 2) else perRow - 1
        }
    }

    Surface(
        modifier = modifier.clearAndSetSemantics { contentDescription = mergedDescription },
        shape = MealsyShapes.strip,
        color = colors.oliveTrack,
    ) {
        Column(
            modifier = Modifier.padding(vertical = 14.dp, horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            entries.chunked(perRow).forEach { rowEntries ->
                Row(horizontalArrangement = Arrangement.SpaceBetween) {
                    rowEntries.forEach { entry ->
                        TotalsColumn(entry = entry, onOverflow = onOverflow, modifier = Modifier.weight(1f))
                    }
                    repeat(perRow - rowEntries.size) { Spacer(modifier = Modifier.weight(1f)) }
                }
            }
        }
    }
}

private const val MIN_COLUMNS = 2

@Composable
private fun TotalsColumn(
    entry: TotalsStripEntry,
    onOverflow: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    Column(
        modifier = modifier.alpha(if (entry.isZero) 0.45f else 1f),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(
            text = entry.label.uppercase(),
            // tinyTag's 0.04em tracking is too tight for this label;
            // the spec calls for 0.1em here, so override it.
            style = MealsyType.tinyTag.copy(letterSpacing = 0.1.em),
            color = colors.oliveTrackLabel,
            textAlign = TextAlign.Center,
            maxLines = 1,
            softWrap = false,
            onTextLayout = { if (it.hasVisualOverflow) onOverflow() },
        )
        Text(
            // MealsyType.bigNumber is already 19sp with tabular
            // figures; only the weight needs bumping to 700 here.
            text = entry.value,
            style = MealsyType.bigNumber.copy(fontWeight = FontWeight.Bold),
            color = colors.oliveTrackValue,
            textAlign = TextAlign.Center,
            maxLines = 1,
            softWrap = false,
            onTextLayout = { if (it.hasVisualOverflow) onOverflow() },
        )
    }
}

@Preview(name = "TotalsStrip light", widthDp = 390)
@Composable
private fun TotalsStripLightPreview() {
    MealsyTheme {
        Surface(color = MealsyTheme.colors.canvas) {
            TotalsStrip(
                entries =
                    listOf(
                        TotalsStripEntry("kcal", "412", isZero = false),
                        TotalsStripEntry("Protein", "28g", isZero = false),
                        TotalsStripEntry("Carbs", "12g", isZero = false),
                        TotalsStripEntry("Fat", "31g", isZero = false),
                        TotalsStripEntry("Fiber", "0g", isZero = true),
                    ),
                modifier = Modifier.padding(20.dp),
            )
        }
    }
}

@Preview(
    name = "TotalsStrip dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun TotalsStripDarkPreview() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            TotalsStrip(
                entries =
                    listOf(
                        TotalsStripEntry("kcal", "412", isZero = false),
                        TotalsStripEntry("Protein", "28g", isZero = false),
                        TotalsStripEntry("Carbs", "0g", isZero = true),
                        TotalsStripEntry("Fat", "0g", isZero = true),
                        TotalsStripEntry("Fiber", "0g", isZero = true),
                    ),
                modifier = Modifier.padding(20.dp),
            )
        }
    }
}
