package app.mealsy.android.ui.mymeals

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.data.repo.MyMealsRepository
import app.mealsy.data.repo.SavedMeal
import dagger.hilt.android.lifecycle.HiltViewModel
import java.io.IOException
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

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
 * Quick-logging a meal only calls `POST /my-meals/{id}/log` — it does not
 * itself refresh [app.mealsy.android.ui.chat.ChatViewModel]'s today header,
 * since that state lives on a different, already-alive `ChatViewModel`
 * instance (Hilt scopes both to the nav graph, not to each other). The
 * simplest correct wiring: [quickLog] returns a [Deferred] the screen awaits
 * before popping back to chat, and `ChatScreen` refreshes its own today
 * header on `ON_RESUME` (see `ChatScreen.kt`) — returning from this screen
 * always triggers that resume, so the header is current by the time the
 * user sees it again without this ViewModel needing to know `ChatViewModel`
 * exists.
 */
@HiltViewModel
class MyMealsViewModel @Inject constructor(
    private val repository: MyMealsRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow<MyMealsUiState>(MyMealsUiState.Loading)
    val uiState: StateFlow<MyMealsUiState> = _uiState.asStateFlow()

    /** Ids swiped for delete but still inside the undo window — hidden from the list immediately. */
    private val _hiddenIds = MutableStateFlow<Set<String>>(emptySet())
    val hiddenIds: StateFlow<Set<String>> = _hiddenIds.asStateFlow()

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
     * [undoWindowMs]. If [undoDelete] is called for the same [id] first, the
     * scheduled delete is cancelled and the meal reappears.
     */
    fun deleteWithUndo(id: String) {
        _hiddenIds.value = _hiddenIds.value + id
        pendingDeleteJobs[id] = viewModelScope.launch {
            delay(undoWindowMs)
            try {
                repository.delete(id)
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                // Best-effort: the meal stays hidden client-side either way; a
                // failed delete just means it reappears on the next [load].
            }
            pendingDeleteJobs.remove(id)
            val current = _uiState.value
            if (current is MyMealsUiState.Loaded) {
                val remaining = current.meals.filterNot { it.id == id }
                _uiState.value = if (remaining.isEmpty()) MyMealsUiState.Empty else MyMealsUiState.Loaded(remaining)
            }
        }
    }

    /** Cancels [id]'s pending delete (if the undo window hasn't elapsed) and un-hides it. */
    fun undoDelete(id: String) {
        pendingDeleteJobs.remove(id)?.cancel()
        _hiddenIds.value = _hiddenIds.value - id
    }
}
