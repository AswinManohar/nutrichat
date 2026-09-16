package app.mealsy.android.ui.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.R
import app.mealsy.android.design.components.CircleIconButton
import app.mealsy.android.design.components.CoachNote
import app.mealsy.android.design.components.Eyebrow
import app.mealsy.android.design.components.InsetDivider
import app.mealsy.android.design.components.ListContainer
import app.mealsy.android.design.components.ListRow
import app.mealsy.android.design.components.MetricCard
import app.mealsy.android.design.components.PastelIconCircle
import app.mealsy.android.design.components.StatusPill
import app.mealsy.android.design.components.StatusPillAwareness
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.design.theme.mealsyScreenPadding
import app.mealsy.android.ui.common.ErrorState
import app.mealsy.android.ui.common.LoadingState

/**
 * The Home dashboard: today's status pill, macro tiles, meal list and
 * coach note.
 *
 * Refreshes silently on `ON_RESUME` (e.g. returning here after logging a
 * meal from chat or My Meals) via [HomeViewModel.refresh], mirroring
 * `ChatScreen`'s `ON_RESUME` pattern, and wraps [HomeContent] in an
 * [PullToRefreshBox] for a manual pull gesture.
 *
 * @param onOpenSettings Navigates to the Settings screen (the header's gear button).
 * @param onOpenMealType Navigates to a meal-type's detail, given its wire key
 *   ("breakfast"|"lunch"|"dinner"|"snack").
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    onOpenSettings: () -> Unit,
    onOpenMealType: (String) -> Unit,
    viewModel: HomeViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) viewModel.refresh()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    PullToRefreshBox(
        isRefreshing = state.refreshing,
        onRefresh = viewModel::refresh,
        modifier = Modifier.fillMaxSize(),
    ) {
        HomeContent(
            state = state,
            onOpenSettings = onOpenSettings,
            onOpenMealType = onOpenMealType,
            onRetry = viewModel::retry,
            modifier = Modifier.fillMaxSize(),
        )
    }
}

/**
 * The Home dashboard's content, with no pull-to-refresh wrapper, so
 * screenshot goldens render it directly and deterministically from a
 * hand-built [HomeUiState].
 */
@Composable
internal fun HomeContent(
    state: HomeUiState,
    onOpenSettings: () -> Unit,
    onOpenMealType: (String) -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    when {
        state.loading -> LoadingState(message = stringResource(R.string.home_loading), modifier = modifier)
        state.error -> ErrorState(message = stringResource(R.string.home_error), onRetry = onRetry, modifier = modifier)
        else -> HomeLoaded(state, onOpenSettings, onOpenMealType, modifier)
    }
}

@Composable
private fun HomeLoaded(
    state: HomeUiState,
    onOpenSettings: () -> Unit,
    onOpenMealType: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .verticalScroll(rememberScrollState())
            .mealsyScreenPadding(),
    ) {
        Row(verticalAlignment = Alignment.Top) {
            Column(modifier = Modifier.weight(1f)) {
                Eyebrow(text = state.dateLabel)
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = greetingFor(state.dayPart, state.firstName),
                    style = MealsyType.display,
                    color = MealsyTheme.colors.ink,
                    modifier = Modifier.widthIn(max = 260.dp),
                )
            }
            CircleIconButton(
                icon = MealsyIcons.Gear,
                contentDescription = stringResource(R.string.home_settings),
                onClick = onOpenSettings,
            )
        }

        Spacer(modifier = Modifier.height(44.dp))

        val eatenLabel = stringResource(R.string.home_eaten_label, state.eatenKcal)
        val stateLabel = kcalStateText(state.kcalState)
        if (state.mindful) {
            StatusPillAwareness(eatenLabel = eatenLabel, stateLabel = stateLabel)
        } else {
            StatusPill(
                eatenLabel = eatenLabel,
                stateLabel = stateLabel,
                eatenFraction = state.eatenFraction,
            )
        }

        Spacer(modifier = Modifier.height(18.dp))

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            MetricCard(
                label = stringResource(R.string.home_metric_protein),
                value = state.proteinValue,
                modifier = Modifier.weight(1f),
            )
            MetricCard(
                label = stringResource(R.string.home_metric_carbs),
                value = state.carbsValue,
                modifier = Modifier.weight(1f),
            )
            MetricCard(
                label = stringResource(R.string.home_metric_fat),
                value = state.fatValue,
                modifier = Modifier.weight(1f),
            )
        }

        Spacer(modifier = Modifier.height(28.dp))

        Text(
            text = stringResource(R.string.home_todays_meals),
            style = MealsyType.section,
            color = MealsyTheme.colors.ink,
        )

        Spacer(modifier = Modifier.height(12.dp))

        ListContainer {
            state.meals.forEachIndexed { index, row ->
                ListRow(
                    label = stringResource(mealTypeLabelRes(row.mealType)),
                    onClick = { onOpenMealType(row.mealType) },
                    leading = { PastelIconCircle(icon = MealsyIcons.Bowl, tone = row.tone, contentDescription = null) },
                    badgeCount = row.count,
                    trailingText = if (row.count == null) stringResource(R.string.home_meal_not_yet) else null,
                )
                if (index != state.meals.lastIndex) InsetDivider()
            }
        }

        Spacer(modifier = Modifier.height(20.dp))

        state.coachNote?.let { note ->
            CoachNote(text = coachNoteText(note))
        }
    }
}

/** Resolves the greeting bucket to localized text; no name -> the bare bucket greeting, no comma. */
@Composable
private fun greetingFor(dayPart: DayPart, firstName: String?): String {
    return if (firstName.isNullOrBlank()) {
        stringResource(
            when (dayPart) {
                DayPart.Morning -> R.string.home_greeting_morning
                DayPart.Afternoon -> R.string.home_greeting_afternoon
                DayPart.Evening -> R.string.home_greeting_evening
            },
        )
    } else {
        stringResource(
            when (dayPart) {
                DayPart.Morning -> R.string.home_greeting_morning_named
                DayPart.Afternoon -> R.string.home_greeting_afternoon_named
                DayPart.Evening -> R.string.home_greeting_evening_named
            },
            firstName,
        )
    }
}

/** Resolves the status pill's trailing state text against `strings.xml`. */
@Composable
private fun kcalStateText(state: HomeKcalState): String = when (state) {
    is HomeKcalState.Left -> stringResource(R.string.home_state_left, state.kcal)
    is HomeKcalState.Over -> stringResource(R.string.home_state_over, state.kcal)
    HomeKcalState.NoTarget -> stringResource(R.string.home_state_no_target)
}

private fun mealTypeLabelRes(mealType: String): Int = when (mealType) {
    "breakfast" -> R.string.home_meal_breakfast
    "lunch" -> R.string.home_meal_lunch
    "dinner" -> R.string.home_meal_dinner
    else -> R.string.home_meal_snack
}

@Composable
private fun coachNoteText(note: HomeCoachNote): String = when (note) {
    is HomeCoachNote.ProteinGap -> stringResource(
        when (note.dayPart) {
            DayPart.Morning -> R.string.home_coach_protein_gap_morning
            DayPart.Afternoon -> R.string.home_coach_protein_gap_afternoon
            DayPart.Evening -> R.string.home_coach_protein_gap_evening
        },
        note.gapG,
    )
    is HomeCoachNote.KcalRemaining -> stringResource(R.string.home_coach_kcal_remaining, note.kcal)
    is HomeCoachNote.TargetReached -> stringResource(R.string.home_coach_target_reached)
    is HomeCoachNote.Mindful -> stringResource(R.string.home_coach_mindful, note.nMeals)
}
