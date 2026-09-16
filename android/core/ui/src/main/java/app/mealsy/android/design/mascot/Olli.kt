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

    val bobModifier = if (bob && animationsEnabled && !inInspection) {
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
 */
object OlliSize {
    /** Olli in the chat header, alongside the title. */
    val Header: Dp = 34.dp

    /** Olli at the "bite" point of the status pill / snack-bar. */
    val Bite: Dp = 46.dp

    /** Olli on the onboarding "done" / completion step. */
    val Done: Dp = 150.dp

    /** Olli on the onboarding welcome screen. */
    val Welcome: Dp = 200.dp
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
