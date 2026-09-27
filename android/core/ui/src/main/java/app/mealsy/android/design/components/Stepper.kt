package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.setProgress
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.design.theme.rememberMealsyHaptics
import kotlinx.coroutines.delay

/** A generously-bounded ceiling used when [Stepper.max] is left at its
 * unbounded [Int.MAX_VALUE] default, so [ProgressBarRangeInfo] always gets a
 * finite range for TalkBack's adjustable-widget gesture. */
private const val UNBOUNDED_RANGE_PADDING = 1000

/** How long a press must be held before hold-to-repeat kicks in. */
private const val REPEAT_INITIAL_DELAY_MS = 450L

/** The repeat interval floor once acceleration has fully ramped up. */
private const val REPEAT_MIN_INTERVAL_MS = 60L

/** The repeat interval ceiling when hold-to-repeat first kicks in. */
private const val REPEAT_MAX_INTERVAL_MS = 220L

/** How many repeats it takes to ramp from [REPEAT_MAX_INTERVAL_MS] down to
 * [REPEAT_MIN_INTERVAL_MS]. */
private const val REPEAT_RAMP_STEPS = 12

/** The proper minus sign (U+2212), taller and better-aligned to the
 * baseline than an ASCII hyphen at large font scales. */
private const val MINUS_SIGN = "−"

/**
 * Mealsy's gram-quantity stepper, used on food rows in the meal confirm card.
 *
 * Exposes itself to TalkBack as an adjustable widget: [progressBarRangeInfo]
 * plus a [setProgress] action let a swipe-up/down gesture on the whole
 * control change [value] by [step], in addition to tapping the +/- buttons
 * directly. The +/- buttons also support press-and-hold with acceleration,
 * and tapping the value itself switches it to a direct-entry text field.
 *
 * @param value The current integer value.
 * @param onValueChange Invoked with the new value when a button is tapped,
 *   held, or a typed value is committed.
 * @param modifier The modifier applied to the stepper's track.
 * @param step The amount to add or subtract per tap or repeat.
 * @param min The minimum allowed value; the decrease button disables here.
 * @param max The maximum allowed value; the increase button disables here.
 * @param label The accessibility label announced together with the current
 *   value, e.g. "Quantity, 120 g".
 * @param valueLabel Formats [value] for both the visible label and the
 *   accessibility [androidx.compose.ui.semantics.stateDescription].
 */
@Composable
fun Stepper(
    value: Int,
    onValueChange: (Int) -> Unit,
    modifier: Modifier = Modifier,
    step: Int = 5,
    min: Int = 5,
    max: Int = Int.MAX_VALUE,
    label: String = "Quantity",
    valueLabel: (Int) -> String = { "$it g" },
) {
    val colors = MealsyTheme.colors
    val haptics = rememberMealsyHaptics()
    val canDecrease = value > min
    val canIncrease = value < max
    val effectiveMax = if (max == Int.MAX_VALUE) value + UNBOUNDED_RANGE_PADDING else max
    var editing by remember { mutableStateOf(false) }

    Surface(
        modifier =
            modifier.semantics(mergeDescendants = true) {
                contentDescription = label
                stateDescription = valueLabel(value)
                progressBarRangeInfo =
                    ProgressBarRangeInfo(
                        current = value.toFloat(),
                        range = min.toFloat()..effectiveMax.toFloat(),
                        steps = 0,
                    )
                setProgress { targetValue ->
                    val next = targetValue.toInt().coerceIn(min, effectiveMax)
                    if (next != value) {
                        onValueChange(next)
                        true
                    } else {
                        false
                    }
                }
            },
        shape = MealsyShapes.pill,
        color = colors.canvas,
        border = BorderStroke(1.dp, colors.hairline),
    ) {
        Row(
            modifier = Modifier.padding(3.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            RepeatingStepperButton(
                symbol = MINUS_SIGN,
                enabled = canDecrease,
                contentDescription = "Decrease",
                onStep = { onValueChange((value - step).coerceAtLeast(min)) },
                onRepeatTick = haptics::tick,
            )
            if (editing) {
                StepperValueField(
                    initialValue = value,
                    min = min,
                    max = max,
                    onCommit = { committed ->
                        onValueChange(committed.coerceIn(min, max))
                        editing = false
                    },
                    onCancel = { editing = false },
                )
            } else {
                val slideDurationMs = app.mealsy.android.design.theme.motionDurationMs(120)
                AnimatedContent(
                    targetState = value,
                    transitionSpec = {
                        val duration = slideDurationMs
                        val direction = if (targetState > initialState) 1 else -1
                        (
                            slideInVertically(tween(duration)) { direction * it } togetherWith
                                slideOutVertically(tween(duration)) { -direction * it }
                        )
                    },
                    label = "stepper-value",
                    modifier =
                        Modifier
                            .widthIn(min = 44.dp)
                            .clickable(
                                interactionSource = remember { MutableInteractionSource() },
                                indication = null,
                            ) { editing = true },
                ) { animatedValue ->
                    Text(
                        text = valueLabel(animatedValue),
                        style =
                            MealsyType.badge.copy(
                                fontSize =
                                    androidx.compose.ui.unit.TextUnit(
                                        13f,
                                        androidx.compose.ui.unit.TextUnitType.Sp,
                                    ),
                            ),
                        color = colors.ink,
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                        modifier = Modifier.widthIn(min = 44.dp),
                    )
                }
            }
            RepeatingStepperButton(
                symbol = "+",
                enabled = canIncrease,
                contentDescription = "Increase",
                onStep = { onValueChange((value + step).coerceAtMost(max)) },
                onRepeatTick = haptics::tick,
            )
        }
    }
}

/**
 * A direct-entry replacement for the value [Text], shown when the value is
 * tapped. Commits on IME "done" or on losing focus; reverts to the button
 * row via [onCommit] either way (an empty/invalid entry commits [initialValue]
 * unchanged).
 */
@Composable
private fun StepperValueField(
    initialValue: Int,
    min: Int,
    max: Int,
    onCommit: (Int) -> Unit,
    onCancel: () -> Unit,
) {
    val colors = MealsyTheme.colors
    var fieldValue by
        remember {
            mutableStateOf(
                TextFieldValue(
                    text = initialValue.toString(),
                    selection = TextRange(0, initialValue.toString().length),
                ),
            )
        }
    val focusRequester = remember { FocusRequester() }
    var committed = false

    fun commit() {
        if (committed) return
        committed = true
        val parsed = fieldValue.text.toIntOrNull()
        onCommit(parsed?.coerceIn(min, max) ?: initialValue)
    }

    LaunchedEffect(Unit) { focusRequester.requestFocus() }

    BasicTextField(
        value = fieldValue,
        onValueChange = { new ->
            if (new.text.length <= 5 && new.text.all(Char::isDigit)) {
                fieldValue = new
            }
        },
        modifier =
            Modifier
                .widthIn(min = 44.dp)
                .focusRequester(focusRequester)
                .onFocusChanged { if (!it.isFocused) commit() },
        singleLine = true,
        textStyle =
            MealsyType.badge.copy(
                fontSize = androidx.compose.ui.unit.TextUnit(13f, androidx.compose.ui.unit.TextUnitType.Sp),
                color = colors.ink,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            ),
        cursorBrush = SolidColor(colors.ink),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Done),
        keyboardActions = KeyboardActions(onDone = { commit() }),
    )
}

