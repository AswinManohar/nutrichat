package app.mealsy.android.ui.mymeals

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.onClick
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
import app.mealsy.android.ui.common.ErrorKind
import app.mealsy.android.ui.common.ErrorState
import app.mealsy.android.ui.common.LoadingState
import app.mealsy.data.repo.SavedMeal
import app.mealsy.domain.CardItem
import app.mealsy.domain.FoodNameHumanizer
import app.mealsy.domain.PastelTone
import app.mealsy.domain.pastelToneFor
import kotlinx.serialization.json.JsonObject
import java.text.NumberFormat
import java.util.Locale

/** [SwipeToDismissBoxState]'s positional threshold for a swipe-to-delete — dp-based (not px) so it's density-independent (#48 item 2). Mirrors [app.mealsy.android.ui.meals.MealTypeListScreen]'s. */
private val SWIPE_DELETE_THRESHOLD = 96.dp

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
    val pendingUndoIds by viewModel.pendingUndoIds.collectAsStateWithLifecycle()
    val failedDeleteIds by viewModel.failedDeleteIds.collectAsStateWithLifecycle()

    MyMealsContent(
        uiState = uiState,
        hiddenIds = hiddenIds,
        pendingUndoIds = pendingUndoIds,
        onOpenMeal = onOpenMeal,
        onRetry = viewModel::load,
        onDeleteWithUndo = viewModel::deleteWithUndo,
        onUndoDelete = viewModel::undoDelete,
        failedDeleteIds = failedDeleteIds,
        onRetryDelete = viewModel::retryDelete,
        onDismissDeleteFailure = viewModel::dismissDeleteFailure,
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
    pendingUndoIds: Set<String> = emptySet(),
    failedDeleteIds: Set<String> = emptySet(),
    onRetryDelete: (String) -> Unit = {},
    onDismissDeleteFailure: (String) -> Unit = {},
) {
    // The most recently swiped meal, kept only so the toast has a name/id to
    // render — its *visibility* is driven by [pendingUndoIds] (the
    // ViewModel's own undo window), not by a timer of this composable's own.
    // Running an independent screen-level timer here previously could drift
    // from `MyMealsViewModel.undoWindowMs` (e.g. shrunk by tests, or simply
    // by having two hardcoded durations to keep in sync), letting the toast
    // disappear before the delete was actually committed, or worse, stay
    // visible after the delete already fired — see MyMealsScreen's undo
    // review (Phase 5 cleanup).
    var lastSwiped by remember { mutableStateOf<SavedMeal?>(null) }

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
                    ErrorState(
                        stringResource(
                            when (state.kind) {
                                ErrorKind.Offline -> R.string.error_offline
                                ErrorKind.LoadFailed -> R.string.my_meals_error_load_failed
                            },
                        ),
                        onRetry = onRetry,
                        modifier = Modifier.fillMaxSize(),
                    )
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
                                                lastSwiped = meal
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

        val toastTarget = lastSwiped?.takeIf { it.id in pendingUndoIds }
        if (toastTarget != null) {
            UndoToast(
                onUndo = {
                    onUndoDelete(toastTarget.id)
                    lastSwiped = null
                },
                modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 24.dp),
            )
        }

        // #52: a failed DELETE restores the meal to the list; say so, with a retry.
        val failedId = failedDeleteIds.firstOrNull()
        if (failedId != null) {
            DeleteFailedToast(
                onRetry = { onRetryDelete(failedId) },
                modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 24.dp),
            )
            LaunchedEffect(failedId) {
                kotlinx.coroutines.delay(DELETE_FAILED_TOAST_MS)
                onDismissDeleteFailure(failedId)
            }
        }
    }
}

private const val DELETE_FAILED_TOAST_MS = 6_000L

