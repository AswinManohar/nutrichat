package app.mealsy.android.ui.home

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.android.design.components.TagTone
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TodayResponse
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.data.repo.ProfileStore
import app.mealsy.data.repo.TodayRefreshSignal
import app.mealsy.domain.Goals
import app.mealsy.domain.ProteinFood
import app.mealsy.domain.ProteinGapDayPart
import app.mealsy.domain.ProteinGapSuggestion
import app.mealsy.domain.proteinGapSuggestion
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.io.IOException
import java.text.NumberFormat
import java.time.Clock
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale
import javax.inject.Inject
import kotlin.math.roundToInt

/** Which third of the day the device clock currently falls in, for greeting and coach-note copy. */
enum class DayPart { Morning, Afternoon, Evening }

/** Hour boundaries for [DayPart]: `< MORNING_END` is [DayPart.Morning], `< AFTERNOON_END` is [DayPart.Afternoon]. */
private const val MORNING_END_HOUR = 12
private const val AFTERNOON_END_HOUR = 17

/** Logcat tag for [HomeViewModel]'s non-network load failures. */
private const val TAG = "HomeViewModel"

/**
 * A resolved coach-note variant for Home's [app.mealsy.android.design.components.CoachNote].
 *
 * Kept as semantic data (day part, rounded numbers) rather than resolved
 * text, so [HomeScreen] — not this view model — owns the translatable copy
 * in `strings.xml` (mirrors [app.mealsy.android.ui.onboarding.ContinueLabel]).
 */
sealed interface HomeCoachNote {
    /**
     * The user is short of their protein goal by [gapG] grams, and [food] plausibly closes it
     * (see [app.mealsy.domain.proteinGapSuggestion] — only offered for small gaps, respecting prefs).
     */
    data class ProteinGapSingleFood(val gapG: Int, val food: ProteinFood) : HomeCoachNote

    /** The user is short of their protein goal by [gapG] grams, too large for one food to close. */
    data class ProteinGapSpread(val gapG: Int) : HomeCoachNote

    /** [kcal] calories remain under the daily calorie goal. */
    data class KcalRemaining(val kcal: Int) : HomeCoachNote

    /** The calorie goal has been met or exceeded and there is no protein gap. */
    data object TargetReached : HomeCoachNote

    /** Mindful tracking mode (no numeric targets) — [nMeals] logged so far today. */
    data class Mindful(val nMeals: Int) : HomeCoachNote
}

/**
 * One row in Home's "Today's meals" list.
 *
 * @param mealType The wire meal-type key ("breakfast"|"lunch"|"dinner"|"snack"), used both to
 *   resolve the row's localized label in [HomeScreen] and as the argument to `onOpenMealType`.
 * @param tone Which pastel tone fills the row's leading icon circle.
 * @param count The matching `TodayResponse.byType[].nMeals`, or `null` when that meal type has not
 *   been logged yet (absent from `byType`, or present with `nMeals == 0`) — renders "not yet".
 */
data class HomeMealRow(val mealType: String, val tone: TagTone, val count: Int?)

/**
 * The resolved variant for Home's status pill "state" text (the pill's
 * trailing label, e.g. "560 left"), kept as semantic data — day-part-free,
 * unlike [HomeCoachNote], but still just a formatted-number wrapper rather
 * than resolved text — so [HomeScreen] owns the translatable copy in
 * `strings.xml` (mirrors [HomeCoachNote]).
 */
sealed interface HomeKcalState {
    /** [kcal] calories remain under the daily calorie goal (already formatted, e.g. "560"). */
    data class Left(val kcal: String) : HomeKcalState

    /** The daily calorie goal has been exceeded by [kcal] calories (already formatted, absolute value). */
    data class Over(val kcal: String) : HomeKcalState

    /** Mindful tracking mode (no numeric calorie target). */
    data object NoTarget : HomeKcalState
}

