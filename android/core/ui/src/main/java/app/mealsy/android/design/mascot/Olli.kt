package app.mealsy.android.design.mascot

import android.provider.Settings
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.R
import app.mealsy.android.design.theme.LocalReducedMotion
import app.mealsy.android.design.theme.MealsyTheme
import coil.ImageLoader
import coil.compose.rememberAsyncImagePainter
import coil.decode.ImageDecoderDecoder
import coil.request.ImageRequest

/**
 * Olli, the Mealsy mascot, rendered as a looping animated WebP.
 *
 * Olli is allowed ONLY in four places per the design system: onboarding,
 * empty states, the chat header, and the status-pill "bite" point. Never use
 * Olli on ordinary data screens.
 *
 * ### Inspection-mode determinism
 * When [LocalInspectionMode] is true (Compose `@Preview` and Roborazzi /
 * Robolectric screenshot tests both set this), Coil is skipped entirely and
 * the deterministic first frame ([R.drawable.olli_static]) is rendered with
 * no animation and no bob. This is what keeps screenshot goldens stable —
 * screenshot tests exercising [Olli] should expect the static frame, not the
 * animated WebP.
 *
 * ### Reduced motion
 * If the system's `Settings.Global.ANIMATOR_DURATION_SCALE` is `0f` (the
 * user has disabled animations system-wide), Olli renders the static frame
 * instead of animating, both for the WebP loop and for [olliBob].
 *
 * @param modifier Modifier applied to the rendered mascot.
 * @param size Target size; see [OlliSize] for the four sanctioned sizes.
 * @param bob Whether to apply the idle bob animation via [olliBob].
 * @param contentDescription Accessibility description. Defaults to `null`
 *   because Olli is decorative in most placements. Callers who use Olli as
 *   the only content of an otherwise meaningful element (for example, a
 *   button whose sole visual is Olli) must pass a real description.
 */
@Composable
fun Olli(
    modifier: Modifier = Modifier,
    size: Dp = OlliSize.Header,
    bob: Boolean = true,
    contentDescription: String? = null,
) {
    val inInspection = LocalInspectionMode.current
    val context = LocalContext.current

    val animationsEnabled = remember {
        try {
            Settings.Global.getFloat(
                context.contentResolver,
                Settings.Global.ANIMATOR_DURATION_SCALE,
            ) != 0f
        } catch (_: Settings.SettingNotFoundException) {
            true
        }
    }

    // LocalReducedMotion already folds in LocalInspectionMode (see
    // ReducedMotion.kt), so this also stays static under `@Preview` and
    // Roborazzi; animationsEnabled additionally covers the system-wide
    // "Remove animations" setting even when Olli is rendered outside
    // MealsyTheme (LocalReducedMotion then falls back to its `false` default).
    val reducedMotion = LocalReducedMotion.current
    val bobModifier = if (bob && animationsEnabled && !inInspection && !reducedMotion) {
        Modifier.olliBob()
    } else {
        Modifier
    }

    if (inInspection) {
        Image(
            painter = painterResource(R.drawable.olli_static),
            contentDescription = contentDescription,
            modifier = modifier.then(bobModifier).size(size),
        )
        return
    }

    val imageLoader = remember(context) {
        ImageLoader.Builder(context)
            .components { add(ImageDecoderDecoder.Factory()) }
            .build()
    }

    if (!animationsEnabled) {
        Image(
            painter = painterResource(R.drawable.olli_static),
            contentDescription = contentDescription,
            modifier = modifier.then(bobModifier).size(size),
        )
        return
    }

    val request = remember(context) {
        ImageRequest.Builder(context)
            .data(R.raw.olli)
            .build()
    }

    Image(
        painter = rememberAsyncImagePainter(model = request, imageLoader = imageLoader),
        contentDescription = contentDescription,
        modifier = modifier.then(bobModifier).size(size),
    )
}

/**
 * The four sanctioned sizes for [Olli], one per allowed placement.
 *
 * These are NOT the design spec's nominal 34/46/150/200dp — do not "fix"
 * them back to those numbers. `olli.webp` was cropped to its visible alpha
 * bounds (53×78px mascot, was padded out to a square 150×150 canvas, now a
 * 61×86 canvas). [Olli] renders it in a square `Modifier.size(size)` box
 * with the default `ContentScale.Fit`, so the box's *height* is always the
 * constraining dimension and the visible mascot height is
 * `size × (78 / 86)` (≈0.907× the box) — versus `size × (78 / 150)` (≈0.52×
 * the box) for the old, more-padded asset. Concretely, at each placement's
 * old nominal dp box the mascot would now read noticeably larger:
 *
 * - [Header] and [Done]/[Welcome] are set so the mascot's *visible* height
 *   matches what it looked like pre-crop: box = old nominal dp × (0.52 /
 *   0.907) ≈ old nominal dp × 0.573 (Done 150→86dp, Welcome 200→115dp).
 * - [Header] intentionally follows the same 0.573 factor as well (34→~20dp
 *   box) would read as *smaller* than intended at very small sizes, so it
 *   is nudged up to 30dp (visible mascot ≈27dp) for legibility in the chat
 *   header.
 * - [Bite] is deliberately made to read LARGER than before — that was the
 *   point of the tighter crop for the status-pill bite point — so it is
 *   not rescaled to match the old visual size; it targets a ≈34dp visible
 *   mascot height (box 38dp × 0.907 ≈ 34.5dp), versus the old asset's
 *   effective ≈24dp visible height at the old 46dp box.
 */
object OlliSize {
    /** Olli in the chat header, alongside the title. */
    val Header: Dp = 30.dp

    /** Olli at the "bite" point of the status pill / snack-bar. */
    val Bite: Dp = 38.dp

    /** Olli on the onboarding "done" / completion step. */
    val Done: Dp = 86.dp

    /** Olli on the onboarding welcome screen. */
    val Welcome: Dp = 115.dp
}

/**
 * Applies Olli's idle "bob" animation: translateY from 0dp to -8dp over
 * 3200ms with ease-in-out easing, reversing indefinitely.
 *
 * @param enabled Whether the bob animation should run. Callers are
 *   responsible for disabling this under reduced-motion settings; [Olli]
 *   itself already accounts for that.
 */
@Composable
fun Modifier.olliBob(enabled: Boolean = true): Modifier {
    if (!enabled) return this
    val transition = rememberInfiniteTransition(label = "olliBob")
    val translation by transition.animateFloat(
        initialValue = 0f,
        targetValue = -8f,
        animationSpec = infiniteRepeatable(
            animation = tween(
                durationMillis = 3200,
                easing = CubicBezierEasing(0.42f, 0f, 0.58f, 1f),
            ),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "olliBobY",
    )
    return this.graphicsLayer { translationY = translation.dp.toPx() }
}

@Preview(name = "Olli - light", showBackground = true)
@Preview(name = "Olli - dark", uiMode = 0x21, showBackground = true)
@Composable
private fun OlliPreview() {
    MealsyTheme {
        Surface {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Olli(size = OlliSize.Header)
                Olli(size = OlliSize.Bite)
                Olli(size = OlliSize.Done)
                Olli(size = OlliSize.Welcome)
            }
        }
    }
}
