package app.mealsy.android.ui.mymeals

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.android.di.ApplicationScope
import app.mealsy.data.repo.MyMealsRepository
import app.mealsy.data.repo.SavedMeal
import dagger.hilt.android.lifecycle.HiltViewModel
import java.io.IOException
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Job
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * How long a swiped-away meal stays hidden-but-recoverable before
 * [MyMealsViewModel.deleteWithUndo] actually calls `DELETE /my-meals/{id}` —
 * the standard "undo snackbar" pattern (the delete is delayed, not the UI
 * removal). `internal var` rather than a `private val` purely so tests can
 * shrink it instead of sleeping ~4s real time per test (this file's tests
 * all run on [kotlinx.coroutines.Dispatchers.Unconfined] against a real
 * [okhttp3.mockwebserver.MockWebServer], per [app.mealsy.android.ui.chat.ChatViewModelTest]'s
 * convention, so a virtual-time `TestDispatcher` isn't an option here).
 */
internal var undoWindowMs: Long = 4_000L

/** Rendering state for [MyMealsScreen]. */
sealed interface MyMealsUiState {
    data object Loading : MyMealsUiState
    data object Empty : MyMealsUiState
    data class Error(val message: String) : MyMealsUiState
    data class Loaded(val meals: List<SavedMeal>) : MyMealsUiState
}

/**
 * Drives the My Meals screen: listing saved meals, quick-logging one, and
 * swipe-to-delete with an undo window.
 *
 * Quick-logging a meal only calls `POST /my-meals/{id}/log` and emits
 * `TodayRefreshSignal.notifyLogged()` (from within [MyMealsRepository]) — it
 * does not itself refresh any other screen's state directly. [quickLog]
 * returns a [Deferred] the screen awaits before popping back (to Home, per
 * the current nav graph); Home observes `TodayRefreshSignal` and refreshes
 * on `ON_RESUME`, so its totals are current by the time the user sees it
 * again without this ViewModel needing to know about any other screen.
 *
 * [deleteWithUndo]'s delayed `DELETE` deliberately runs on [appScope], not
 * `viewModelScope`: this `ViewModel` is scoped to the My Meals back-stack
 * entry, so `viewModelScope` is cancelled the instant the user pops back to
 * chat (e.g. right after a quick-log) — before the undo window elapses. That
 * would silently cancel the coroutine and drop the delete, leaving the
 * "deleted" meal to reappear on the next [load]. [onCleared] additionally
 * flushes any still-pending delete immediately rather than leaving it to run
 * out its window on [appScope] unattended — leaving the screen is treated as
 * an implicit "commit" of the delete, same as closing the undo snackbar.
 */
@HiltViewModel
class MyMealsViewModel @Inject constructor(
    private val repository: MyMealsRepository,
    @ApplicationScope private val appScope: CoroutineScope,
) : ViewModel() {

    private val _uiState = MutableStateFlow<MyMealsUiState>(MyMealsUiState.Loading)
    val uiState: StateFlow<MyMealsUiState> = _uiState.asStateFlow()

    /** Ids swiped for delete but still inside the undo window — hidden from the list immediately. */
    private val _hiddenIds = MutableStateFlow<Set<String>>(emptySet())
    val hiddenIds: StateFlow<Set<String>> = _hiddenIds.asStateFlow()

    /**
     * Ids whose delayed `DELETE` hasn't fired yet — i.e. still genuinely
     * undoable. The screen drives its undo toast's visibility off this
     * (rather than running its own independent timer) so the toast can
     * never outlive, or disappear before, this `ViewModel`'s actual undo
     * window: see [deleteWithUndo]/[undoDelete]/[commitDelete].
     */
    private val _pendingUndoIds = MutableStateFlow<Set<String>>(emptySet())
    val pendingUndoIds: StateFlow<Set<String>> = _pendingUndoIds.asStateFlow()

    private val pendingDeleteJobs = mutableMapOf<String, Job>()

    /** Exposed only so tests can [Job.join] the initial load deterministically. */
    val readyJob: Job = load()

    /** Re-runs the list load — used by the error state's retry button and after a save-from-chat. */
    fun load(): Job {
        _uiState.value = MyMealsUiState.Loading
        return viewModelScope.launch {
            try {
                val meals = repository.list()
                _uiState.value = if (meals.isEmpty()) MyMealsUiState.Empty else MyMealsUiState.Loaded(meals)
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: IOException) {
                _uiState.value = MyMealsUiState.Error("Couldn't reach Mealsy. Check your connection.")
            } catch (exc: Exception) {
                _uiState.value = MyMealsUiState.Error("Something went wrong loading your meals.")
            }
        }
    }

    /**
     * Quick-logs saved meal [id] at [mealType]. Returns a [Deferred] of
     * whether it succeeded — the screen awaits this before navigating back
     * to chat so a failure can show an error instead of silently popping.
     */
    fun quickLog(id: String, mealType: String): Deferred<Boolean> = viewModelScope.async {
        try {
            repository.quickLog(id, mealType)
            true
        } catch (exc: CancellationException) {
            throw exc
        } catch (exc: Exception) {
            false
        }
    }

    /**
     * Hides [id] immediately and schedules the real `DELETE` after
     * [undoWindowMs], on [appScope] so it survives this `ViewModel` being
     * cleared. If [undoDelete] is called for the same [id] first, the
     * scheduled delete is cancelled and the meal reappears. Calling this
     * again for an [id] that already has a pending delete cancels the first
     * job before scheduling a fresh one, rather than racing two deletes.
     */
    fun deleteWithUndo(id: String) {
        pendingDeleteJobs.remove(id)?.cancel()
        _hiddenIds.value = _hiddenIds.value + id
        _pendingUndoIds.value = _pendingUndoIds.value + id
        pendingDeleteJobs[id] = appScope.launch {
            delay(undoWindowMs)
            commitDelete(id)
        }
    }

    /** Cancels [id]'s pending delete (if the undo window hasn't elapsed) and un-hides it. */
    fun undoDelete(id: String) {
        pendingDeleteJobs.remove(id)?.cancel()
        _hiddenIds.value = _hiddenIds.value - id
        _pendingUndoIds.value = _pendingUndoIds.value - id
    }

    /**
     * Leaving the screen commits any pending deletes immediately instead of
     * leaving them to run out their window unattended on [appScope] — same
     * intent as the undo window elapsing normally, just without the wait.
     * The delete itself still runs on [appScope] (not the now-cancelled
     * `viewModelScope`) so it isn't dropped by this very `onCleared` call.
     */
    override fun onCleared() {
        super.onCleared()
        val ids = pendingDeleteJobs.keys.toList()
        for (id in ids) {
            pendingDeleteJobs.remove(id)?.cancel()
            appScope.launch { commitDelete(id) }
        }
    }

    /**
     * Calls `DELETE /my-meals/{id}` and removes [id] from a currently-
     * [MyMealsUiState.Loaded] list.
     *
     * The network call runs on whatever dispatcher the caller launched this
     * on ([appScope]'s `Dispatchers.Default`), but [pendingDeleteJobs],
     * [_uiState], and [_hiddenIds] are all plain, unsynchronized mutable
     * state that [deleteWithUndo]/[undoDelete]/[onCleared] also touch from
     * the main thread — mutating them from a background worker here would be
     * an unguarded data race (a lost `pendingDeleteJobs` removal, or a
     * clobbered `Loaded` list read-modify-write). `withContext(Dispatchers.Main.immediate)`
     * hops every bit of that bookkeeping back onto main, leaving only the
     * actual HTTP call on the worker.
     */
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
            _pendingUndoIds.value = _pendingUndoIds.value - id
            val current = _uiState.value
            if (current is MyMealsUiState.Loaded) {
                val remaining = current.meals.filterNot { it.id == id }
                _uiState.value =
                    if (remaining.isEmpty()) MyMealsUiState.Empty else MyMealsUiState.Loaded(remaining)
            }
        }
    }
}
