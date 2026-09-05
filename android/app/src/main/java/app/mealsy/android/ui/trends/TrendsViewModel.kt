package app.mealsy.android.ui.trends

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.data.repo.CategorySlice
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.data.repo.TrendData
import app.mealsy.data.repo.TrendsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import java.io.IOException
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** Number of days covered by the trends window, toggled via the 7/30-day segmented control. */
enum class TrendsWindow(val days: Int) {
    WEEK(7),
    MONTH(30),
}

/** Rendering state for [TrendsScreen]. */
sealed interface TrendsUiState {
    data object Loading : TrendsUiState
    data object Empty : TrendsUiState
    data class Error(val message: String) : TrendsUiState
    data class Loaded(
        val trends: TrendData,
        val categories: List<CategorySlice>,
        val proteinGoal: Double?,
    ) : TrendsUiState
}

/**
 * Drives the trends screen: fetches `GET /meals/trends` + `GET /meals/categories`
 * for the selected [TrendsWindow] via [TrendsRepository], plus the protein goal
 * (for the chart's reference line) via [GoalsRepository].
 *
 * Both trends endpoints return a bare, possibly-empty JSON array on a day/window
 * with nothing logged — that maps to [TrendsUiState.Empty], not an error.
 */
@HiltViewModel
class TrendsViewModel @Inject constructor(
    private val trendsRepository: TrendsRepository,
    private val goalsRepository: GoalsRepository,
) : ViewModel() {

    private val _window = MutableStateFlow(TrendsWindow.WEEK)
    val window: StateFlow<TrendsWindow> = _window.asStateFlow()

    private val _uiState = MutableStateFlow<TrendsUiState>(TrendsUiState.Loading)
    val uiState: StateFlow<TrendsUiState> = _uiState.asStateFlow()

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

    private fun load(selected: TrendsWindow): Job {
        _uiState.value = TrendsUiState.Loading
        return viewModelScope.launch {
            try {
                val trends = trendsRepository.trends(selected.days)
                val categories = trendsRepository.categories(selected.days)
                val proteinGoal = try {
                    goalsRepository.get()?.proteinGoal
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: Exception) {
                    null
                }
                _uiState.value = if (trends.days.isEmpty() && categories.isEmpty()) {
                    TrendsUiState.Empty
                } else {
                    TrendsUiState.Loaded(trends, categories, proteinGoal)
                }
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: IOException) {
                _uiState.value = TrendsUiState.Error("Couldn't reach Mealsy. Check your connection.")
            } catch (exc: Exception) {
                _uiState.value = TrendsUiState.Error("Something went wrong loading trends.")
            }
        }
    }
}
