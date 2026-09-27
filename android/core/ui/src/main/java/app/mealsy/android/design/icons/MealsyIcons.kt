package app.mealsy.android.design.icons

import android.content.res.Configuration
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyTheme

/**
 * Converts a `<circle cx cy r>` primitive from the design handoff's inline
 * SVGs into an equivalent two-arc path string, since [PathParser] only
 * understands path syntax.
 */
private fun circlePath(
    cx: Float,
    cy: Float,
    r: Float,
): String = "M${cx - r} ${cy}A$r $r 0 1 0 ${cx + r} ${cy}A$r $r 0 1 0 ${cx - r} $cy Z"

/**
 * Converts a `<rect x y width height rx>` primitive from the design
 * handoff's inline SVGs into an equivalent rounded-rectangle path string.
 */
private fun roundedRectPath(
    x: Float,
    y: Float,
    w: Float,
    h: Float,
    rx: Float,
): String {
    val right = x + w
    val bottom = y + h
    return "M${x + rx} $y" +
        "H${right - rx}A$rx $rx 0 0 1 $right ${y + rx}" +
        "V${bottom - rx}A$rx $rx 0 0 1 ${right - rx} $bottom" +
        "H${x + rx}A$rx $rx 0 0 1 $x ${bottom - rx}" +
        "V${y + rx}A$rx $rx 0 0 1 ${x + rx} $y Z"
}

/**
 * Builds a 24x24 stroked line icon from one or more SVG path strings, using
 * Mealsy's line-icon spec: 2dp stroke, round caps and joins, nominal
 * [Color.Black] tint that callers override via `Icon(tint = ...)`.
 */
private fun strokedIcon(
    name: String,
    strokeWidth: Float = 2f,
    vararg pathData: String,
): ImageVector =
    ImageVector.Builder(
        name = name,
        defaultWidth = 24.dp,
        defaultHeight = 24.dp,
        viewportWidth = 24f,
        viewportHeight = 24f,
    ).apply {
        pathData.forEach { d ->
            addPath(
                pathData = PathParser().parsePathString(d).toNodes(),
                stroke = SolidColor(Color.Black),
                strokeLineWidth = strokeWidth,
                strokeLineCap = StrokeCap.Round,
                strokeLineJoin = StrokeJoin.Round,
            )
        }
    }.build()

/**
 * Builds a 24x24 filled icon (used only for [MealsyIcons.Sparkle], which the
 * handoff renders as a solid shape rather than a stroked outline).
 */
private fun filledIcon(
    name: String,
    pathData: String,
): ImageVector =
    ImageVector.Builder(
        name = name,
        defaultWidth = 24.dp,
        defaultHeight = 24.dp,
        viewportWidth = 24f,
        viewportHeight = 24f,
    ).apply {
        addPath(
            pathData = PathParser().parsePathString(pathData).toNodes(),
            fill = SolidColor(Color.Black),
        )
    }.build()

/**
 * Builds the 120x12 olive squiggle underline used under the onboarding
 * welcome headline. Unlike every other icon in this file it is not on the
 * 24-grid: its native size is 120dp x 12dp with a 3dp stroke.
 */
private fun squiggleIcon(): ImageVector =
    ImageVector.Builder(
        name = "Squiggle",
        defaultWidth = 120.dp,
        defaultHeight = 12.dp,
        viewportWidth = 120f,
        viewportHeight = 12f,
    ).apply {
        addPath(
            pathData =
                PathParser()
                    .parsePathString("M2 8c10-6 20 6 30 0s20 6 30 0 20 6 30 0 16 4 26 0")
                    .toNodes(),
            stroke = SolidColor(Color.Black),
            strokeLineWidth = 3f,
            strokeLineCap = StrokeCap.Round,
            strokeLineJoin = StrokeJoin.Round,
        )
    }.build()

