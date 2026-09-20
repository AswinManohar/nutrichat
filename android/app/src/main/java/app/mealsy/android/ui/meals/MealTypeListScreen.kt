package app.mealsy.android.ui.meals

import android.text.format.DateFormat
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.R
import app.mealsy.android.design.components.CircleIconButton
import app.mealsy.android.design.components.Eyebrow
import app.mealsy.android.design.components.InsetDivider
import app.mealsy.android.design.components.ListContainer
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
import app.mealsy.data.repo.LoggedMeal
import app.mealsy.domain.FoodNameHumanizer
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.math.roundToInt

/**
 * Lists today's logged meals for a single meal type (e.g. "Lunch"), with
 * swipe-to-delete and an undo snackbar.
 *
 * @param onBack Navigates back to Home.
 * @param onOpenMeal Navigates to the meal-detail screen for a tapped row's
 *   meal id.
 */
@Composable
fun MealTypeListScreen(
    onBack: () -> Unit,
    onOpenMeal: (String) -> Unit,
    viewModel: MealTypeListViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val hiddenIds by viewModel.hiddenIds.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val undoneLabel = stringResource(R.string.meal_type_deleted_undo_label)
    val deletedMessage = stringResource(R.string.meal_type_deleted_message)

    Box(modifier = Modifier.fillMaxSize()) {
        MealTypeListContent(
            state = state,
            hiddenIds = hiddenIds,
            mealType = viewModel.mealType,
            onBack = onBack,
            onOpenMeal = onOpenMeal,
            onRetry = viewModel::load,
            onSwipeDelete = { id ->
                viewModel.deleteWithUndo(id)
                scope.launch {
                    val result =
                        snackbarHostState.showSnackbar(
                            message = deletedMessage,
                            actionLabel = undoneLabel,
                        )
                    if (result == SnackbarResult.ActionPerformed) viewModel.undoDelete(id)
                }
            },
            modifier = Modifier.fillMaxSize(),
        )
        SnackbarHost(hostState = snackbarHostState, modifier = Modifier.align(Alignment.BottomCenter))
    }
}

/** [MealTypeListScreen]'s content, with no ViewModel dependency so previews/tests can drive it directly. */
@Composable
internal fun MealTypeListContent(
    state: MealTypeListUiState,
    hiddenIds: Set<String>,
    mealType: String,
    onBack: () -> Unit,
    onOpenMeal: (String) -> Unit,
    onRetry: () -> Unit,
    onSwipeDelete: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.mealsyScreenPadding(showsBottomNav = false)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            CircleIconButton(
                icon = MealsyIcons.ChevronLeft,
                contentDescription = stringResource(R.string.meal_type_back),
                onClick = onBack,
            )
            Eyebrow(text = stringResource(mealTypeLabelRes(mealType)))
            Spacer(modifier = Modifier.width(38.dp))
        }

        Spacer(modifier = Modifier.height(20.dp))

        when (state) {
            MealTypeListUiState.Loading ->
                LoadingState(message = stringResource(R.string.meal_type_loading), modifier = Modifier.fillMaxSize())
            is MealTypeListUiState.Error ->
                ErrorState(
                    message =
                        stringResource(
                            when (state.kind) {
                                ErrorKind.Offline -> R.string.error_offline
                                ErrorKind.LoadFailed -> R.string.meal_type_error_load_failed
                            },
                        ),
                    onRetry = onRetry,
                    modifier = Modifier.fillMaxSize(),
                )
            MealTypeListUiState.Empty ->
                MealTypeEmptyState(mealType = mealType, modifier = Modifier.fillMaxSize())
            is MealTypeListUiState.Loaded -> {
                val visible = state.meals.filterNot { it.mealId in hiddenIds }
                if (visible.isEmpty()) {
                    MealTypeEmptyState(mealType = mealType, modifier = Modifier.fillMaxSize())
                } else {
                    ListContainer {
                        visible.forEachIndexed { index, meal ->
                            SwipeableMealRow(
                                meal = meal,
                                onOpen = { onOpenMeal(meal.mealId) },
                                onSwipeDelete = { onSwipeDelete(meal.mealId) },
                            )
                            if (index != visible.lastIndex) InsetDivider()
                        }
                    }
                }
            }
        }
    }
}

private const val SWIPE_DELETE_THRESHOLD_PX = 300f

@Composable
private fun SwipeableMealRow(
    meal: LoggedMeal,
    onOpen: () -> Unit,
    onSwipeDelete: () -> Unit,
) {
    val colors = MealsyTheme.colors
    var dragOffset by remember { mutableStateOf(0f) }
    val context = LocalContext.current

    val displayLabel =
        remember(meal.label) {
            meal.label?.takeIf { it.isNotBlank() }?.let { FoodNameHumanizer.humanize(it) }
        }
    val timeLabel = remember(meal.loggedAt) { formatLoggedAtTime(meal.loggedAt, context) }

    Row(
        modifier =
            Modifier
                .fillMaxWidth()
                .padding(vertical = 9.dp, horizontal = 16.dp)
                .pointerInput(meal.mealId) {
                    detectHorizontalDragGestures(
                        onDragEnd = {
                            if (dragOffset < -SWIPE_DELETE_THRESHOLD_PX) onSwipeDelete()
                            dragOffset = 0f
                        },
                        onHorizontalDrag = { _, dragAmount -> dragOffset += dragAmount },
                    )
                }
                .pointerInput(meal.mealId) {
                    detectTapGestures(onTap = { onOpen() })
                },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = displayLabel ?: stringResource(R.string.meal_type_generic_label),
                style = MealsyType.body,
                color = colors.ink,
            )
            Spacer(modifier = Modifier.height(2.dp))
            Text(text = timeLabel, style = MealsyType.label, color = colors.muted)
        }
        TagChip(text = stringResource(R.string.meal_type_kcal_chip, meal.kcal.roundToInt()), tone = TagTone.Butter)
        androidx.compose.material3.Icon(
            imageVector = MealsyIcons.ChevronRight,
            contentDescription = null,
            tint = colors.inactive,
            modifier = Modifier.height(13.dp).width(13.dp),
        )
    }
}

/** Formats an ISO instant [loggedAt] to a local `12:40`-style time, honoring the device's 24h setting. */
internal fun formatLoggedAtTime(
    loggedAt: String,
    context: android.content.Context,
): String {
    return try {
        val instant = Instant.parse(loggedAt)
        val local = instant.atZone(ZoneId.systemDefault())
        val pattern = if (DateFormat.is24HourFormat(context)) "HH:mm" else "h:mm a"
        local.format(DateTimeFormatter.ofPattern(pattern, Locale.getDefault()))
    } catch (exc: Exception) {
        ""
    }
}

@Composable
private fun MealTypeEmptyState(
    mealType: String,
    modifier: Modifier = Modifier,
) {
    Box(modifier = modifier, contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Olli(size = OlliSize.Done)
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text =
                    stringResource(
                        R.string.meal_type_empty,
                        stringResource(mealTypeLabelRes(mealType)).lowercase(Locale.getDefault()),
                    ),
                style = MealsyType.body,
                color = MealsyTheme.colors.muted,
            )
        }
    }
}

private fun mealTypeLabelRes(mealType: String): Int =
    when (mealType) {
        "breakfast" -> R.string.home_meal_breakfast
        "lunch" -> R.string.home_meal_lunch
        "dinner" -> R.string.home_meal_dinner
        else -> R.string.home_meal_snack
    }