/**
 * A [StepperButton] wired for press-and-hold repeat: after
 * [REPEAT_INITIAL_DELAY_MS] of a continuous press it starts firing
 * [onStep] on an interval that ramps from [REPEAT_MAX_INTERVAL_MS] down to
 * [REPEAT_MIN_INTERVAL_MS] over [REPEAT_RAMP_STEPS] repeats, so a long hold
 * moves fast without every tap needing that speed.
 */
@Composable
private fun RepeatingStepperButton(
    symbol: String,
    enabled: Boolean,
    contentDescription: String,
    onStep: () -> Unit,
    onRepeatTick: () -> Unit,
) {
    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()

    LaunchedEffect(pressed, enabled) {
        if (!pressed || !enabled) return@LaunchedEffect
        delay(REPEAT_INITIAL_DELAY_MS)
        var repeatCount = 0
        while (true) {
            onStep()
            onRepeatTick()
            repeatCount++
            val progress = (repeatCount.toFloat() / REPEAT_RAMP_STEPS).coerceAtMost(1f)
            val interval =
                (
                    REPEAT_MAX_INTERVAL_MS -
                        (REPEAT_MAX_INTERVAL_MS - REPEAT_MIN_INTERVAL_MS) * progress
                ).toLong()
            delay(interval)
        }
    }

    StepperButton(
        symbol = symbol,
        enabled = enabled,
        contentDescription = contentDescription,
        interactionSource = interactionSource,
        onClick = {
            onStep()
            onRepeatTick()
        },
    )
}

@Composable
private fun StepperButton(
    symbol: String,
    enabled: Boolean,
    contentDescription: String,
    onClick: () -> Unit,
    interactionSource: MutableInteractionSource = remember { MutableInteractionSource() },
) {
    val colors = MealsyTheme.colors
    val pressed by interactionSource.collectIsPressedAsState()
    val background = if (pressed) colors.surfacePressed else Color.Transparent

    Box(
        modifier =
            Modifier
                .size(28.dp)
                .alpha(if (enabled) 1f else 0.35f)
                .background(background, androidx.compose.foundation.shape.CircleShape)
                .semantics { this.contentDescription = contentDescription }
                .clickable(
                    interactionSource = interactionSource,
                    indication = null,
                    enabled = enabled,
                    onClick = onClick,
                ),
        contentAlignment = Alignment.Center,
    ) {
        Text(text = symbol, style = MealsyType.button, color = colors.ink)
    }
}

@Preview(name = "Stepper light", widthDp = 390)
@Composable
private fun StepperLightPreview() {
    MealsyTheme {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.padding(20.dp)) {
                Stepper(value = 120, onValueChange = {})
            }
        }
    }
}

@Preview(
    name = "Stepper dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun StepperDarkPreview() {
    MealsyTheme(darkTheme = true) {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.padding(20.dp)) {
                Stepper(value = 5, onValueChange = {}, min = 5)
            }
        }
    }
}