/** The fixed, always-present meal types shown on Home, in display order with their pastel tones. */
private val MEAL_ROW_ORDER: List<Pair<String, TagTone>> =
    listOf(
        "breakfast" to TagTone.Butter,
        "lunch" to TagTone.Leaf,
        "dinner" to TagTone.Pink,
        "snack" to TagTone.Powder,
    )

/**
 * UI state for the Home dashboard. All prose-bearing fields are either
 * pre-formatted numbers/dates (not translatable) or semantic values
 * ([dayPart], [coachNote], [HomeMealRow.mealType]) that [HomeScreen] resolves
 * against `strings.xml` — this view model never holds a hardcoded string.
 */
data class HomeUiState(
    val loading: Boolean = true,
    val error: Boolean = false,
    val refreshing: Boolean = false,
    val dateLabel: String = "",
    val dayPart: DayPart = DayPart.Afternoon,
    val firstName: String? = null,
    val mindful: Boolean = false,
    val eatenKcal: String = "",
    val kcalState: HomeKcalState = HomeKcalState.NoTarget,
    val eatenFraction: Float = 0f,
    val proteinValue: String = "",
    val carbsValue: String = "",
    val fatValue: String = "",
    val meals: List<HomeMealRow> = emptyList(),
    val coachNote: HomeCoachNote? = null,
)

/**
 * Loads and formats the Home dashboard: today's totals, the active goal,
 * and the cached profile, then derives the status pill, macro tiles, meal
 * rows and coach note from them.
 *
 * [clock] is injected (rather than reading `System.currentTimeMillis()`
 * directly) so tests can pin the day part deterministically; production
 * binds a real [Clock.systemDefaultZone] in `AppModule`.
 */
