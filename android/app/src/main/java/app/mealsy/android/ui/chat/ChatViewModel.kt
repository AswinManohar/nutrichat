package app.mealsy.android.ui.chat

import android.graphics.Bitmap
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.android.util.ConnectivityObserver
import app.mealsy.data.image.ImageEncoder
import app.mealsy.data.offline.DroppedLogStore
import app.mealsy.data.repo.ChatRepository
import app.mealsy.data.repo.LogOutcome
import app.mealsy.data.repo.MyMealsRepository
import app.mealsy.data.repo.TurnResult
import app.mealsy.domain.CardEditor
import app.mealsy.domain.ConfirmationCard
import app.mealsy.domain.FoodNameHumanizer
import app.mealsy.domain.PastelTone
import app.mealsy.domain.defaultMealCategory
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import retrofit2.HttpException
import java.io.IOException
import java.time.Clock
import java.util.UUID
import javax.inject.Inject

/**
 * A tiny pastel macro-metadata tag attached to a coach reply, e.g.
 * `412 kcal` / `28g protein` shown under the message that concluded a log.
 */
data class MacroTag(val text: String, val tone: PastelTone)

/**
 * A single line in the chat transcript.
 *
 * The confirmation card now lives inline as a [Card] entry rather than in a
 * separate `pendingCard` flow, porting `mealStore.ts`'s card lifecycle: only
 * the newest [Card] whose [Card.state] is [CardState.Active]/[CardState.Swapping]
 * is interactive, and every other card is a frozen, collapsed record of what
 * happened to it.
 */
sealed interface ChatMsg {
    val id: String

    /** Epoch millis; the screen formats it as `07:39 PM`. */
    val timestampMillis: Long

    data class User(
        override val id: String,
        override val timestampMillis: Long,
        val text: String,
    ) : ChatMsg

    data class Photo(
        override val id: String,
        override val timestampMillis: Long,
        val bitmap: Bitmap,
    ) : ChatMsg

    data class Coach(
        override val id: String,
        override val timestampMillis: Long,
        val text: String,
        val tags: List<MacroTag> = emptyList(),
        val responseId: String? = null,
        val feedback: Int? = null,
    ) : ChatMsg

    data class UpgradeNotice(
        override val id: String,
        override val timestampMillis: Long,
        val text: String,
    ) : ChatMsg

    data class Card(
        override val id: String,
        override val timestampMillis: Long,
        val card: ConfirmationCard,
        val state: CardState,
    ) : ChatMsg
}

/** The lifecycle state of an inline [ChatMsg.Card], ported from `mealStore.ts`'s `stampResolvedCard`. */
sealed interface CardState {
    /** The newest paused card — fully interactive. */
    data object Active : CardState

    /** A candidate correction turn is in flight for this card. */
    data object Swapping : CardState

    /** The card was confirmed and logged. */
    data class Logged(val label: String, val kcal: Int) : CardState

    /** A newer card superseded this one before it was ever confirmed. */
    data object NotLogged : CardState

    /** The user cancelled this card. */
    data object Discarded : CardState
}

/**
 * Drives the chat screen: sending turns through [ChatRepository], and
 * editing, swapping candidates on, decomposing/combining, and
 * confirming/cancelling the resulting [ConfirmationCard] — all rendered
 * inline in [messages] as [ChatMsg.Card] entries per the ported web card
 * lifecycle (see `frontend/src/stores/mealStore.ts`'s `stampResolvedCard`
 * and `frontend/src/components/chat/ChatThread.tsx`'s collapsed-card
 * strings).
 *
 * Today's totals/goals used to be read here for `ChatScreen`'s now-retired
 * `TodayHeader` (`GET /meals/today` / `GET /goals`); Home owns that display
 * now and refreshes itself via `TodayRefreshSignal`, so this view model no
 * longer needs [app.mealsy.data.api.MealsyApi] at all.
 *
 * @param clock Injected so tests can pin timestamps and [defaultMealCategory].
 *   No Hilt binding for [Clock] exists in this module, so this defaults to
 *   the real system clock rather than adding one.
 */
