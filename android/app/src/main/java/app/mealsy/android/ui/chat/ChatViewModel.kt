package app.mealsy.android.ui.chat

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.data.api.GoalsResponse
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TodayResponse
import app.mealsy.data.repo.ChatRepository
import app.mealsy.data.repo.TurnResult
import app.mealsy.domain.CardEditor
import app.mealsy.domain.ConfirmationCard
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

/** A single line in the chat transcript. */
sealed interface ChatMsg {
    data class User(val text: String) : ChatMsg
    data class Assistant(val text: String) : ChatMsg
}

/**
 * Drives the chat screen: sending turns through [ChatRepository], editing
 * and confirming the resulting [ConfirmationCard], and keeping the today
 * header's totals/goals fresh.
 *
 * [MealsyApi] is injected directly (alongside [ChatRepository]) purely to
 * back the today header's `GET /meals/today` / `GET /goals` reads — those
 * aren't part of the confirmation-flow contract [ChatRepository] owns.
 */
@HiltViewModel
class ChatViewModel @Inject constructor(
    private val repository: ChatRepository,
    private val api: MealsyApi,
) : ViewModel() {

    private val _messages = MutableStateFlow<List<ChatMsg>>(emptyList())
    val messages: StateFlow<List<ChatMsg>> = _messages.asStateFlow()

    private val _pendingCard = MutableStateFlow<ConfirmationCard?>(null)
    val pendingCard: StateFlow<ConfirmationCard?> = _pendingCard.asStateFlow()

    private val _sending = MutableStateFlow(false)
    val sending: StateFlow<Boolean> = _sending.asStateFlow()

    private val _offline = MutableStateFlow(false)
    val offline: StateFlow<Boolean> = _offline.asStateFlow()

    private val _today = MutableStateFlow<TodayResponse?>(null)
    val today: StateFlow<TodayResponse?> = _today.asStateFlow()

    private val _goals = MutableStateFlow<GoalsResponse?>(null)
    val goals: StateFlow<GoalsResponse?> = _goals.asStateFlow()

    /**
     * The startup job that recovers a pending card and loads the today
     * header. Exposed only so tests can [Job.join] it deterministically —
     * production callers don't need to await it, the UI just observes the
     * resulting state flows.
     */
    val readyJob: Job = viewModelScope.launch {
        try {
            _pendingCard.value = repository.recoverPending()
            _offline.value = false
        } catch (exc: CancellationException) {
            throw exc
        } catch (exc: Exception) {
            _offline.value = true
        }
        refreshToday()
    }

    /**
     * Sends [text] as a new turn: appends a user bubble, then handles the
     * result. Returns the underlying [Job] purely so tests can [Job.join] it.
     */
    fun send(text: String): Job {
        _messages.value = _messages.value + ChatMsg.User(text)
        _sending.value = true
        return viewModelScope.launch {
            try {
                when (val result = repository.sendTurn(text)) {
                    is TurnResult.Reply -> appendAssistant(result.message)
                    is TurnResult.Card -> _pendingCard.value = result.card
                    is TurnResult.UpgradeRequired -> appendAssistant(result.message)
                }
                _offline.value = false
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                _offline.value = true
                appendAssistant("Couldn't reach Mealsy. Check your connection and try again.")
            } finally {
                _sending.value = false
            }
        }
    }

    /**
     * Edits the pending card's item at [index] to [newQtyG]. A no-op (rather
     * than a crash) if [index] is stale — e.g. a double-tap race with
     * [removeItem] — since [CardEditor.editQty] throws on an out-of-range
     * index.
     */
    fun editQty(index: Int, newQtyG: Double) {
        val card = _pendingCard.value ?: return
        if (index !in card.items.indices) return
        if (newQtyG <= 0) return
        _pendingCard.value = CardEditor.editQty(card, index, newQtyG)
    }

    /** Removes the pending card's item at [index]; a no-op if [index] is stale. */
    fun removeItem(index: Int) {
        val card = _pendingCard.value ?: return
        if (index !in card.items.indices) return
        _pendingCard.value = CardEditor.removeItem(card, index)
    }

    /** Sets the pending card's meal type (breakfast/lunch/snack/dinner). */
    fun setMealType(mealType: String) {
        _pendingCard.value = _pendingCard.value?.copy(mealType = mealType)
    }

    /** Sets the pending card's overall portion multiplier. */
    fun setPortion(portion: Double) {
        val card = _pendingCard.value ?: return
        _pendingCard.value = CardEditor.setPortion(card, portion)
    }

    /** Confirms the pending card. Leaves it in place (for retry) on failure. */
    fun confirm(): Job? {
        val card = _pendingCard.value ?: return null
        _sending.value = true
        return viewModelScope.launch {
            try {
                val outcome = repository.confirmCard(card)
                _pendingCard.value = null
                appendAssistant(outcome.message)
                _offline.value = false
                refreshToday()
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                _offline.value = true
                appendAssistant("Couldn't log that — check your connection and try again.")
            } finally {
                _sending.value = false
            }
        }
    }

    /** Cancels the pending card. */
    fun cancel(): Job? {
        if (_pendingCard.value == null) return null
        _sending.value = true
        return viewModelScope.launch {
            try {
                _pendingCard.value = null
                when (val result = repository.cancelCard()) {
                    is TurnResult.Reply -> appendAssistant(result.message)
                    is TurnResult.Card -> _pendingCard.value = result.card
                    is TurnResult.UpgradeRequired -> appendAssistant(result.message)
                }
                _offline.value = false
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                _offline.value = true
            } finally {
                _sending.value = false
            }
        }
    }

    private suspend fun refreshToday() {
        try {
            _today.value = api.today()
            _goals.value = api.goals()
        } catch (exc: CancellationException) {
            throw exc
        } catch (exc: Exception) {
            // Today header just stays stale/empty; not fatal to the chat flow.
        }
    }

    private fun appendAssistant(text: String) {
        _messages.value = _messages.value + ChatMsg.Assistant(text)
    }
}
