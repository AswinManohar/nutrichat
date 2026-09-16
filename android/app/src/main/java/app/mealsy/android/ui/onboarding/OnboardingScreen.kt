package app.mealsy.android.ui.onboarding

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.max
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.R
import app.mealsy.android.design.components.CircleIconButton
import app.mealsy.android.design.components.CoachNote
import app.mealsy.android.design.components.DecorativeDots
import app.mealsy.android.design.components.MealsyButton
import app.mealsy.android.design.components.MealsyButtonStyle
import app.mealsy.android.design.components.MealsyProgressBar
import app.mealsy.android.design.components.MealsySlider
import app.mealsy.android.design.components.OliveSquiggle
import app.mealsy.android.design.components.OutlinePill
import app.mealsy.android.design.components.PastelIconCircle
import app.mealsy.android.design.components.FilterChipPill
import app.mealsy.android.design.components.PillInput
import app.mealsy.android.design.components.SelectableCard
import app.mealsy.android.design.components.SpeechBubble
import app.mealsy.android.design.components.TagTone
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.mascot.Olli
import app.mealsy.android.design.mascot.OlliSize
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * Hilt/state entry point for the six-state onboarding flow. Collects
 * [OnboardingViewModel.uiState], fires [onDone] once the flow finishes, and
 * delegates all rendering to the stateless [OnboardingContent] so screenshot
 * tests can exercise the UI without a Hilt graph.
 */
@Composable
fun OnboardingScreen(
    onDone: () -> Unit,
    onNavigateToLogin: () -> Unit,
    viewModel: OnboardingViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()

    LaunchedEffect(uiState.done) {
        if (uiState.done) onDone()
    }

    OnboardingContent(
        state = uiState,
        onName = viewModel::setName,
        onSelectGoal = viewModel::selectGoal,
        onTogglePref = viewModel::togglePref,
        onKcalTarget = viewModel::setKcalTarget,
        onNext = viewModel::next,
        onBack = viewModel::back,
        onRetry = viewModel::retry,
        onNavigateToLogin = onNavigateToLogin,
    )
}

/**
 * The six designed onboarding states (welcome, name, goal, preferences,
 * target, done), stateless and Hilt-free so Roborazzi goldens can render it
 * directly against hand-built [OnboardingUiState] values.
 *
 * @param animate Whether the progress bar animates its width and Olli bobs.
 *   Set `false` in screenshot tests for deterministic frames.
 */
@Composable
fun OnboardingContent(
    state: OnboardingUiState,
    onName: (String) -> Unit,
    onSelectGoal: (OnboardingGoal) -> Unit,
    onTogglePref: (DietaryPref) -> Unit,
    onKcalTarget: (Int) -> Unit,
    onNext: () -> Unit,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    onNavigateToLogin: () -> Unit,
    modifier: Modifier = Modifier,
    animate: Boolean = true,
) {
    val colors = MealsyTheme.colors
    val statusBarTop = WindowInsets.statusBars.asPaddingValues().calculateTopPadding()

    Surface(modifier = modifier.fillMaxSize(), color = colors.canvas) {
        when (state.step) {
            0 -> WelcomeStep(
                statusBarTop = statusBarTop,
                animate = animate,
                onGetStarted = onNext,
                onNavigateToLogin = onNavigateToLogin,
            )
            5 -> DoneStep(state = state, animate = animate, onRetry = onRetry)
            else -> StepScaffold(
                state = state,
                statusBarTop = statusBarTop,
                onBack = onBack,
                onNext = onNext,
                animate = animate,
            ) {
                when (state.step) {
                    1 -> NameStep(state = state, onName = onName)
                    2 -> GoalStep(state = state, onSelectGoal = onSelectGoal)
                    3 -> PrefsStep(state = state, onTogglePref = onTogglePref)
                    4 -> TargetStep(state = state, onKcalTarget = onKcalTarget)
                }
            }
        }
    }
}

// --- Step 0: Welcome ---------------------------------------------------