@HiltViewModel
class ChatViewModel
    @Inject
    constructor(
        private val repository: ChatRepository,
        private val connectivity: ConnectivityObserver,
        private val myMealsRepository: MyMealsRepository,
        private val droppedLogStore: DroppedLogStore,
        private val clock: Clock = Clock.systemDefaultZone(),
    ) : ViewModel() {
        private val _messages = MutableStateFlow<List<ChatMsg>>(emptyList())
        val messages: StateFlow<List<ChatMsg>> = _messages.asStateFlow()

        private val _sending = MutableStateFlow(false)
        val sending: StateFlow<Boolean> = _sending.asStateFlow()

        private val _offline = MutableStateFlow(false)
        val offline: StateFlow<Boolean> = _offline.asStateFlow()

        private val _savingMeal = MutableStateFlow(false)
        val savingMeal: StateFlow<Boolean> = _savingMeal.asStateFlow()

        /** One-shot toast events — `Logged`/save results and other transient copy. */
        private val _toasts = MutableSharedFlow<String>(extraBufferCapacity = 4)
        val toasts: SharedFlow<String> = _toasts

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
         * The startup job that recovers a pending card and surfaces any dropped
         * offline logs. Exposed only so tests can [Job.join] it deterministically
         * — production callers don't need to await it, the UI just observes the
         * resulting state flows.
         */
        val readyJob: Job =
            viewModelScope.launch {
                // Surface (once — consumeDropped clears the counter) however many
                // queued meals ReplayWorker gave up on or poison-deleted, per the
                // CARRIED FINDING from Task 7: an offline log silently vanishing
                // must leave a user-visible trace, not just a Crashlytics record.
                try {
                    val droppedCount = droppedLogStore.consumeDropped()
                    if (droppedCount > 0) {
                        val notice =
                            if (droppedCount == 1) {
                                "A queued meal from earlier couldn't be synced and was dropped."
                            } else {
                                "$droppedCount queued meals couldn't be synced and were dropped."
                            }
                        appendCoach(notice)
                    }
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: Exception) {
                    // Best-effort — a failure reading this counter must not block startup.
                }
                try {
                    val recovered = repository.recoverPending()
                    if (recovered != null) appendCard(recovered)
                    _offline.value = false
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: IOException) {
                    _offline.value = true
                } catch (exc: Exception) {
                    // HttpException or anything else on startup recovery isn't fatal
                    // and there's no chat transcript yet to report it into.
                }
            }

        /**
         * Sends [text] as a new turn: appends a user bubble, then handles the
         * result. Returns the underlying [Job] purely so tests can [Job.join] it.
         */
        fun send(text: String): Job {
            appendUser(text)
            _sending.value = true
            return viewModelScope.launch {
                try {
                    handleTurnResult(repository.sendTurn(text))
                    _offline.value = false
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: IOException) {
                    _offline.value = true
                    appendCoach("Couldn't reach Mealsy. Check your connection and try again.")
                } catch (exc: HttpException) {
                    appendCoach(httpErrorMessage(exc))
                } catch (exc: Exception) {
                    appendCoach("Something went wrong. Try again.")
                } finally {
                    _sending.value = false
                }
            }
        }

        /**
         * Sends a captured meal photo as a new turn: encodes [bitmap] via
         * [ImageEncoder], appends a photo bubble, then handles the result
         * exactly like [send]. Returns the underlying [Job] purely so tests can
         * [Job.join] it.
         */
        fun sendPhoto(bitmap: Bitmap): Job {
            _messages.value = _messages.value + ChatMsg.Photo(newId(), clock.millis(), bitmap)
            _sending.value = true
            return viewModelScope.launch {
                try {
                    // JPEG compression is CPU-bound; keep it off the main thread
                    // so a large capture doesn't cause a frame-drop stutter.
                    val imageB64 = withContext(Dispatchers.Default) { ImageEncoder.encode(bitmap) }
                    handleTurnResult(repository.sendTurn("", imageB64 = imageB64))
                    _offline.value = false
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: IOException) {
                    _offline.value = true
                    appendCoach("Couldn't reach Mealsy. Check your connection and try again.")
                } catch (exc: HttpException) {
                    appendCoach(httpErrorMessage(exc))
                } catch (exc: Exception) {
                    appendCoach("Something went wrong. Try again.")
                } finally {
                    _sending.value = false
                }
            }
        }

        /** Dispatches a [TurnResult] from `send`/`sendPhoto` into the transcript. */
        private fun handleTurnResult(result: TurnResult) {
            when (result) {
                is TurnResult.Reply -> appendCoach(result.message)
                is TurnResult.Card -> appendCard(result.card)
                is TurnResult.UpgradeRequired -> appendUpgradeNotice(result.message)
            }
        }

        /** Returns the id of the newest still-interactive card, or null if there isn't one. */
        private fun activeCardId(): String? {
            val msg = _messages.value.lastOrNull { it is ChatMsg.Card } as? ChatMsg.Card ?: return null
            return if (msg.state is CardState.Active || msg.state is CardState.Swapping) msg.id else null
        }

        /**
         * Appends [card] as a new, active [ChatMsg.Card], first stamping any
         * earlier still-active card as [CardState.NotLogged] (ported from
         * `mealStore.ts`'s `stampResolvedCard`).
         */
        private fun appendCard(card: ConfirmationCard) {
            val withMealType =
                if (card.mealType == "unspecified") {
                    card.copy(mealType = defaultMealCategory(clock))
                } else {
                    card
                }
            stampActiveCard(CardState.NotLogged)
            _messages.value = _messages.value + ChatMsg.Card(newId(), clock.millis(), withMealType, CardState.Active)
        }

        /** Replaces the currently-active card's message in place, keeping its id. */
        private fun replaceActiveCard(
            card: ConfirmationCard,
            state: CardState,
        ) {
            val activeId = activeCardId() ?: return
            _messages.value =
                _messages.value.map { msg ->
                    if (msg is ChatMsg.Card && msg.id == activeId) msg.copy(card = card, state = state) else msg
                }
        }

        /** Stamps the currently-active card (if any) with [state]. */
        private fun stampActiveCard(state: CardState) {
            val activeId = activeCardId() ?: return
            _messages.value =
                _messages.value.map { msg ->
                    if (msg is ChatMsg.Card && msg.id == activeId) msg.copy(state = state) else msg
                }
        }

        /** Drops the currently-active card message entirely (no backend call). */
        private fun dropActiveCard() {
            val activeId = activeCardId() ?: return
            _messages.value = _messages.value.filterNot { it is ChatMsg.Card && it.id == activeId }
        }

        private fun activeCard(): ConfirmationCard? {
            val activeId = activeCardId() ?: return null
            return (_messages.value.firstOrNull { it is ChatMsg.Card && it.id == activeId } as? ChatMsg.Card)?.card
        }

        /**
         * Edits the active card's item at [index] to [newQtyG]. A no-op (rather
         * than a crash) if [index] is stale — e.g. a double-tap race with
         * [removeItem] — since [CardEditor.editQty] throws on an out-of-range
         * index.
         */
        fun editQty(
            index: Int,
            newQtyG: Double,
        ) {
            val card = activeCard() ?: return
            if (index !in card.items.indices) return
            if (newQtyG <= 0) return
            replaceActiveCard(CardEditor.editQty(card, index, newQtyG), CardState.Active)
        }

        /**
         * Removes the active card's item at [index]; a no-op if [index] is
         * stale. Removing the LAST item dismisses the card locally — no
         * backend call — matching the web's behavior.
         */
        fun removeItem(index: Int) {
            val card = activeCard() ?: return
            if (index !in card.items.indices) return
            if (card.items.size == 1) {
                dropActiveCard()
                return
            }
            replaceActiveCard(CardEditor.removeItem(card, index), CardState.Active)
        }

        /** Sets the active card's meal type (breakfast/lunch/snack/dinner). */
        fun setMealType(mealType: String) {
            val card = activeCard() ?: return
            replaceActiveCard(card.copy(mealType = mealType), CardState.Active)
        }

        /** Sets the active card's overall portion multiplier. */
        fun setPortion(portion: Double) {
            val card = activeCard() ?: return
            replaceActiveCard(CardEditor.setPortion(card, portion), CardState.Active)
        }

        /**
         * Applies a candidate correction to the active card's item at [index]:
         * marks the card [CardState.Swapping] and sends a `use X instead of Y`
         * turn. A returned [TurnResult.Card] replaces the card in place (back to
         * [CardState.Active]); a [TurnResult.Reply]/[TurnResult.UpgradeRequired]
         * stamps it [CardState.NotLogged] and appends the reply. On [IOException]
         * the swap reverts to [CardState.Active] and the offline copy is
         * appended, per the T4 build brief.
         */
        fun onSwapCandidate(
            index: Int,
            newName: String,
        ): Job? {
            val card = activeCard() ?: return null
            if (index !in card.items.indices) return null
            val from = card.items[index].foodName
            replaceActiveCard(CardEditor.replaceCandidate(card, index, newName), CardState.Swapping)
            _sending.value = true
            return viewModelScope.launch {
                try {
                    when (val result = repository.correctCandidate(from, newName)) {
                        is TurnResult.Card -> replaceActiveCard(result.card, CardState.Active)
                        is TurnResult.Reply -> {
                            stampActiveCard(CardState.NotLogged)
                            appendCoach(result.message)
                        }
                        is TurnResult.UpgradeRequired -> {
                            stampActiveCard(CardState.NotLogged)
                            appendUpgradeNotice(result.message)
                        }
                    }
                    _offline.value = false
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: IOException) {
                    _offline.value = true
                    replaceActiveCard(card, CardState.Active)
                    appendCoach("Couldn't reach Mealsy. Check your connection and try again.")
                } catch (exc: HttpException) {
                    stampActiveCard(CardState.NotLogged)
                    appendCoach(httpErrorMessage(exc))
                } catch (exc: Exception) {
                    stampActiveCard(CardState.NotLogged)
                    appendCoach("Something went wrong. Try again.")
                } finally {
                    _sending.value = false
                }
            }
        }

        /** Decomposes the active composite-dish card in place. See [onSwapCandidate] for the shared error handling shape. */
        fun onDecompose(): Job? = runCardMutation { repository.decompose() }

        /** Combines the active card's items back into a composite dish in place. */
        fun onCombine(): Job? = runCardMutation { repository.combine() }

        private fun runCardMutation(call: suspend () -> TurnResult): Job? {
            val card = activeCard() ?: return null
            _sending.value = true
            return viewModelScope.launch {
                try {
                    when (val result = call()) {
                        is TurnResult.Card -> replaceActiveCard(result.card, CardState.Active)
                        is TurnResult.Reply -> {
                            stampActiveCard(CardState.NotLogged)
                            appendCoach(result.message)
                        }
                        is TurnResult.UpgradeRequired -> {
                            stampActiveCard(CardState.NotLogged)
                            appendUpgradeNotice(result.message)
                        }
                    }
                    _offline.value = false
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: IOException) {
                    _offline.value = true
                    appendCoach("Couldn't reach Mealsy. Check your connection and try again.")
                } catch (exc: HttpException) {
                    appendCoach(httpErrorMessage(exc))
                } catch (exc: Exception) {
                    appendCoach("Something went wrong. Try again.")
                } finally {
                    _sending.value = false
                }
            }
        }

        /**
         * Confirms the active card. On success, stamps it [CardState.Logged]
         * with the distinct humanized dish names and rounded kcal total, and
         * appends the server's reply carrying macro tags. Leaves it in place
         * (for retry) on failure.
         */
        fun confirm(): Job? {
            val activeId = activeCardId() ?: return null
            val card = activeCard() ?: return null
            _sending.value = true
            return viewModelScope.launch {
                try {
                    when (val outcome = repository.confirmCard(card)) {
                        is LogOutcome.Logged -> {
                            val label = loggedLabel(card)
                            val kcal = Math.round(CardEditor.totals(card).kcal).toInt()
                            _messages.value =
                                _messages.value.map { msg ->
                                    if (msg is ChatMsg.Card && msg.id == activeId) {
                                        msg.copy(state = CardState.Logged(label, kcal))
                                    } else {
                                        msg
                                    }
                                }
                            _toasts.tryEmit("Logged: $label · $kcal kcal")
                            appendCoach(
                                outcome.message,
                                tags =
                                    listOf(
                                        MacroTag("$kcal kcal", PastelTone.Butter),
                                        MacroTag("${Math.round(outcome.proteinG)}g protein", PastelTone.Leaf),
                                    ),
                            )
                            _offline.value = false
                        }
                        is LogOutcome.Queued -> {
                            stampActiveCard(CardState.NotLogged)
                            _offline.value = true
                            appendCoach("Saved — will sync when you're back online")
                        }
                    }
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: IOException) {
                    _offline.value = true
                    appendCoach("Couldn't log that — check your connection and try again.")
                } catch (exc: HttpException) {
                    appendCoach(httpErrorMessage(exc))
                } catch (exc: Exception) {
                    appendCoach("Something went wrong. Try again.")
                } finally {
                    _sending.value = false
                }
            }
        }

        /** The distinct `sourceDish ?: foodName` values, humanized, joined for a collapsed-card label. */
        private fun loggedLabel(card: ConfirmationCard): String {
            val names = card.items.map { it.sourceDish ?: it.foodName }.distinct()
            return names.joinToString(", ") { FoodNameHumanizer.humanize(it) }
        }

        /** Cancels the active card. It is only stamped [CardState.Discarded] once cancellation actually succeeds. */
        fun cancel(): Job? {
            if (activeCardId() == null) return null
            _sending.value = true
            return viewModelScope.launch {
                try {
                    when (val result = repository.cancelCard()) {
                        is TurnResult.Reply -> {
                            stampActiveCard(CardState.Discarded)
                            appendCoach(result.message)
                        }
                        is TurnResult.Card -> replaceActiveCard(result.card, CardState.Active)
                        is TurnResult.UpgradeRequired -> {
                            stampActiveCard(CardState.Discarded)
                            appendUpgradeNotice(result.message)
                        }
                    }
                    _offline.value = false
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: IOException) {
                    // Leave the card in place — the server's confirmation thread
                    // is still paused, and losing it here strands that thread.
                    _offline.value = true
                    appendCoach("Couldn't cancel — check your connection and try again.")
                } catch (exc: HttpException) {
                    appendCoach(httpErrorMessage(exc))
                } catch (exc: Exception) {
                    appendCoach("Something went wrong. Try again.")
                } finally {
                    _sending.value = false
                }
            }
        }

        /**
         * Saves the active card as a new My Meal named [name]. A duplicate name
         * (409) and success are both reported as one-shot toasts rather than
         * transcript messages.
         */
        fun onSaveAsMyMeal(name: String): Job? {
            val card = activeCard() ?: return null
            _savingMeal.value = true
            return viewModelScope.launch {
                try {
                    myMealsRepository.save(card, name)
                    _toasts.tryEmit("Saved \"$name\" to My Meals.")
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: HttpException) {
                    if (exc.code() == 409) {
                        _toasts.tryEmit("You already have a meal with that name.")
                    } else {
                        _toasts.tryEmit("Couldn't save that meal. Try again.")
                    }
                } catch (exc: IOException) {
                    _toasts.tryEmit("Couldn't reach Mealsy. Check your connection and try again.")
                } catch (exc: Exception) {
                    _toasts.tryEmit("Couldn't save that meal. Try again.")
                } finally {
                    _savingMeal.value = false
                }
            }
        }

        /**
         * Submits [rating] (1 = up, -1 = down) for the coach message [messageId].
         * A no-op when that message has no `responseId` — this backend branch
         * never emits one today, so the thumbs UI never renders and this is
         * never actually called in practice, but the logic is here for when it
         * does. Optimistically applies [rating], reverting on failure.
         */
        fun submitFeedback(
            messageId: String,
            rating: Int,
        ): Job? {
            val msg = _messages.value.firstOrNull { it.id == messageId } as? ChatMsg.Coach ?: return null
            val responseId = msg.responseId ?: return null
            val previous = msg.feedback
            setCoachFeedback(messageId, rating)
            return viewModelScope.launch {
                try {
                    repository.submitCoachingFeedback(responseId, rating)
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: Exception) {
                    setCoachFeedback(messageId, previous)
                }
            }
        }

        private fun setCoachFeedback(
            messageId: String,
            feedback: Int?,
        ) {
            _messages.value =
                _messages.value.map { msg ->
                    if (msg is ChatMsg.Coach && msg.id == messageId) msg.copy(feedback = feedback) else msg
                }
        }

        /** A 429 gets its own copy; every other server error is a generic retry prompt. */
        private fun httpErrorMessage(exc: HttpException): String =
            if (exc.code() == 429) {
                "Slow down a moment and try again."
            } else {
                "Something went wrong on our end. Try again shortly."
            }

        private fun appendUser(text: String) {
            _messages.value = _messages.value + ChatMsg.User(newId(), clock.millis(), text)
        }

        private fun appendCoach(
            text: String,
            tags: List<MacroTag> = emptyList(),
        ) {
            _messages.value = _messages.value + ChatMsg.Coach(newId(), clock.millis(), text, tags = tags)
        }

        private fun appendUpgradeNotice(text: String) {
            _messages.value = _messages.value + ChatMsg.UpgradeNotice(newId(), clock.millis(), text)
        }

        private fun newId(): String = UUID.randomUUID().toString()
    }
