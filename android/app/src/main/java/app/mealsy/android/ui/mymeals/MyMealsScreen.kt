package app.mealsy.android.ui.mymeals

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.PointerInputScope
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.R
import app.mealsy.android.design.components.Eyebrow
import app.mealsy.android.design.components.InkToast
import app.mealsy.android.design.components.InsetDivider
import app.mealsy.android.design.components.ListContainer
import app.mealsy.android.design.components.PastelIconCircle
import app.mealsy.android.design.components.TagChip
import app.mealsy.android.design.components.TagTone
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.mascot.Olli
import app.mealsy.android.design.mascot.OlliSize
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.design.theme.mealsyScreenPadding
import app.mealsy.android.ui.common.ErrorState
import app.mealsy.android.ui.common.LoadingState
import app.mealsy.data.repo.SavedMeal
import app.mealsy.domain.CardItem
import app.mealsy.domain.FoodNameHumanizer
import app.mealsy.domain.PastelTone
import app.mealsy.domain.pastelToneFor
import java.text.NumberFormat
import java.util.Locale
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject

private const val SWIPE_DELETE_THRESHOLD_PX = 300f
private const val UNDO_TOAST_MS = 4_000L

/**
 * My Meals screen: saved quick-log meals with per-meal macros, tap to open
 * meal detail (which offers its own log-again flow), swipe-to-delete with an
 * undo toast.
 *
 * [onLoggedNavigateToChat] is retained for API compatibility with existing
 * call sites but is no longer invoked from a row tap — logging now happens
 * from [app.mealsy.android.ui.mealdetail.MealDetailScreen] after
 * [onOpenMeal] navigates there.
 *
 * @param onOpenMeal Navigates to the meal-detail screen (My-Meal mode) for a
 *   tapped row's meal id.
 */
@Composable
fun MyMealsScreen(
    viewModel: MyMealsViewModel = hiltViewModel(),
    onLoggedNavigateToChat: () -> Unit = {},
    onOpenMeal: (String) -> Unit = {},
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val hiddenIds by viewModel.hiddenIds.collectAsStateWithLifecycle()

    MyMealsContent(
        uiState = uiState,
        hiddenIds = hiddenIds,
        onOpenMeal = onOpenMeal,
        onRetry = viewModel::load,
        onDeleteWithUndo = viewModel::deleteWithUndo,
        onUndoDelete = viewModel::undoDelete,
    )
}

/**
 * [MyMealsScreen]'s content, taking its state directly rather than a
 * `ViewModel` so [app.mealsy.android.ui.mymeals.MyMealsGoldenTest] can drive
 * it with fake/in-memory state (no network), mirroring
 * [app.mealsy.android.ui.mealdetail.MealDetailContent]'s pattern.
 */