/**
 * The Mealsy icon set: a 24-grid, 1.8-2dp stroked line style (round caps and
 * joins), recreated from the inline SVG `<path>`/`<circle>`/`<rect>` data in
 * `android/design-handoff/Mealsy Design System.html` and
 * `Meal Confirm Card.html`.
 *
 * Every icon is exposed as a lazily-built [ImageVector] with a nominal
 * [Color.Black] tint — callers must supply the real color via
 * `Icon(imageVector = ..., tint = ...)`. [Sparkle] is the one exception: the
 * handoff renders it filled, not stroked.
 *
 * Corrections made against the HTML while building this set (see the T4
 * report for details): the icon used for the bottom nav's "Meals" tab in the
 * design's own example markup is actually the [BowlBars] variant (bowl +
 * three bars), not the plain [Bowl] shape from the component-library
 * swatch — both are kept since the task spec calls for both names. No
 * `<svg>` for a gear/settings icon or an "X remove" icon exists anywhere in
 * the handoff bundle (the confirm card's remove control is a literal "×"
 * text glyph, not an SVG); [Gear] and [Close] were built from the task's
 * fallback specs instead of extracted paths — flag these two if a
 * pixel-authoritative gear/close ever turns up in a future handoff drop.
 *
 * Icon accessors below follow the same PascalCase-property convention as
 * `androidx.compose.material.icons.Icons` (e.g. `Icons.Filled.Home`) —
 * ktlint has no built-in exception for this (unlike `@Composable`
 * functions), so it is suppressed per-object rather than disabling the rule
 * project-wide.
 */
@Suppress("ktlint:standard:property-naming")
object MealsyIcons {
    private var _home: ImageVector? = null

    /** Bottom nav "Home" tab. */
    val Home: ImageVector
        get() =
            _home ?: strokedIcon(
                name = "Home",
                strokeWidth = 1.8f,
                pathData = arrayOf("M4 11l8-7 8 7v8a1 1 0 01-1 1h-4v-6h-6v6H5a1 1 0 01-1-1z"),
            ).also { _home = it }

    private var _bowl: ImageVector? = null

    /** Bottom nav "Meals" tab (plain bowl, component-library swatch variant). */
    val Bowl: ImageVector
        get() =
            _bowl ?: strokedIcon(
                name = "Bowl",
                strokeWidth = 1.8f,
                // Written with an explicit space between the two arc flags and
                // the endpoint coordinates ("0 0 16 0" not "0016 0") because
                // Compose's PathParser cannot reliably split a concatenated
                // flag+coordinate run when neither flag is followed by a sign
                // character - it previously mis-tokenized this arc, rendering
                // the bowl as disconnected dots instead of a closed curve.
                pathData = arrayOf("M4 12a8 8 0 0 0 16 0z"),
            ).also { _bowl = it }

    private var _bowlBars: ImageVector? = null

    /**
     * Nutrition/meal variant: bowl with three food bars. Used for list-row
     * meal-type icons and as the nav example's actual "Meals" glyph.
     */
    val BowlBars: ImageVector
        get() =
            _bowlBars ?: strokedIcon(
                name = "BowlBars",
                strokeWidth = 1.8f,
                pathData = arrayOf("M4 12a8 8 0 0 0 16 0z", "M8 12V7", "M12 12V4", "M16 12V9"),
            ).also { _bowlBars = it }

    private var _breakfast: ImageVector? = null

    /** Home "Today's meals" row icon for breakfast: a stroked sun/circle. */
    val Breakfast: ImageVector
        get() =
            _breakfast ?: strokedIcon(
                name = "Breakfast",
                pathData = arrayOf(circlePath(cx = 12f, cy = 13f, r = 6f), "M12 7V4M8 4h8"),
            ).also { _breakfast = it }

    private var _lunch: ImageVector? = null

    /** Home "Today's meals" row icon for lunch: a stroked bowl with a fork. */
    val Lunch: ImageVector
        get() =
            _lunch ?: strokedIcon(
                name = "Lunch",
                pathData = arrayOf("M4 13a8 8 0 0 0 16 0z", "M12 13V6"),
            ).also { _lunch = it }

    private var _dinner: ImageVector? = null

    /**
     * Home "Today's meals" row icon for dinner: a stroked droplet/cloche.
     * Rebuilt from the design's `S` (smooth-curve) command as an equivalent
     * explicit `C` cubic with fully space-separated arc flags, since
     * Compose's [PathParser] mis-tokenizes flag-adjacent digit runs (see the
     * [Bowl] fix above) and dropped most of this path down to a sliver when
     * transcribed with the handoff's compact syntax.
     */
    val Dinner: ImageVector
        get() =
            _dinner ?: strokedIcon(
                name = "Dinner",
                pathData =
                    arrayOf(
                        "M12 3a7 7 0 0 1 7 7c0 5 -7 11 -7 11c0 0 -7 -6 -7 -11a7 7 0 0 1 7 -7z",
                    ),
            ).also { _dinner = it }