@Composable
private fun WelcomeStep(
    statusBarTop: androidx.compose.ui.unit.Dp,
    animate: Boolean,
    onGetStarted: () -> Unit,
    onNavigateToLogin: () -> Unit,
) {
    val colors = MealsyTheme.colors
    val topPadding = max(64.dp, statusBarTop + 16.dp)

    Box(modifier = Modifier.fillMaxSize()) {
        DecorativeDots(modifier = Modifier.fillMaxSize())

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(top = topPadding, start = 24.dp, end = 24.dp, bottom = 28.dp),
        ) {
            Text(
                text = stringResource(R.string.onboarding_welcome_hero).uppercase(),
                style = MealsyType.hero,
                color = colors.ink,
            )
            OliveSquiggle(modifier = Modifier.padding(top = 14.dp))

            Box(modifier = Modifier.weight(1f).fillMaxWidth()) {
                Olli(
                    modifier = Modifier.align(Alignment.BottomCenter),
                    size = OlliSize.Welcome,
                    bob = animate,
                )
                SpeechBubble(
                    text = stringResource(R.string.onboarding_welcome_speech_bubble).uppercase(),
                    modifier = Modifier
                        .align(Alignment.TopStart)
                        .padding(start = 173.dp, top = 0.dp),
                )
            }

            OutlinePill(
                text = stringResource(R.string.onboarding_welcome_pill).uppercase(),
                modifier = Modifier
                    .align(Alignment.CenterHorizontally)
                    .padding(top = 18.dp, bottom = 10.dp),
            )

            MealsyButton(
                text = stringResource(R.string.onboarding_welcome_get_started),
                onClick = onGetStarted,
                modifier = Modifier.fillMaxWidth(),
                style = MealsyButtonStyle.Primary,
            )
            Spacer(modifier = Modifier.height(10.dp))
            MealsyButton(
                text = stringResource(R.string.onboarding_welcome_have_account),
                onClick = onNavigateToLogin,
                modifier = Modifier.fillMaxWidth(),
                style = MealsyButtonStyle.Secondary,
            )
        }
    }
}

// --- Steps 1-4 shared chrome --------------------------------------------

