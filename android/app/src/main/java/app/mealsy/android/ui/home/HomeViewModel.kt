package app.mealsy.android.ui.home

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.android.data.TodayRepository
import app.mealsy.android.design.components.TagTone
import app.mealsy.data.api.TodayResponse
import app.mealsy.data.repo.DayPoint
import app.mealsy.data.repo.ProfileStore
import app.mealsy.data.repo.TodayRefreshSignal
import app.mealsy.data.repo.TrendsRepository
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
import java.time.LocalDate
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

/** Days in Home's "This week" grid, ending today. */
private const val WEEK_DAYS = 7

/** A week-grid macro below this share of its goal renders as a dashed "under goal" cell. */
private const val WEEK_LOW_FRACTION = 0.7

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

/**
 * One macro cell in Home's "This week" grid.
 *
 * @param grams The day's total, rounded.
 * @param low `true` when [grams] is under [WEEK_LOW_FRACTION] of the user's goal for this macro —
 *   renders as the dashed outline. Always `false` for a macro with no goal (carbs, or mindful mode).
 */
data class HomeWeekCell(val grams: Int, val low: Boolean)

/**
 * One column (day) in Home's "This week" grid.
 *
 * @param weekday The short localized weekday ("Tue"); [HomeScreen] shows "Today" instead when [isToday].
 * @param kcal The day's formatted kcal total, or `null` when nothing was logged that day — the
 *   column then renders empty dashed cells.
 * @param kcalThousands The same total in thousands to one decimal ("2.0"), shown instead of [kcal]
 *   when a large font scale makes the full number overflow its column.
 */
data class HomeWeekDay(
    val weekday: String,
    val isToday: Boolean,
    val kcal: String?,
    val kcalThousands: String? = null,
    val protein: HomeWeekCell?,
    val fiber: HomeWeekCell?,
    val carbs: HomeWeekCell?,
)

/**
 * Home's "This week" grid: the last [WEEK_DAYS] days, oldest first, ending today.
 *
 * @param startLabel The first day, formatted ("Sep 10"), for the "Sep 10 – today" range label.
 * @param showsGoalLegend Whether any cell can be judged against a goal, so the
 *   "Under 70% of goal" legend entry is meaningful.
 */
data class HomeWeek(
    val startLabel: String,
    val days: List<HomeWeekDay>,
    val showsGoalLegend: Boolean,
)

/**
 * Builds [HomeWeek] from `GET /meals/trends` points. The backend omits days with
 * no meals, so every day in the window is filled in here (as the Trends screen's
 * `buildTrendsDayBars` does) to keep weekday columns aligned.
 *
 * @param days The trends points for the window; dates are ISO `yyyy-MM-dd`.
 * @param goals The active goal, or `null` when the user has none.
 * @param mindful Mindful tracking mode: no cell is judged against a goal.
 * @param today The last day of the window.
 * @param locale Formats weekdays, the range start and kcal totals.
 */
internal fun buildHomeWeek(
    days: List<DayPoint>,
    goals: Goals?,
    mindful: Boolean,
    today: LocalDate,
    locale: Locale = Locale.getDefault(),
): HomeWeek {
    val byDate =
        days.mapNotNull { point ->
            runCatching { LocalDate.parse(point.date) }.getOrNull()?.let { it to point }
        }.toMap()
    val proteinGoal = goals?.proteinGoal.takeUnless { mindful }
    val fiberGoal = goals?.fiberGoal.takeUnless { mindful }
    val kcalFormat = NumberFormat.getIntegerInstance(locale)
    val thousandsFormat =
        NumberFormat.getNumberInstance(locale).apply {
            minimumFractionDigits = 1
            maximumFractionDigits = 1
        }
    val weekdayFormat = DateTimeFormatter.ofPattern("EEE", locale)
    val start = today.minusDays((WEEK_DAYS - 1).toLong())
    return HomeWeek(
        startLabel = DateTimeFormatter.ofPattern("MMM d", locale).format(start),
        days =
            (0 until WEEK_DAYS).map { offset ->
                val date = start.plusDays(offset.toLong())
                val point = byDate[date]
                HomeWeekDay(
                    weekday = weekdayFormat.format(date),
                    isToday = date == today,
                    kcal = point?.let { kcalFormat.format(it.kcal.roundToInt()) },
                    kcalThousands = point?.let { thousandsFormat.format(it.kcal / 1000) },
                    protein = point?.let { weekCell(it.proteinG, proteinGoal) },
                    fiber = point?.let { weekCell(it.fiberG, fiberGoal) },
                    carbs = point?.let { weekCell(it.carbsG, goal = null) },
                )
            },
        showsGoalLegend = (proteinGoal ?: 0.0) > 0.0 || (fiberGoal ?: 0.0) > 0.0,
    )
}

private fun weekCell(
    grams: Double,
    goal: Double?,
): HomeWeekCell =
    HomeWeekCell(
        grams = grams.roundToInt(),
        low = goal != null && goal > 0.0 && grams / goal < WEEK_LOW_FRACTION,
    )

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
    val week: HomeWeek? = null,
    val weekUnavailable: Boolean = false,
)

/**
 * Loads and formats the Home dashboard: today's totals, the active goal,
 * the cached profile and the last week's trends, then derives the status
 * pill, macro tiles, meal rows, coach note and week grid from them.
 *
 * [clock] is injected (rather than reading `System.currentTimeMillis()`
 * directly) so tests can pin the day part deterministically; production
 * binds a real [Clock.systemDefaultZone] in `AppModule`.
 */
@HiltViewModel
class HomeViewModel
    @Inject
    constructor(
        private val todayRepository: TodayRepository,
        private val profileStore: ProfileStore,
        private val todayRefreshSignal: TodayRefreshSignal,
        private val trendsRepository: TrendsRepository,
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
                // #49 item 4: routed through the shared TodayRepository (rather than
                // calling the API/GoalsRepository directly) so a redundant concurrent
                // load — e.g. this init load racing HomeScreen's synthetic ON_RESUME —
                // joins the same in-flight request instead of duplicating it.
                val (snapshot, profile, weekDays) =
                    coroutineScope {
                        val snapshotDeferred = async { todayRepository.get() }
                        val profileDeferred = async { profileStore.get() }
                        val weekDeferred = async { loadWeekDays() }
                        Triple(snapshotDeferred.await(), profileDeferred.await(), weekDeferred.await())
                    }
                _uiState.value = buildState(snapshot.today, snapshot.goals, profile?.firstName, weekDays)
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

        /**
         * The week grid's trends points, or `null` when the fetch fails. A failure here
         * leaves the rest of Home usable: the grid shows its own error text instead.
         */
        private suspend fun loadWeekDays(): List<DayPoint>? =
            try {
                trendsRepository.trends(WEEK_DAYS).days
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                Log.w(TAG, "week trends failed: ${exc::class.simpleName}: ${exc.message}")
                null
            }

        private fun buildState(
            today: TodayResponse,
            goals: Goals?,
            firstName: String?,
            weekDays: List<DayPoint>?,
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
                week = weekDays?.let { buildHomeWeek(it, goals, mindful, LocalDate.now(clock)) },
                weekUnavailable = weekDays == null,
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