    private var _snack: ImageVector? = null

    /** Home "Today's meals" row icon for snacks: a stroked crescent. */
    val Snack: ImageVector
        get() =
            _snack ?: strokedIcon(
                name = "Snack",
                pathData = arrayOf("M17 4a7 7 0 1 1 -9 9a8 8 0 0 0 9 -9z"),
            ).also { _snack = it }

    private var _lineChart: ImageVector? = null

    /** Bottom nav "Trends" tab. */
    val LineChart: ImageVector
        get() =
            _lineChart ?: strokedIcon(
                name = "LineChart",
                strokeWidth = 1.8f,
                pathData = arrayOf("M4 20l5-7 4 3 7-12"),
            ).also { _lineChart = it }

    private var _chat: ImageVector? = null

    /** Bottom nav "Chat" tab. */
    val Chat: ImageVector
        get() =
            _chat ?: strokedIcon(
                name = "Chat",
                strokeWidth = 1.8f,
                pathData = arrayOf("M4 7a3 3 0 013-3h10a3 3 0 013 3v6a3 3 0 01-3 3H9l-5 4z"),
            ).also { _chat = it }

    private var _plus: ImageVector? = null

    /** FAB "log a meal" glyph. */
    val Plus: ImageVector
        get() =
            _plus ?: strokedIcon(
                name = "Plus",
                strokeWidth = 2.2f,
                pathData = arrayOf("M12 5v14", "M5 12h14"),
            ).also { _plus = it }

    private var _chevronRight: ImageVector? = null

    /** List-row disclosure chevron. */
    val ChevronRight: ImageVector
        get() =
            _chevronRight ?: strokedIcon(
                name = "ChevronRight",
                pathData = arrayOf("M9 5l7 7-7 7"),
            ).also { _chevronRight = it }

    private var _chevronLeft: ImageVector? = null

    /** Circular back button. */
    val ChevronLeft: ImageVector
        get() =
            _chevronLeft ?: strokedIcon(
                name = "ChevronLeft",
                pathData = arrayOf("M15 5l-7 7 7 7"),
            ).also { _chevronLeft = it }

    private var _check: ImageVector? = null

    /** Toggles, toasts, selection cards. */
    val Check: ImageVector
        get() =
            _check ?: strokedIcon(
                name = "Check",
                strokeWidth = 2.4f,
                pathData = arrayOf("M4 12l5 5L20 7"),
            ).also { _check = it }

    private var _close: ImageVector? = null

    /**
     * "Remove" / dismiss glyph. Not present as an SVG in the handoff (the
     * confirm card uses a literal "×" text glyph) — built from the task's
     * fallback path spec.
     */
    val Close: ImageVector
        get() =
            _close ?: strokedIcon(
                name = "Close",
                pathData = arrayOf("M6 6l12 12", "M18 6L6 18"),
            ).also { _close = it }

    private var _trash: ImageVector? = null

    /** Swipe-to-delete background glyph (#48 item 2). */
    val Trash: ImageVector
        get() =
            _trash ?: strokedIcon(
                name = "Trash",
                strokeWidth = 2f,
                pathData =
                    arrayOf(
                        "M4 7h16",
                        "M9 7V4h6v3",
                        "M6 7l1 13a2 2 0 002 2h6a2 2 0 002-2l1-13",
                        "M10 11v6",
                        "M14 11v6",
                    ),
            ).also { _trash = it }

    private var _sparkle: ImageVector? = null

    /** Filled coach-note sparkle. The one filled (non-stroked) icon in the set. */
    val Sparkle: ImageVector
        get() =
            _sparkle ?: filledIcon(
                name = "Sparkle",
                pathData = "M12 2l2.4 7.6L22 12l-7.6 2.4L12 22l-2.4-7.6L2 12l7.6-2.4z",
            ).also { _sparkle = it }

    private var _mic: ImageVector? = null