@HiltViewModel
class HomeViewModel
    @Inject
    constructor(
        private val api: MealsyApi,
        private val goalsRepository: GoalsRepository,
        private val profileStore: ProfileStore,
        private val todayRefreshSignal: TodayRefreshSignal,
        private val clock: Clock,
    ) : ViewModel() {
        private val _uiState = MutableStateFlow(HomeUiState())
        val uiState: StateFlow<HomeUiState> = _uiState.asStateFlow()

        init {
            load(showLoading = true)
            viewModelScope.launch {
                todayRefreshSignal.events.collect { load(showLoading = false) }
            }
        }

        /** User-initiated refresh (pull-to-refresh) — drives [HomeUiState.refreshing], not [HomeUiState.loading]. */
        fun refresh() {
            viewModelScope.launch {
                _uiState.update { it.copy(refreshing = true) }
                loadOnce()
                _uiState.update { it.copy(refreshing = false) }
            }
        }

        /** Re-runs the load after [HomeUiState.error], with the full-screen loading placeholder. */
        fun retry() {
            load(showLoading = true)
        }

        private fun load(showLoading: Boolean) {
            viewModelScope.launch {
                if (showLoading) _uiState.update { it.copy(loading = true, error = false) }
                loadOnce()
            }
        }

        private suspend fun loadOnce() {
            try {
                val (today, goals, profile) =
                    coroutineScope {
                        val todayDeferred = async { api.today() }
                        val goalsDeferred = async { goalsRepository.get() }
                        val profileDeferred = async { profileStore.get() }
                        Triple(todayDeferred.await(), goalsDeferred.await(), profileDeferred.await())
                    }
                _uiState.value = buildState(today, goals, profile?.firstName)
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: IOException) {
                _uiState.update { it.copy(loading = false, refreshing = false, error = true) }
            } catch (exc: Exception) {
                // Non-network failure (e.g. a non-404 HTTP error from goals()) — log what it
                // was rather than swallowing it silently, then surface the same error state.
                Log.w(TAG, "loadOnce failed: ${exc::class.simpleName}: ${exc.message}")
                _uiState.update { it.copy(loading = false, refreshing = false, error = true) }
            }
        }

        private fun buildState(
            today: TodayResponse,
            goals: Goals?,
            firstName: String?,
        ): HomeUiState {
            val mindful = goals == null || goals.trackingMode == "mindful" || goals.kcalGoal == null
            val kcalGoal = goals?.kcalGoal
            val dayPart = dayPartOf(LocalDateTime.now(clock).hour)
            val kcalFormat = NumberFormat.getIntegerInstance()

            val eatenFraction =
                if (mindful || kcalGoal == null || kcalGoal <= 0.0) {
                    0f
                } else {
                    (today.kcal / kcalGoal).toFloat().coerceIn(0f, 1f)
                }

            val kcalState =
                if (mindful || kcalGoal == null) {
                    HomeKcalState.NoTarget
                } else {
                    val remaining = kcalGoal - today.kcal
                    if (remaining >= 0) {
                        HomeKcalState.Left(kcalFormat.format(remaining.roundToInt()))
                    } else {
                        HomeKcalState.Over(kcalFormat.format(-remaining.roundToInt()))
                    }
                }

            val meals =
                MEAL_ROW_ORDER.map { (mealType, tone) ->
                    val byType = today.byType.find { it.mealType == mealType }
                    val count = byType?.nMeals?.takeIf { it > 0 }
                    HomeMealRow(mealType = mealType, tone = tone, count = count)
                }

            val proteinGoal = goals?.proteinGoal
            val proteinGapG = proteinGoal?.let { (it - today.proteinG).roundToInt() }
            val kcalRemainingRounded = kcalGoal?.let { (it - today.kcal).roundToInt() }
            val proteinGapSuggestion =
                proteinGapG?.let {
                    proteinGapSuggestion(
                        gapG = it,
                        mealsLoggedToday = today.nMeals,
                        dayPart = dayPart.toProteinGapDayPart(),
                        dietaryPrefs = goals?.dietaryPrefs ?: emptyMap(),
                    )
                }
            val coachNote: HomeCoachNote =
                when {
                    mindful -> HomeCoachNote.Mindful(nMeals = today.nMeals)
                    proteinGapSuggestion is ProteinGapSuggestion.SingleFood ->
                        HomeCoachNote.ProteinGapSingleFood(
                            gapG = proteinGapSuggestion.gapG,
                            food = proteinGapSuggestion.food,
                        )
                    proteinGapSuggestion is ProteinGapSuggestion.Spread ->
                        HomeCoachNote.ProteinGapSpread(gapG = proteinGapSuggestion.gapG)
                    kcalRemainingRounded != null && kcalRemainingRounded > 0 ->
                        HomeCoachNote.KcalRemaining(kcal = kcalRemainingRounded)
                    else -> HomeCoachNote.TargetReached
                }

            return HomeUiState(
                loading = false,
                error = false,
                refreshing = false,
                dateLabel =
                    DateTimeFormatter.ofPattern("EEEE, MMM d", Locale.getDefault())
                        .format(LocalDateTime.now(clock))
                        .uppercase(Locale.getDefault()),
                dayPart = dayPart,
                firstName = firstName?.trim()?.takeIf { it.isNotBlank() },
                mindful = mindful,
                eatenKcal = kcalFormat.format(today.kcal.roundToInt()),
                kcalState = kcalState,
                eatenFraction = eatenFraction,
                proteinValue = "${today.proteinG.roundToInt()}g",
                carbsValue = "${today.carbsG.roundToInt()}g",
                fatValue = "${today.fatG.roundToInt()}g",
                meals = meals,
                coachNote = coachNote,
            )
        }

        private fun dayPartOf(hour: Int): DayPart =
            when {
                hour < MORNING_END_HOUR -> DayPart.Morning
                hour < AFTERNOON_END_HOUR -> DayPart.Afternoon
                else -> DayPart.Evening
            }

        private fun DayPart.toProteinGapDayPart(): ProteinGapDayPart =
            when (this) {
                DayPart.Morning -> ProteinGapDayPart.Morning
                DayPart.Afternoon -> ProteinGapDayPart.Afternoon
                DayPart.Evening -> ProteinGapDayPart.Evening
            }
    }
