package app.mealsy.android.ui.chat

import android.graphics.Bitmap
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.android.util.ConnectivityObserver
import app.mealsy.data.api.GoalsResponse
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TodayResponse
import app.mealsy.data.image.ImageEncoder
import app.mealsy.data.repo.ChatRepository
import app.mealsy.data.repo.LogOutcome
import app.mealsy.data.repo.TurnResult
import app.mealsy.domain.CardEditor
import app.mealsy.domain.ConfirmationCard
import dagger.hilt.android.lifecycle.HiltViewModel
import java.io.IOException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject
import retrofit2.HttpException

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
    private val connectivity: ConnectivityObserver,
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

    init {
        // Primary offline signal: with no pending card there may be no
        // in-flight network call left to ever clear a stale `_offline=true`
        // (e.g. connectivity drops with nothing queued), so connectivity
        // changes must be able to both set AND clear the banner, or the
        // chat input stays locked out until the process restarts. The
        // request-driven sets elsewhere (send/confirm/cancel/startup)
        // remain a secondary signal — they fire immediately on a call's
        // actual outcome without waiting for the OS to notice.
        viewModelScope.launch {
            connectivity.isOnline.collect { online -> _offline.value = !online }
        }
    }

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
        } catch (exc: IOException) {
            _offline.value = true
        } catch (exc: Exception) {
            // HttpException or anything else on startup recovery isn't fatal
            // and there's no chat transcript yet to report it into.
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
            } catch (exc: IOException) {
                _offline.value = true
                appendAssistant("Couldn't reach Mealsy. Check your connection and try again.")
            } catch (exc: HttpException) {
                appendAssistant(httpErrorMessage(exc))
            } catch (exc: Exception) {
                appendAssistant("Something went wrong. Try again.")
            } finally {
                _sending.value = false
            }
        }
    }

    /**
     * Sends a captured meal photo as a new turn: encodes [bitmap] via
     * [ImageEncoder], appends a "[photo]" user bubble, then handles the
     * result exactly like [send]. Returns the underlying [Job] purely so
     * tests can [Job.join] it.
     */
    fun sendPhoto(bitmap: Bitmap): Job {
        _messages.value = _messages.value + ChatMsg.User("[photo]")
        _sending.value = true
        return viewModelScope.launch {
            try {
                val imageB64 = ImageEncoder.encode(bitmap)
                when (val result = repository.sendTurn("", imageB64 = imageB64)) {
                    is TurnResult.Reply -> appendAssistant(result.message)
                    is TurnResult.Card -> _pendingCard.value = result.card
                    is TurnResult.UpgradeRequired -> appendAssistant(result.message)
                }
                _offline.value = false
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: IOException) {
                _offline.value = true
                appendAssistant("Couldn't reach Mealsy. Check your connection and try again.")
            } catch (exc: HttpException) {
                appendAssistant(httpErrorMessage(exc))
            } catch (exc: Exception) {
                appendAssistant("Something went wrong. Try again.")
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
                when (val outcome = repository.confirmCard(card)) {
                    is LogOutcome.Logged -> {
                        _pendingCard.value = null
                        appendAssistant(outcome.message)
                        _offline.value = false
                        refreshToday()
                    }
                    is LogOutcome.Queued -> {
                        _pendingCard.value = null
                        _offline.value = true
                        appendAssistant("Saved — will sync when you're back online")
                    }
                }
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: IOException) {
                _offline.value = true
                appendAssistant("Couldn't log that — check your connection and try again.")
            } catch (exc: HttpException) {
                appendAssistant(httpErrorMessage(exc))
            } catch (exc: Exception) {
                appendAssistant("Something went wrong. Try again.")
            } finally {
                _sending.value = false
            }
        }
    }

    /** Cancels the pending card. The card is only cleared once cancellation actually succeeds. */
    fun cancel(): Job? {
        if (_pendingCard.value == null) return null
        _sending.value = true
        return viewModelScope.launch {
            try {
                when (val result = repository.cancelCard()) {
                    is TurnResult.Reply -> {
                        _pendingCard.value = null
                        appendAssistant(result.message)
                    }
                    is TurnResult.Card -> _pendingCard.value = result.card
                    is TurnResult.UpgradeRequired -> {
                        _pendingCard.value = null
                        appendAssistant(result.message)
                    }
                }
                _offline.value = false
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: IOException) {
                // Leave the card in place — the server's confirmation thread
                // is still paused, and losing it here strands that thread.
                _offline.value = true
                appendAssistant("Couldn't cancel — check your connection and try again.")
            } catch (exc: HttpException) {
                appendAssistant(httpErrorMessage(exc))
            } catch (exc: Exception) {
                appendAssistant("Something went wrong. Try again.")
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

    /** A 429 gets its own copy; every other server error is a generic retry prompt. */
    private fun httpErrorMessage(exc: HttpException): String = if (exc.code() == 429) {
        "Slow down a moment and try again."
    } else {
        "Something went wrong on our end. Try again shortly."
    }

    private fun appendAssistant(text: String) {
        _messages.value = _messages.value + ChatMsg.Assistant(text)
    }
}