/** "Couldn't delete" [InkToast] with a tappable "Retry" pill, shown when a delete fails. */
@Composable
private fun DeleteFailedToast(
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        InkToast(text = stringResource(R.string.my_meals_delete_failed_toast))
        androidx.compose.material3.Surface(
            shape = app.mealsy.android.design.theme.MealsyShapes.pill,
            color = colors.ink,
            modifier = Modifier.clickable(onClick = onRetry),
        ) {
            androidx.compose.material3.Text(
                text = stringResource(R.string.my_meals_delete_retry),
                style = MealsyType.badge,
                color = colors.olive,
                modifier = Modifier.padding(vertical = 12.dp, horizontal = 14.dp),
            )
        }
    }
}

/**
 * The themed undo toast shown after a swipe-delete: [InkToast]'s "Deleted"
 * copy plus a tappable "Undo" affordance overlaid on the same pill.
 */
@Composable
private fun UndoToast(
    onUndo: () -> Unit,
    modifier: Modifier = Modifier,
) {
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
private fun formatKcal(kcal: Double): String = NumberFormat.getIntegerInstance(Locale.US).format(kcal.toInt())

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

private fun SavedMeal.toCardItem(): CardItem =
    CardItem(
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

private fun PastelTone.toTagTone(): TagTone =
    when (this) {
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
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SavedMealRow(
    meal: SavedMeal,
    onTap: () -> Unit,
    onSwipeDelete: () -> Unit,
) {
    val colors = MealsyTheme.colors
    val density = LocalDensity.current
    val thresholdPx = with(density) { SWIPE_DELETE_THRESHOLD.toPx() }

    val dismissState =
        rememberSwipeToDismissBoxState(
            positionalThreshold = { thresholdPx },
        )

    LaunchedEffect(dismissState.currentValue) {
        if (dismissState.currentValue == SwipeToDismissBoxValue.EndToStart) {
            onSwipeDelete()
            dismissState.snapTo(SwipeToDismissBoxValue.Settled)
        }
    }

    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()
    // Opaque (not Color.Transparent) so it fully covers the SwipeToDismissBox's
    // terracotta backgroundContent at rest — a transparent row here let that
    // background bleed through even when not swiping. Mirrors
    // MealTypeListScreen's SwipeableMealRow.
    val background = if (pressed) colors.surfacePressed else colors.surface

    val kcalText = stringResource(R.string.my_meals_row_kcal, formatKcal(meal.kcal))
    val description =
        stringResource(
            R.string.my_meals_row_description,
            meal.name,
            meal.kcal.toInt().toString(),
            meal.proteinG.toInt().toString(),
        )
    val openLabel = stringResource(R.string.my_meals_open_label)
    val deleteAction = stringResource(R.string.my_meals_delete_action)

    // Reduced motion shortens/skips SwipeToDismissBox's own settle animation —
    // it doesn't take the gesture away — so gesturesEnabled stays true
    // unconditionally, matching MealTypeListScreen's row (#48).
    SwipeToDismissBox(
        state = dismissState,
        enableDismissFromStartToEnd = false,
        backgroundContent = {
            Box(
                modifier =
                    Modifier
                        .fillMaxSize()
                        .background(colors.terracotta)
                        .padding(horizontal = 20.dp),
                contentAlignment = Alignment.CenterEnd,
            ) {
                Icon(
                    imageVector = MealsyIcons.Trash,
                    contentDescription = deleteAction,
                    tint = colors.terracottaText,
                )
            }
        },
    ) {
        Row(
            modifier =
                Modifier
                    .fillMaxWidth()
                    .defaultMinSize(minHeight = 48.dp)
                    .background(background)
                    .clickable(
                        interactionSource = interactionSource,
                        indication = null,
                        onClickLabel = openLabel,
                        role = Role.Button,
                        onClick = onTap,
                    )
                    // clickable() above gives the row a click action/role for
                    // TalkBack, but clearAndSetSemantics below replaces the
                    // merged-children semantics tree with a single curated
                    // description — which would otherwise drop that click
                    // action too (#48 item 1), so it's re-declared here.
                    .clearAndSetSemantics {
                        contentDescription = description
                        onClick(label = openLabel) {
                            onTap()
                            true
                        }
                        customActions =
                            listOf(
                                CustomAccessibilityAction(deleteAction) {
                                    onSwipeDelete()
                                    true
                                },
                            )
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
}
