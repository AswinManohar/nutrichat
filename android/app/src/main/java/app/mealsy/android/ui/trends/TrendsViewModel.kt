package app.mealsy.android.ui.trends

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.android.ui.common.ErrorKind
import app.mealsy.data.repo.CategorySlice
import app.mealsy.data.repo.DayPoint
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.data.repo.TrendData
import app.mealsy.data.repo.TrendsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.io.IOException
import javax.inject.Inject
import kotlin.math.roundToInt

/** Number of days covered by the trends window, toggled via the 7/30-day segmented control. */
enum class TrendsWindow(val days: Int) {
    WEEK(7),
    MONTH(30),
}

/** Rendering state for [TrendsScreen]. */
sealed interface TrendsUiState {
    data object Loading : TrendsUiState

    data object Empty : TrendsUiState

    data class Error(val kind: ErrorKind) : TrendsUiState

    /**
     * @param proteinGoal The protein daily goal, for the protein chart's dashed reference line.
     * @param kcalGoal The kcal daily goal, for the kcal chart's dashed reference line.
     * @param avgKcal The average kcal across [averageKcal] — days *with data* only (see kdoc).
     * @param avgProteinG The average protein grams across [averageProteinG] — same rule.
     * @param daysLoggedCount How many days in the window have at least one logged meal
     *   ([trends]`.days` already omits no-meal days, so this is just its size).
     * @param daysInWindow The window's total day count (the "Days logged" denominator).
     * @param refreshing Set while a Week/Month toggle is refetching this window's data.
     *   The screen keeps rendering this (stale) [Loaded] content — segmented control
     *   included — instead of blanking to [Loading], so only the very first load
     *   ever shows the full-screen loading state.
     */
    data class Loaded(
        val trends: TrendData,
        val categories: List<CategorySlice>,
        val proteinGoal: Double?,
        val kcalGoal: Double? = null,
        val avgKcal: Int = averageKcal(trends.days),
        val avgProteinG: Int = averageProteinG(trends.days),
        val daysLoggedCount: Int = trends.days.size,
        val daysInWindow: Int = 7,
        val refreshing: Boolean = false,
    ) : TrendsUiState
}

/**
 * Average kcal per logged day.
 *
 * Averages over days *with data* (the backend already omits no-meal days
 * from [DayPoint] lists), not over the full window length — a 30-day window
 * with 5 logged days reports the average of those 5 days, not a total
 * diluted by 25 empty days. Returns `0` for an empty list (no division by
 * zero).
 */
internal fun averageKcal(days: List<DayPoint>): Int = if (days.isEmpty()) 0 else (days.sumOf { it.kcal } / days.size).roundToInt()

/** Average protein grams per logged day. Same "days with data" rule as [averageKcal]. */
internal fun averageProteinG(days: List<DayPoint>): Int = if (days.isEmpty()) 0 else (days.sumOf { it.proteinG } / days.size).roundToInt()

/**
 * Drives the trends screen: fetches `GET /meals/trends` + `GET /meals/categories`
 * for the selected [TrendsWindow] via [TrendsRepository], plus the protein goal
 * (for the chart's reference line) via [GoalsRepository].
 *
 * Both trends endpoints return a bare, possibly-empty JSON array on a day/window
 * with nothing logged — that maps to [TrendsUiState.Empty], not an error.
 */
@HiltViewModel
class TrendsViewModel
    @Inject
    constructor(
        private val trendsRepository: TrendsRepository,
        private val goalsRepository: GoalsRepository,
    ) : ViewModel() {
        private val _window = MutableStateFlow(TrendsWindow.WEEK)
        val window: StateFlow<TrendsWindow> = _window.asStateFlow()

        private val _uiState = MutableStateFlow<TrendsUiState>(TrendsUiState.Loading)
        val uiState: StateFlow<TrendsUiState> = _uiState.asStateFlow()

        /**
         * Per-window [TrendsUiState.Loaded] cache, populated after each successful
         * load. Lets a Week/Month toggle show the target window's own last-known
         * content (rather than the window being left behind) while it refetches.
         */
        private val loadedCache = mutableMapOf<TrendsWindow, TrendsUiState.Loaded>()

        /** Exposed only so tests can [Job.join] the load deterministically. */
        val readyJob: Job = load(_window.value)

        /** Switches the trends window and refetches; a no-op if [newWindow] is already selected. */
        fun setWindow(newWindow: TrendsWindow): Job? {
            if (newWindow == _window.value) return null
            _window.value = newWindow
            return load(newWindow)
        }

        /** Re-runs the load for the current window — used by the error state's retry button. */
        fun retry(): Job = load(_window.value)

        /**
         * Loads [selected]'s trends/categories/goals.
         *
         * Stale-while-revalidate: if there is any prior [TrendsUiState.Loaded] to
         * show for [selected] (its own cache entry, or else whatever is currently
         * on screen), that content stays up with [TrendsUiState.Loaded.refreshing]
         * set instead of the screen dropping to [TrendsUiState.Loading]. Only a
         * truly cold start — nothing loaded yet, for any window — shows [TrendsUiState.Loading].
         */
        private fun load(selected: TrendsWindow): Job {
            val staleForSelected = loadedCache[selected] ?: (_uiState.value as? TrendsUiState.Loaded)
            _uiState.value = staleForSelected?.copy(refreshing = true) ?: TrendsUiState.Loading
            return viewModelScope.launch {
                try {
                    val trends = trendsRepository.trends(selected.days)
                    val categories = trendsRepository.categories(selected.days)
                    val goals =
                        try {
                            goalsRepository.get()
                        } catch (exc: CancellationException) {
                            throw exc
                        } catch (exc: Exception) {
                            null
                        }
                    _uiState.value =
                        if (trends.days.isEmpty() && categories.isEmpty()) {
                            loadedCache.remove(selected)
                            TrendsUiState.Empty
                        } else {
                            TrendsUiState.Loaded(
                                trends = trends,
                                categories = categories,
                                proteinGoal = goals?.proteinGoal,
                                kcalGoal = goals?.kcalGoal,
                                daysInWindow = selected.days,
                                refreshing = false,
                            ).also { loadedCache[selected] = it }
                        }
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: IOException) {
                    _uiState.value = TrendsUiState.Error(ErrorKind.Offline)
                } catch (exc: Exception) {
                    _uiState.value = TrendsUiState.Error(ErrorKind.LoadFailed)
                }
            }
        }
    }
