package app.mealsy.android.ui.meals

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.android.di.ApplicationScope
import app.mealsy.android.ui.common.ErrorKind
import app.mealsy.data.repo.LoggedMeal
import app.mealsy.data.repo.MealsRepository
import app.mealsy.data.repo.TodayRefreshSignal
import dagger.hilt.android.lifecycle.HiltViewModel
import java.io.IOException
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * How long a swiped-away meal stays hidden-but-recoverable before
 * [MealTypeListViewModel.deleteWithUndo] actually calls `DELETE
 * /meals/log/{meal_id}`. `internal var` (not `private val`) so tests can
 * shrink it, mirroring [app.mealsy.android.ui.mymeals.undoWindowMs].
 */
internal var mealTypeUndoWindowMs: Long = 4_000L

/** Rendering state for [MealTypeListScreen]. */
sealed interface MealTypeListUiState {
    data object Loading : MealTypeListUiState
    data object Empty : MealTypeListUiState
    data class Error(val kind: ErrorKind) : MealTypeListUiState
    data class Loaded(val meals: List<LoggedMeal>) : MealTypeListUiState
}

/**
 * Drives the meal-type list screen (e.g. "Lunch"): today's logged meals for
 * one meal type, refreshed on [TodayRefreshSignal], with swipe-to-delete and
 * a 4s undo window.
 *
 * This deliberately mirrors [app.mealsy.android.ui.mymeals.MyMealsViewModel]'s
 * `deleteWithUndo`/`undoDelete`/`onCleared` logic verbatim rather than
 * extracting a shared controller — see that class's doc comment for the
 * race-guard reasoning ([appScope] vs. `viewModelScope`, why the delayed
 * delete must survive this ViewModel being cleared, and why leaving the
 * screen commits any pending delete immediately). Keeping two copies avoids
 * risking a behavior change to `MyMealsViewModel`, which this task must not
 * touch.
 */
@HiltViewModel
class MealTypeListViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val repository: MealsRepository,
    private val todayRefreshSignal: TodayRefreshSignal,
    @ApplicationScope private val appScope: CoroutineScope,
) : ViewModel() {

    /** The wire meal-type key this screen lists, e.g. "lunch". */
    val mealType: String = checkNotNull(savedStateHandle["mealType"]) {
        "MealTypeListViewModel requires a mealType nav arg"
    }

    private val _uiState = MutableStateFlow<MealTypeListUiState>(MealTypeListUiState.Loading)
    val uiState: StateFlow<MealTypeListUiState> = _uiState.asStateFlow()

    /** Ids swiped for delete but still inside the undo window — hidden from the list immediately. */
    private val _hiddenIds = MutableStateFlow<Set<String>>(emptySet())
    val hiddenIds: StateFlow<Set<String>> = _hiddenIds.asStateFlow()

    private val pendingDeleteJobs = mutableMapOf<String, Job>()

    /** Exposed only so tests can [Job.join] the initial load deterministically. */
    val readyJob: Job = load()

    init {
        viewModelScope.launch {
            todayRefreshSignal.events.collect { load() }
        }
    }

    /** Re-runs the list load — used by the error state's retry button and after [TodayRefreshSignal]. */
    fun load(): Job {
        _uiState.value = MealTypeListUiState.Loading
        return viewModelScope.launch {
            try {
                val meals = repository.listForDay(mealType = mealType)
                _uiState.value =
                    if (meals.isEmpty()) MealTypeListUiState.Empty else MealTypeListUiState.Loaded(meals)
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: IOException) {
                _uiState.value = MealTypeListUiState.Error(ErrorKind.Offline)
            } catch (exc: Exception) {
                _uiState.value = MealTypeListUiState.Error(ErrorKind.LoadFailed)
            }
        }
    }

    /**
     * Hides [id] immediately and schedules the real `DELETE` after
     * [mealTypeUndoWindowMs], on [appScope] so it survives this `ViewModel`
     * being cleared. See [app.mealsy.android.ui.mymeals.MyMealsViewModel.deleteWithUndo].
     */
    fun deleteWithUndo(id: String) {
        pendingDeleteJobs.remove(id)?.cancel()
        _hiddenIds.value = _hiddenIds.value + id
        pendingDeleteJobs[id] = appScope.launch {
            delay(mealTypeUndoWindowMs)
            commitDelete(id)
        }
    }

    /** Cancels [id]'s pending delete (if the undo window hasn't elapsed) and un-hides it. */
    fun undoDelete(id: String) {
        pendingDeleteJobs.remove(id)?.cancel()
        _hiddenIds.value = _hiddenIds.value - id
    }

    /** See [app.mealsy.android.ui.mymeals.MyMealsViewModel.onCleared]. */
    override fun onCleared() {
        super.onCleared()
        val ids = pendingDeleteJobs.keys.toList()
        for (id in ids) {
            pendingDeleteJobs.remove(id)?.cancel()
            appScope.launch { commitDelete(id) }
        }
    }

    /** See [app.mealsy.android.ui.mymeals.MyMealsViewModel.commitDelete]. */
    private suspend fun commitDelete(id: String) {
        try {
            repository.delete(id)
        } catch (exc: CancellationException) {
            throw exc
        } catch (exc: Exception) {
            // Best-effort: the meal stays hidden client-side either way; a
            // failed delete just means it reappears on the next [load].
        }
        withContext(Dispatchers.Main.immediate) {
            pendingDeleteJobs.remove(id)
            val current = _uiState.value
            if (current is MealTypeListUiState.Loaded) {
                val remaining = current.meals.filterNot { it.mealId == id }
                _uiState.value = if (remaining.isEmpty()) {
                    MealTypeListUiState.Empty
                } else {
                    MealTypeListUiState.Loaded(remaining)
                }
            }
        }
    }
}
