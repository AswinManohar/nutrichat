package app.mealsy.android.ui.micronutrients

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.android.ui.common.ErrorKind
import app.mealsy.data.repo.NutrientsRepository
import app.mealsy.domain.MicroRange
import app.mealsy.domain.MicroSummary
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.io.IOException
import javax.inject.Inject

/** What the body of [MicronutrientsScreen] shows below its pinned header. */
sealed interface MicronutrientsContent {
    data object Loading : MicronutrientsContent

    /** Nothing was logged in the selected range. */
    data object Empty : MicronutrientsContent

    data class Error(val kind: ErrorKind) : MicronutrientsContent

    /** @param refreshing A range switch is refetching; the stale [summary] stays on screen. */
    data class Loaded(val summary: MicroSummary, val refreshing: Boolean = false) : MicronutrientsContent
}

/**
 * @param tabId The selected tab's id, or null for the summary's first tab.
 * @param selectedKey The nutrient whose amounts and sources are open, if any.
 */
data class MicronutrientsUiState(
    val range: MicroRange = MicroRange.Today,
    val tabId: String? = null,
    val selectedKey: String? = null,
    val content: MicronutrientsContent = MicronutrientsContent.Loading,
)

/**
 * Drives the Micronutrients screen (Trends -> Micronutrients): loads the
 * summary for the selected [MicroRange] from [NutrientsRepository] and holds
 * the tab and the tapped nutrient.
 *
 * A range switch keeps the previous range's chart up (dimmed) while it
 * refetches, like Trends' Week/Month toggle, so only the first load blanks.
 */
@HiltViewModel
class MicronutrientsViewModel
    @Inject
    constructor(
        private val repository: NutrientsRepository,
    ) : ViewModel() {
        private val _uiState = MutableStateFlow(MicronutrientsUiState())
        val uiState: StateFlow<MicronutrientsUiState> = _uiState.asStateFlow()

        private var loadJob: Job? = null

        /** Exposed only so tests can join the first load. */
        val readyJob: Job = load()

        /** Switches the range and refetches; null (a no-op) if [range] is already selected. */
        fun setRange(range: MicroRange): Job? {
            if (range == _uiState.value.range) return null
            _uiState.update { it.copy(range = range, selectedKey = null) }
            return load()
        }

        fun setTab(tabId: String) {
            _uiState.update { it.copy(tabId = tabId, selectedKey = null) }
        }

        /** Opens [key]'s amounts and sources, or closes them when it is already open. */
        fun toggleNutrient(key: String) {
            _uiState.update { it.copy(selectedKey = if (it.selectedKey == key) null else key) }
        }

        fun retry(): Job = load()

        private fun load(): Job {
            loadJob?.cancel()
            val range = _uiState.value.range
            _uiState.update { state ->
                val stale = state.content as? MicronutrientsContent.Loaded
                state.copy(content = stale?.copy(refreshing = true) ?: MicronutrientsContent.Loading)
            }
            return viewModelScope.launch {
                val content =
                    try {
                        repository.summary(range.days)?.let { MicronutrientsContent.Loaded(it) }
                            ?: MicronutrientsContent.Empty
                    } catch (exc: CancellationException) {
                        throw exc
                    } catch (exc: IOException) {
                        Log.w(TAG, "Micronutrients load failed (offline?) for $range", exc)
                        MicronutrientsContent.Error(ErrorKind.Offline)
                    } catch (exc: Exception) {
                        Log.e(TAG, "Micronutrients load failed for $range", exc)
                        MicronutrientsContent.Error(ErrorKind.LoadFailed)
                    }
                _uiState.update { it.copy(content = content) }
            }.also { loadJob = it }
        }

        private companion object {
            const val TAG = "Micronutrients"
        }
    }
