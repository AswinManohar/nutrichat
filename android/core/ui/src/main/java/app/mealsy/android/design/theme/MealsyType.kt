package app.mealsy.android.design.theme

import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import app.mealsy.android.design.R

/**
 * Builds a single weight instance of the bundled Geist variable font.
 *
 * The variable font's `wght` axis (100-900) is driven directly via
 * [FontVariation.weight] rather than shipping a separate static file per
 * weight. [FontVariation] is an experimental Compose text API as of this
 * BOM; opted into here since it is the officially recommended way to drive
 * a variable font axis.
 */
@OptIn(ExperimentalTextApi::class)
private fun geist(weight: FontWeight) =
    Font(
        R.font.geist_variable,
        weight = weight,
        variationSettings = FontVariation.Settings(FontVariation.weight(weight.weight)),
    )

/**
 * The Geist font family, spanning the weights Mealsy's type roles use
 * (400/500/600/700/800), all backed by one variable-font resource.
 */
val GeistFamily =
    FontFamily(
        geist(FontWeight.Normal),
        geist(FontWeight.Medium),
        geist(FontWeight.SemiBold),
        geist(FontWeight.Bold),
        geist(FontWeight.ExtraBold),
    )

/**
 * The Mealsy type scale. Every style uses [GeistFamily] and tabular figures
 * (`fontFeatureSettings = "tnum"`) per the design system's numeral rule.
 *
 * [hero] and [eyebrow] are rendered in UPPERCASE by the caller (e.g. via
 * `.uppercase()` on the string) — these styles do not transform case
 * themselves.
 */
object MealsyType {
    /** 46sp hero display text. Caller renders this uppercase. */
    val hero =
        TextStyle(
            fontFamily = GeistFamily,
            fontWeight = FontWeight.SemiBold,
            fontSize = 46.sp,
            lineHeight = 47.sp,
            letterSpacing = (-0.02).em,
            fontFeatureSettings = "tnum",
        )

    /** 32sp display text, may wrap two lines. */
    val display =
        TextStyle(
            fontFamily = GeistFamily,
            fontWeight = FontWeight.Medium,
            fontSize = 32.sp,
            lineHeight = 35.2.sp,
            letterSpacing = (-0.02).em,
            fontFeatureSettings = "tnum",
        )

    /** 30sp screen title. */
    val screenTitle =
        TextStyle(
            fontFamily = GeistFamily,
            fontWeight = FontWeight.Medium,
            fontSize = 30.sp,
            lineHeight = 33.6.sp,
            letterSpacing = (-0.02).em,
            fontFeatureSettings = "tnum",
        )

    /** 17sp section heading. */
    val section =
        TextStyle(
            fontFamily = GeistFamily,
            fontWeight = FontWeight.Medium,
            fontSize = 17.sp,
            lineHeight = 22.sp,
            letterSpacing = 0.em,
            fontFeatureSettings = "tnum",
        )

    /** 14sp body copy. */
    val body =
        TextStyle(
            fontFamily = GeistFamily,
            fontWeight = FontWeight.Normal,
            fontSize = 14.sp,
            lineHeight = 21.sp,
            letterSpacing = 0.em,
            fontFeatureSettings = "tnum",
        )

    /** 12sp label, typically colored `muted`. */
    val label =
        TextStyle(
            fontFamily = GeistFamily,
            fontWeight = FontWeight.Normal,
            fontSize = 12.sp,
            lineHeight = 16.sp,
            letterSpacing = 0.em,
            fontFeatureSettings = "tnum",
        )

    /** 11sp eyebrow label. Caller renders this uppercase. */
    val eyebrow =
        TextStyle(
            fontFamily = GeistFamily,
            fontWeight = FontWeight.Medium,
            fontSize = 11.sp,
            lineHeight = 14.sp,
            letterSpacing = 0.12.em,
            fontFeatureSettings = "tnum",
        )

    /** 15sp button label. */
    val button =
        TextStyle(
            fontFamily = GeistFamily,
            fontWeight = FontWeight.Medium,
            fontSize = 15.sp,
            lineHeight = 20.sp,
            letterSpacing = 0.em,
            fontFeatureSettings = "tnum",
        )

    /** 12sp badge text. */
    val badge =
        TextStyle(
            fontFamily = GeistFamily,
            fontWeight = FontWeight.Medium,
            fontSize = 12.sp,
            lineHeight = 16.sp,
            letterSpacing = 0.em,
            fontFeatureSettings = "tnum",
        )

    /** 10sp tiny metadata tag text. */
    val tinyTag =
        TextStyle(
            fontFamily = GeistFamily,
            fontWeight = FontWeight.Medium,
            fontSize = 10.sp,
            lineHeight = 13.sp,
            letterSpacing = 0.04.em,
            fontFeatureSettings = "tnum",
        )

    /** 19sp metric value. */
    val bigNumber =
        TextStyle(
            fontFamily = GeistFamily,
            fontWeight = FontWeight.Medium,
            fontSize = 19.sp,
            lineHeight = 24.sp,
            letterSpacing = 0.em,
            fontFeatureSettings = "tnum",
        )

    /** 26sp large metric value. */
    val bigNumberLarge =
        TextStyle(
            fontFamily = GeistFamily,
            fontWeight = FontWeight.Medium,
            fontSize = 26.sp,
            lineHeight = 30.sp,
            letterSpacing = 0.em,
            fontFeatureSettings = "tnum",
        )
}