    /** Chat input mic glyph. */
    val Mic: ImageVector
        get() =
            _mic ?: strokedIcon(
                name = "Mic",
                strokeWidth = 1.8f,
                pathData =
                    arrayOf(
                        roundedRectPath(x = 9f, y = 3f, w = 6f, h = 11f, rx = 3f),
                        "M5 11a7 7 0 0014 0M12 18v3",
                    ),
            ).also { _mic = it }

    private var _send: ImageVector? = null

    /** Chat input send glyph. */
    val Send: ImageVector
        get() =
            _send ?: strokedIcon(
                name = "Send",
                pathData = arrayOf("M12 19V5", "M5 12l7-7 7 7"),
            ).also { _send = it }

    private var _gear: ImageVector? = null

    /**
     * Home screen settings button. No gear/settings SVG exists anywhere in
     * the handoff bundle — this is a standard 8-spoke settings glyph built
     * to match the 24-grid stroke style, not an extracted handoff path.
     */
    val Gear: ImageVector
        get() =
            _gear ?: strokedIcon(
                name = "Gear",
                pathData =
                    arrayOf(
                        circlePath(cx = 12f, cy = 12f, r = 3f),
                        "M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41" +
                            "M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41",
                    ),
            ).also { _gear = it }

    private var _camera: ImageVector? = null

    /** Chat photo-attach glyph. */
    val Camera: ImageVector
        get() =
            _camera ?: strokedIcon(
                name = "Camera",
                pathData =
                    arrayOf(
                        circlePath(cx = 12f, cy = 13f, r = 6f),
                        "M12 7V4M8 4h8",
                    ),
            ).also { _camera = it }

    private var _squiggle: ImageVector? = null

    /**
     * Onboarding olive squiggle underline. Not a 24-grid icon: native size
     * is 120dp x 12dp with a 3dp stroke — size accordingly when placing it.
     */
    val Squiggle: ImageVector
        get() = _squiggle ?: squiggleIcon().also { _squiggle = it }

    /** All icons paired with their names, for the icon-grid preview. */
    internal val all: List<Pair<String, ImageVector>>
        get() =
            listOf(
                "Home" to Home,
                "Bowl" to Bowl,
                "BowlBars" to BowlBars,
                "Breakfast" to Breakfast,
                "Lunch" to Lunch,
                "Dinner" to Dinner,
                "Snack" to Snack,
                "LineChart" to LineChart,
                "Chat" to Chat,
                "Plus" to Plus,
                "ChevronRight" to ChevronRight,
                "ChevronLeft" to ChevronLeft,
                "Check" to Check,
                "Close" to Close,
                "Sparkle" to Sparkle,
                "Mic" to Mic,
                "Send" to Send,
                "Gear" to Gear,
                "Camera" to Camera,
            )
}

/** Renders every [MealsyIcons] entry at 24dp with its name, for visual review. */
@Composable
private fun MealsyIconsGrid() {
    Surface(color = MealsyTheme.colors.canvas) {
        LazyVerticalGrid(
            columns = GridCells.Fixed(4),
            horizontalArrangement = Arrangement.spacedBy(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
            modifier =
                Modifier
                    .fillMaxWidth()
                    .padding(16.dp),
        ) {
            items(MealsyIcons.all) { (name, icon) ->
                androidx.compose.foundation.layout.Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Icon(
                        imageVector = icon,
                        contentDescription = name,
                        tint = MealsyTheme.colors.ink,
                        modifier = Modifier.padding(4.dp),
                    )
                    Text(text = name, style = MaterialThemeLabel(), color = MealsyTheme.colors.muted)
                }
            }
        }
    }
}

/** Small helper so the preview grid doesn't need a MealsyType import cycle. */
@Composable
private fun MaterialThemeLabel() = androidx.compose.material3.MaterialTheme.typography.labelSmall

@Preview(name = "Icon grid light", widthDp = 390)
@Composable
private fun MealsyIconsGridPreviewLight() {
    MealsyTheme(darkTheme = false) { MealsyIconsGrid() }
}

@Preview(name = "Icon grid dark", widthDp = 390, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun MealsyIconsGridPreviewDark() {
    MealsyTheme(darkTheme = true) { MealsyIconsGrid() }
}