@Composable
internal fun MyMealsContent(
    uiState: MyMealsUiState,
    hiddenIds: Set<String>,
    onOpenMeal: (String) -> Unit,
    onRetry: () -> Unit,
    onDeleteWithUndo: (String) -> Unit,
    onUndoDelete: (String) -> Unit,
) {
    val scope = rememberCoroutineScope()
    var undoTarget by remember { mutableStateOf<SavedMeal?>(null) }

    Box(modifier = Modifier.fillMaxSize()) {
        Column(modifier = Modifier.fillMaxSize().mealsyScreenPadding()) {
            Eyebrow(text = stringResource(R.string.my_meals_eyebrow))
            androidx.compose.foundation.layout.Spacer(modifier = Modifier.height(4.dp))
            androidx.compose.material3.Text(
                text = stringResource(R.string.my_meals_title),
                style = MealsyType.display,
                color = MealsyTheme.colors.ink,
            )
            androidx.compose.foundation.layout.Spacer(modifier = Modifier.height(10.dp))

            when (val state = uiState) {
                MyMealsUiState.Loading ->
                    LoadingState(stringResource(R.string.my_meals_loading), modifier = Modifier.fillMaxSize())
                MyMealsUiState.Empty -> MyMealsEmptyState(modifier = Modifier.fillMaxSize())
                is MyMealsUiState.Error ->
                    ErrorState(state.message, onRetry = onRetry, modifier = Modifier.fillMaxSize())
                is MyMealsUiState.Loaded -> {
                    val visible = state.meals.filterNot { it.id in hiddenIds }
                    if (visible.isEmpty()) {
                        MyMealsEmptyState(modifier = Modifier.fillMaxSize())
                    } else {
                        LazyColumn(modifier = Modifier.fillMaxWidth()) {
                            item {
                                ListContainer {
                                    visible.forEachIndexed { index, meal ->
                                        SavedMealRow(
                                            meal = meal,
                                            onTap = { onOpenMeal(meal.id) },
                                            onSwipeDelete = {
                                                onDeleteWithUndo(meal.id)
                                                undoTarget = meal
                                                scope.launch {
                                                    delay(UNDO_TOAST_MS)
                                                    if (undoTarget?.id == meal.id) undoTarget = null
                                                }
                                            },
                                        )
                                        if (index != visible.lastIndex) InsetDivider()
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        val toastTarget = undoTarget
        if (toastTarget != null) {
            UndoToast(
                onUndo = {
                    onUndoDelete(toastTarget.id)
                    undoTarget = null
                },
                modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 24.dp),
            )
        }
    }
}

/**
 * The themed undo toast shown after a swipe-delete: [InkToast]'s "Deleted"
 * copy plus a tappable "Undo" affordance overlaid on the same pill.
 */
@Composable
private fun UndoToast(onUndo: () -> Unit, modifier: Modifier = Modifier) {
    val colors = MealsyTheme.colors
    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        InkToast(text = stringResource(R.string.my_meals_deleted_toast))
        androidx.compose.material3.Surface(
            shape = app.mealsy.android.design.theme.MealsyShapes.pill,
            color = colors.ink,
            modifier = Modifier.clickable(onClick = onUndo),
        ) {
            androidx.compose.material3.Text(
                text = stringResource(R.string.my_meals_undo),
                style = MealsyType.badge,
                color = colors.olive,
                modifier = Modifier.padding(vertical = 12.dp, horizontal = 14.dp),
            )
        }
    }
}

@Composable
private fun MyMealsEmptyState(modifier: Modifier = Modifier) {
    Box(modifier = modifier, contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Olli(size = OlliSize.Done, bob = true)
            androidx.compose.foundation.layout.Spacer(modifier = Modifier.height(12.dp))
            androidx.compose.material3.Text(
                text = stringResource(R.string.my_meals_empty_body),
                style = MealsyType.body,
                color = MealsyTheme.colors.muted,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                modifier = Modifier.padding(horizontal = 32.dp),
            )
        }
    }
}

/** Formats [kcal] as tabular, thousands-separated whole kcal, e.g. "1,340". */
private fun formatKcal(kcal: Double): String =
    NumberFormat.getIntegerInstance(Locale.US).format(kcal.toInt())

/**
 * Heuristic for whether [raw] looks like a raw USDA description (and should
 * be run through [FoodNameHumanizer.humanize]) versus a name the user typed
 * themselves (shown verbatim): raw USDA strings are either comma-separated
 * (`"Chicken, broilers or fryers, breast, meat only, cooked, grilled"`) or
 * fully upper-case with no lowercase letters (`"USUAL BREAKFAST"` would
 * NOT trip this — it has no comma and is a plausible user title, but a name
 * like `"CHICKEN, BREAST"` trips both signals).
 */
internal fun displayName(raw: String): String {
    val hasComma = raw.contains(',')
    val isAllCaps = raw.isNotBlank() && raw.any { it.isLetter() } && raw.none { it.isLowerCase() }
    return when {
        // All-caps input carries no case information to preserve, so lower
        // it first: this keeps a no-comma blob like "CHICKEN BREAST" from
        // surviving humanize()'s sentence-case-only pass-through unchanged.
        isAllCaps -> FoodNameHumanizer.humanize(raw.lowercase())
        hasComma -> FoodNameHumanizer.humanize(raw)
        else -> raw
    }
}

private fun SavedMeal.toCardItem(): CardItem = CardItem(
    foodName = name,
    qtyG = 1.0,
    targetQtyG = 1.0,
    kcal = kcal,
    proteinG = proteinG,
    carbsG = carbsG,
    fatG = fatG,
    fiberG = fiberG,
    fdcId = 0L,
    estimated = false,
    extras = JsonObject(emptyMap()),
)

private fun PastelTone.toTagTone(): TagTone = when (this) {
    PastelTone.Leaf -> TagTone.Leaf
    PastelTone.Butter -> TagTone.Butter
    PastelTone.Powder -> TagTone.Powder
    PastelTone.Pink -> TagTone.Pink
}

/**
 * One saved meal row, styled to match [app.mealsy.android.design.components.ListRow]'s
 * height/padding/pressed state (composed by hand rather than through
 * `ListRow` itself, since this row needs a [TagChip] trailing element that
 * `ListRow`'s `trailingText`/`badgeCount` slots can't express, and `ListRow`
 * is owned by `:core:ui` — see the Phase 5 T2 report for why it isn't
 * extended instead). Tap opens meal detail; swipe left past the threshold
 * deletes (optimistic hide + undo, driven by the caller).
 */
@Composable
private fun SavedMealRow(meal: SavedMeal, onTap: () -> Unit, onSwipeDelete: () -> Unit) {
    val colors = MealsyTheme.colors
    var dragOffset by remember { mutableStateOf(0f) }
    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()
    val background = if (pressed) colors.surfacePressed else androidx.compose.ui.graphics.Color.Transparent

    val kcalText = stringResource(R.string.my_meals_row_kcal, formatKcal(meal.kcal))
    val description = stringResource(
        R.string.my_meals_row_description,
        meal.name,
        meal.kcal.toInt().toString(),
        meal.proteinG.toInt().toString(),
    )
    val deleteAction = stringResource(R.string.my_meals_delete_action)

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .defaultMinSize(minHeight = 48.dp)
            .background(background)
            .pointerInput(meal.id) {
                detectHorizontalDragGestures(
                    onDragEnd = {
                        if (dragOffset < -SWIPE_DELETE_THRESHOLD_PX) onSwipeDelete()
                        dragOffset = 0f
                    },
                    onHorizontalDrag = { _, dragAmount -> dragOffset += dragAmount },
                )
            }
            .pointerInput(meal.id) { detectTapToLog(onTap) }
            .clearAndSetSemantics {
                contentDescription = description
                customActions = listOf(CustomAccessibilityAction(deleteAction) { onSwipeDelete(); true })
            }
            .padding(vertical = 9.dp, horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        PastelIconCircle(
            icon = MealsyIcons.Bowl,
            tone = pastelToneFor(meal.toCardItem()).toTagTone(),
            size = 34.dp,
        )
        androidx.compose.material3.Text(
            text = displayName(meal.name),
            style = MealsyType.body,
            color = colors.ink,
            modifier = Modifier.weight(1f),
        )
        TagChip(text = kcalText, tone = TagTone.Butter)
        Icon(
            imageVector = MealsyIcons.ChevronRight,
            contentDescription = null,
            tint = colors.inactive,
            modifier = Modifier.padding(start = 2.dp).size(13.dp),
        )
    }
}

private suspend fun PointerInputScope.detectTapToLog(onTap: () -> Unit) {
    detectTapGestures(onTap = { onTap() })
}