@Composable
private fun StepScaffold(
    state: OnboardingUiState,
    statusBarTop: androidx.compose.ui.unit.Dp,
    onBack: () -> Unit,
    onNext: () -> Unit,
    animate: Boolean,
    content: @Composable () -> Unit,
) {
    val topPadding = max(60.dp, statusBarTop + 16.dp)
    val showBack = state.step != state.startStep
    val backLabel = stringResource(R.string.onboarding_back)
    val stepLabel = stringResource(R.string.onboarding_step_n_of_4, state.step)
    val stepOfLabel = stringResource(R.string.onboarding_step_of_4, state.step)

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(top = topPadding, start = 24.dp, end = 24.dp, bottom = 28.dp),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(14.dp),
            modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp),
        ) {
            if (showBack) {
                CircleIconButton(
                    icon = MealsyIcons.ChevronLeft,
                    contentDescription = backLabel,
                    onClick = onBack,
                    size = 38.dp,
                )
            } else {
                Spacer(modifier = Modifier.width(38.dp))
            }
            MealsyProgressBar(
                progress = state.progress,
                modifier = Modifier.weight(1f),
                animate = animate,
                contentDescription = stepLabel,
            )
            Text(text = stepOfLabel, style = MealsyType.label, color = MealsyTheme.colors.muted)
        }

        Column(modifier = Modifier.weight(1f)) {
            content()
        }

        val buttonLabel = when (state.continueLabel) {
            ContinueLabel.Continue -> stringResource(R.string.onboarding_continue)
            ContinueLabel.NothingToAvoid -> stringResource(R.string.onboarding_nothing_to_avoid)
            ContinueLabel.Finish -> stringResource(R.string.onboarding_finish)
        }
        MealsyButton(
            text = buttonLabel,
            onClick = onNext,
            enabled = state.continueEnabled,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun StepTitle(text: String) {
    Text(
        text = text,
        style = MealsyType.screenTitle,
        color = MealsyTheme.colors.ink,
        modifier = Modifier.padding(top = 28.dp, bottom = 8.dp),
    )
}

@Composable
private fun StepSubtitle(text: String) {
    Text(
        text = text,
        style = MealsyType.body,
        color = MealsyTheme.colors.muted,
        modifier = Modifier.padding(bottom = 24.dp),
    )
}

// --- Step 1: Name ---------------------------------------------------------

@Composable
private fun NameStep(state: OnboardingUiState, onName: (String) -> Unit) {
    Column {
        StepTitle(stringResource(R.string.onboarding_name_title))
        StepSubtitle(stringResource(R.string.onboarding_name_subtitle))
        PillInput(
            value = state.name,
            onValueChange = onName,
            placeholder = stringResource(R.string.onboarding_name_placeholder),
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

// --- Step 2: Goal ----------------------------------------------------------

internal data class GoalCardSpec(
    val goal: OnboardingGoal,
    val tone: TagTone,
    val titleRes: Int,
    val subtitleRes: Int,
)

internal val GOAL_CARD_SPECS = listOf(
    GoalCardSpec(OnboardingGoal.Lose, TagTone.Butter, R.string.onboarding_goal_lose_title, R.string.onboarding_goal_lose_subtitle),
    GoalCardSpec(OnboardingGoal.Maintain, TagTone.Leaf, R.string.onboarding_goal_maintain_title, R.string.onboarding_goal_maintain_subtitle),
    GoalCardSpec(OnboardingGoal.Build, TagTone.Powder, R.string.onboarding_goal_build_title, R.string.onboarding_goal_build_subtitle),
    GoalCardSpec(OnboardingGoal.Learn, TagTone.Pink, R.string.onboarding_goal_learn_title, R.string.onboarding_goal_learn_subtitle),
)

@Composable
private fun GoalStep(state: OnboardingUiState, onSelectGoal: (OnboardingGoal) -> Unit) {
    Column {
        val title = if (state.firstName.isBlank()) {
            stringResource(R.string.onboarding_goal_title_no_name)
        } else {
            stringResource(R.string.onboarding_goal_title, state.firstName)
        }
        StepTitle(title)
        StepSubtitle(stringResource(R.string.onboarding_goal_subtitle))

        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            GOAL_CARD_SPECS.forEach { spec ->
                val title2 = stringResource(spec.titleRes)
                SelectableCard(
                    title = title2,
                    subtitle = stringResource(spec.subtitleRes),
                    selected = state.goal == spec.goal,
                    onClick = { onSelectGoal(spec.goal) },
                    leading = {
                        PastelIconCircle(initial = title2.first(), tone = spec.tone)
                    },
                )
            }
        }
    }
}

// --- Step 3: Preferences ---------------------------------------------------

internal val PREF_LABELS: Map<DietaryPref, Int> = mapOf(
    DietaryPref.Vegetarian to R.string.onboarding_pref_vegetarian,
    DietaryPref.Vegan to R.string.onboarding_pref_vegan,
    DietaryPref.Pescatarian to R.string.onboarding_pref_pescatarian,
    DietaryPref.NoDairy to R.string.onboarding_pref_no_dairy,
    DietaryPref.NoGluten to R.string.onboarding_pref_no_gluten,
    DietaryPref.LowSodium to R.string.onboarding_pref_low_sodium,
    DietaryPref.LowSugar to R.string.onboarding_pref_low_sugar,
    DietaryPref.NoNuts to R.string.onboarding_pref_no_nuts,
)

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun PrefsStep(state: OnboardingUiState, onTogglePref: (DietaryPref) -> Unit) {
    Column {
        StepTitle(stringResource(R.string.onboarding_prefs_title))
        StepSubtitle(stringResource(R.string.onboarding_prefs_subtitle))

        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            DietaryPref.entries.forEach { pref ->
                FilterChipPill(
                    text = stringResource(PREF_LABELS.getValue(pref)),
                    selected = pref in state.prefs,
                    onClick = { onTogglePref(pref) },
                )
            }
        }
    }
}

// --- Step 4: Target ---------------------------------------------------------

@Composable
private fun goalLabel(goal: OnboardingGoal?): String = when (goal) {
    OnboardingGoal.Lose -> stringResource(R.string.onboarding_goal_lose_title)
    OnboardingGoal.Maintain -> stringResource(R.string.onboarding_goal_maintain_title)
    OnboardingGoal.Build -> stringResource(R.string.onboarding_goal_build_title)
    OnboardingGoal.Learn -> stringResource(R.string.onboarding_goal_learn_title)
    null -> ""
}

@Composable
private fun targetWhyCopy(goal: OnboardingGoal?): String = when (goal) {
    OnboardingGoal.Lose -> stringResource(R.string.onboarding_target_why_lose)
    OnboardingGoal.Maintain -> stringResource(R.string.onboarding_target_why_maintain)
    OnboardingGoal.Build -> stringResource(R.string.onboarding_target_why_build)
    OnboardingGoal.Learn -> stringResource(R.string.onboarding_target_why_learn)
    null -> stringResource(R.string.onboarding_target_why_default)
}

@Composable
private fun TargetStep(state: OnboardingUiState, onKcalTarget: (Int) -> Unit) {
    val colors = MealsyTheme.colors

    Column {
        StepTitle(stringResource(R.string.onboarding_target_title))
        StepSubtitle(targetWhyCopy(state.goal))

        Surface(
            color = colors.surface,
            shape = MealsyShapes.card,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(modifier = Modifier.padding(vertical = 20.dp, horizontal = 18.dp)) {
                if (state.isMindful) {
                    Text(
                        text = stringResource(R.string.onboarding_target_mindful_note),
                        style = MealsyType.body,
                        color = colors.muted,
                    )
                } else {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.Bottom,
                    ) {
                        Text(
                            text = stringResource(R.string.onboarding_target_daily_calorie_goal),
                            style = MealsyType.label,
                            color = colors.muted,
                        )
                        Text(
                            text = stringResource(
                                R.string.onboarding_target_kcal_value,
                                "%,d".format(state.kcalTarget),
                            ),
                            style = MealsyType.bigNumberLarge,
                            color = colors.ink,
                        )
                    }

                    MealsySlider(
                        value = state.kcalTarget,
                        onValueChange = onKcalTarget,
                        modifier = Modifier.fillMaxWidth().padding(top = 14.dp),
                        contentDescription = stringResource(R.string.onboarding_target_slider_content_description),
                    )

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text(
                            text = stringResource(R.string.onboarding_target_min_kcal),
                            fontSize = 11.sp,
                            color = colors.inactive,
                        )
                        Text(
                            text = stringResource(R.string.onboarding_target_max_kcal),
                            fontSize = 11.sp,
                            color = colors.inactive,
                        )
                    }
                }
            }
        }

        val coachNoteText = if (state.coachNotePrefs.isEmpty()) {
            stringResource(R.string.onboarding_target_coach_note_default)
        } else {
            val joined = state.coachNotePrefs
                .map { pref -> stringResource(PREF_LABELS.getValue(pref)) }
                .joinToString(" and ") { it.lowercase() }
            if (state.hasMorePrefs) {
                stringResource(R.string.onboarding_target_coach_note_prefs_more, joined)
            } else {
                stringResource(R.string.onboarding_target_coach_note_prefs, joined)
            }
        }
        CoachNote(text = coachNoteText, modifier = Modifier.padding(top = 12.dp))
    }
}

