package app.mealsy.android.ui.journey

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.android.ui.common.ErrorKind
import app.mealsy.data.repo.DayPoint
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.data.repo.NutrientsRepository
import app.mealsy.data.repo.TrendsRepository
import app.mealsy.domain.MicroSummary
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.io.IOException
import java.time.Clock
import java.time.LocalDate
import javax.inject.Inject

/** Journey's micronutrient section, which loads independently of the macros. */
sealed interface JourneyMicros {
    data class Loaded(val summary: MicroSummary) : JourneyMicros

    /** Nothing logged in the range. */
    data object Empty : JourneyMicros

    /** The nutrients endpoints failed (e.g. a server without spec 008 yet); the rest of Journey still shows. */
    data object Unavailable : JourneyMicros
}

sealed interface JourneyContent {
    data object Loading : JourneyContent

    data class Error(val kind: ErrorKind) : JourneyContent

    /**
     * @param days Logged days in the range (the backend omits the rest).
     * @param today The range's last day, for the chart's column labels.
     * @param refreshing A range switch is refetching; this stale content stays up.
     */
    data class Loaded(
        val days: List<DayPoint>,
        val today: LocalDate,
        val kcalGoal: Double?,
        val proteinGoal: Double?,
        val micros: JourneyMicros,
        val refreshing: Boolean = false,
    ) : JourneyContent
}

data class JourneyUiState(
    val range: JourneyRange = JourneyRange.Week,
    val content: JourneyContent = JourneyContent.Loading,
)

/**
 * Drives the Journey tab: macros from `GET /meals/trends`, targets from
 * `GET /goals` and the micronutrient summary from [NutrientsRepository], all
 * fetched in parallel for the selected [JourneyRange]. Weight and glucose are
 * placeholders on the screen until the backend tracks them.
 *
 * Goals and micronutrients are optional: if either fails the screen still
 * shows the macros, without a target line or with the micronutrient section
 * marked unavailable. Only a trends failure is a screen-level error.
 */
@HiltViewModel
class JourneyViewModel
    @Inject
    constructor(
        private val trendsRepository: TrendsRepository,
        private val goalsRepository: GoalsRepository,
        private val nutrientsRepository: NutrientsRepository,
        private val clock: Clock,
    ) : ViewModel() {
        private val _uiState = MutableStateFlow(JourneyUiState())
        val uiState: StateFlow<JourneyUiState> = _uiState.asStateFlow()

        private var loadJob: Job? = null

        /** Exposed only so tests can join the first load. */
        val readyJob: Job = load()

        /** Switches the range and refetches; null (a no-op) if [range] is already selected. */
        fun setRange(range: JourneyRange): Job? {
            if (range == _uiState.value.range) return null
            _uiState.update { it.copy(range = range) }
            return load()
        }

        fun retry(): Job = load()

        private fun load(): Job {
            loadJob?.cancel()
            val range = _uiState.value.range
            _uiState.update { state ->
                val stale = state.content as? JourneyContent.Loaded
                state.copy(content = stale?.copy(refreshing = true) ?: JourneyContent.Loading)
            }
            return viewModelScope.launch {
                val content =
                    try {
                        fetch(range)
                    } catch (exc: CancellationException) {
                        throw exc
                    } catch (exc: IOException) {
                        Log.w(TAG, "Journey load failed (offline?) for $range", exc)
                        JourneyContent.Error(ErrorKind.Offline)
                    } catch (exc: Exception) {
                        Log.e(TAG, "Journey load failed for $range", exc)
                        JourneyContent.Error(ErrorKind.LoadFailed)
                    }
                _uiState.update { it.copy(content = content) }
            }.also { loadJob = it }
        }

        private suspend fun fetch(range: JourneyRange): JourneyContent.Loaded =
            coroutineScope {
                val trends = async { trendsRepository.trends(range.days) }
                val goals = async { optional("goals") { goalsRepository.get() } }
                val micros =
                    async {
                        optional("micronutrients") { nutrientsRepository.summary(range.days) }
                            .let { result ->
                                when {
                                    result.isFailure -> JourneyMicros.Unavailable
                                    result.getOrNull() == null -> JourneyMicros.Empty
                                    else -> JourneyMicros.Loaded(result.getOrThrow()!!)
                                }
                            }
                    }
                val g = goals.await().getOrNull()
                JourneyContent.Loaded(
                    days = trends.await().days,
                    today = LocalDate.now(clock),
                    kcalGoal = g?.kcalGoal,
                    proteinGoal = g?.proteinGoal,
                    micros = micros.await(),
                )
            }

        /** Runs an optional fetch; a failure is logged and returned, not thrown. */
        private suspend fun <T> optional(
            what: String,
            block: suspend () -> T,
        ): Result<T> =
            try {
                Result.success(block())
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                Log.w(TAG, "Journey: $what unavailable", exc)
                Result.failure(exc)
            }

        private companion object {
            const val TAG = "Journey"
        }
    }