// --- Step 5: Done ---------------------------------------------------------

@Composable
private fun DoneStep(state: OnboardingUiState, animate: Boolean, onRetry: () -> Unit) {
    val colors = MealsyTheme.colors

    Box(modifier = Modifier.fillMaxSize().padding(horizontal = 32.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Olli(size = OlliSize.Done, bob = animate)

            val title = if (state.firstName.isBlank()) {
                stringResource(R.string.onboarding_done_title_no_name)
            } else {
                stringResource(R.string.onboarding_done_title, state.firstName)
            }
            Text(
                text = title,
                style = MealsyType.screenTitle,
                color = colors.ink,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 20.dp, bottom = 10.dp),
            )
            Text(
                text = stringResource(R.string.onboarding_done_subtitle),
                style = MealsyType.body,
                color = colors.muted,
                textAlign = TextAlign.Center,
                modifier = Modifier.widthIn(max = 260.dp),
            )

            Spacer(modifier = Modifier.height(20.dp))

            val pillText = if (state.isMindful) {
                stringResource(R.string.onboarding_done_pill_no_target, goalLabel(state.goal))
            } else {
                stringResource(
                    R.string.onboarding_done_pill,
                    goalLabel(state.goal),
                    "%,d".format(state.kcalTarget),
                )
            }
            Surface(color = colors.olive, shape = MealsyShapes.pill) {
                Text(
                    text = pillText,
                    style = MealsyType.label,
                    color = colors.oliveText,
                    modifier = Modifier.padding(vertical = 12.dp, horizontal = 22.dp),
                )
            }

            if (state.error) {
                Spacer(modifier = Modifier.height(20.dp))
                Text(
                    text = stringResource(R.string.onboarding_done_error),
                    style = MealsyType.body,
                    color = colors.muted,
                    textAlign = TextAlign.Center,
                )
                Spacer(modifier = Modifier.height(10.dp))
                MealsyButton(
                    text = stringResource(R.string.onboarding_done_try_again),
                    onClick = onRetry,
                    style = MealsyButtonStyle.Secondary,
                )
            }
        }
    }
}

