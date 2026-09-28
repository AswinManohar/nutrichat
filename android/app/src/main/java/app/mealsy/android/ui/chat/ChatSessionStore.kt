package app.mealsy.android.ui.chat

import app.mealsy.android.di.ApplicationScope
import app.mealsy.android.util.ConnectivityObserver
import app.mealsy.data.auth.SessionManager
import app.mealsy.data.auth.SessionState
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
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
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
import javax.inject.Singleton

/** [ChatSessionStore]'s internal key for "signed out" — distinct from any real user id. */
private const val SIGNED_OUT_KEY = "\u0000signed-out"

/** Sentinel meaning "no session observed yet" — distinct from [SIGNED_OUT_KEY] and any user id. */
private const val UNSET_KEY = "\u0000unset"

/**
 * Holds the single chat conversation's transcript and in-flight work, shared
 * by every [ChatViewModel] instance regardless of which nav-graph entry
 * (`chat` tab or `chat?quickLog=true` from the FAB) created it — #40: the FAB
 * quick-log and the Chat tab must show the SAME conversation, not two
 * independent threads that only converge server-side via
 * [ChatRepository.conversationId]'s persisted id.
 *
 * `@Singleton` + work launched on the injected [ApplicationScope] (rather
 * than a `ViewModel`'s `viewModelScope`) is also what makes sending survive
 * navigation (#40 part 2): `viewModelScope` is cancelled the instant its
 * backstack entry is popped (system Back, a tab tap while a reply is still
 * in flight), which used to cancel the in-flight `POST /meals/log` outright.
 * A dropped response is still recovered via [ChatRepository.recoverPending]
 * (`GET /meals/pending`) the same way it always was — that recovery path is
 * unchanged here, just no longer racing a viewModelScope cancellation.
 *
 * This is exactly the logic [ChatViewModel] used to run directly in its own
 * `viewModelScope`; [ChatViewModel] is now a thin per-screen forwarder onto
 * this store (see its KDoc).
 *
 * Being a singleton means it outlives any one user's sign-in, so it also
 * observes [SessionManager.sessionState] to reset itself on sign-out/sign-in
 * (or a same-device switch to a different account) — see [resetForNewSession]
 * — rather than leaking one user's transcript into the next session. Pending
 * recovery (`GET /meals/pending`) also isn't a construction-time one-shot any
 * more: it re-runs on every [attach] (i.e. every `ChatViewModel` creation),
 * gated to only fire while [SessionManager.sessionState] is
 * [SessionState.SignedIn] and skipped while a send is already in flight — see
 * [attach].
 *
 * @param clock Injected so tests can pin timestamps and [defaultMealCategory].
 */
@Singleton
class ChatSessionStore
    @Inject
    constructor(
        private val repository: ChatRepository,
        private val connectivity: ConnectivityObserver,
        private val myMealsRepository: MyMealsRepository,
        private val droppedLogStore: DroppedLogStore,
        private val sessionManager: SessionManager,
        @ApplicationScope private val scope: CoroutineScope,
        private val clock: Clock = Clock.systemDefaultZone(),
    ) {
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

        /**
         * The last-observed session identity: a user id, [SIGNED_OUT_KEY], or
         * [UNSET_KEY] before the first [SessionState] is seen. Used purely to
         * detect a *change* of identity (sign-out, sign-in, or a same-device
         * switch to a different account) in [resetForNewSession] — comparing
         * successive [SessionState.SignedIn] values by id, not by reference,
         * since e.g. a token refresh emits a new but same-user `SignedIn`.
         */
        private var sessionKey: String = UNSET_KEY

        /**
         * The child job all message-mutating work (send/confirm/cancel/edit/
         * recovery) is launched under. Cancelled and replaced wholesale in
         * [resetForNewSession] so a sign-out (or account switch) can't let a
         * stale request from the old user's session land after the
         * transcript has already been reset — a plain per-call `Job` field
         * would need every launch site to remember to check it.
         */
        private var sessionJob = kotlinx.coroutines.SupervisorJob(scope.coroutineContext[Job])
        private var sessionScope: CoroutineScope = CoroutineScope(scope.coroutineContext + sessionJob)

        /** The most recently launched [attach] recovery job — exposed via [attach]'s return value for tests to join. */
        private var recoveryJob: Job = completedJob()

        init {
            // Primary offline signal: with no pending card there may be no
            // in-flight network call left to ever clear a stale `_offline=true`
            // (e.g. connectivity drops with nothing queued), so connectivity
            // changes must be able to both set AND clear the banner, or the
            // chat input stays locked out until the process restarts. The
            // request-driven sets elsewhere (send/confirm/cancel/startup)
            // remain a secondary signal — they fire immediately on a call's
            // actual outcome without waiting for the OS to notice. This
            // collector lives on the outer [scope], not [sessionScope]: it's
            // not user-specific and must keep running across a sign-out.
            scope.launch {
                connectivity.isOnline.collect { online -> _offline.value = !online }
            }

            // #40 follow-up: this store is a process-wide singleton, so it
            // outlives any one user's sign-in. Without this, signing out and
            // back in (or switching accounts on the same device) would leave
            // the previous user's transcript on screen. `sessionState` is a
            // hot StateFlow — comparing against [sessionKey] (not just
            // reacting to every emission) is what makes this a no-op for a
            // same-user re-emission (e.g. a token refresh), while still
            // resetting on a genuine identity change either direction.
            scope.launch {
                sessionManager.sessionState.collect { state ->
                    val newKey =
                        when (state) {
                            is SessionState.SignedIn -> state.userId
                            SessionState.SignedOut -> SIGNED_OUT_KEY
                            // Transient — wait for a real (signed-in/signed-out) value
                            // rather than treating "loading" as its own identity.
                            SessionState.Loading -> return@collect
                        }
                    if (newKey != sessionKey) {
                        sessionKey = newKey
                        resetForNewSession()
                    }
                }
            }
        }

        /**
         * Cancels all in-flight session work and clears the transcript —
         * called whenever [sessionKey] changes (sign-out, sign-in, or a
         * same-device account switch). Recovery for the *new* session is
         * NOT re-triggered here: it runs from [attach], the same as any
         * other chat-screen open, once a `ChatViewModel` is actually created
         * against the new session.
         */
        private fun resetForNewSession() {
            sessionJob.cancel()
            sessionJob = kotlinx.coroutines.SupervisorJob(scope.coroutineContext[Job])
            sessionScope = CoroutineScope(scope.coroutineContext + sessionJob)
            recoveryJob = completedJob()
            _messages.value = emptyList()
            _sending.value = false
            _savingMeal.value = false
        }

        /** An already-completed [Job], for [attach] call sites that have nothing to run. */
        private fun completedJob(): Job = Job().apply { complete() }

        /**
         * Called by every new [ChatViewModel] (i.e. every chat-screen open,
         * FAB or tab) to re-run pending-card recovery (`GET /meals/pending`).
         * This used to be a construction-time one-shot ([recoveryJob] simply
         * ran once when the singleton was first built) — which could run
         * before any session existed (recovering 401s), and never re-ran
         * later, even though the same recovery used to happen on every chat
         * open when [ChatViewModel] owned it directly (e.g. a card left
         * pending from another device or Telegram, or the app resuming after
         * hours in the background).
         *
         * A no-op (returns the previous [recoveryJob] rather than launching a
         * new one) while a send/confirm/cancel/etc is already in flight —
         * racing recovery against an active card's own request could stomp
         * whichever finishes last. Also a no-op (an already-[completedJob])
         * while signed out: [SessionManager]'s token provider has nothing to
         * attach to `GET /meals/pending` yet, and `checkOnboarding` may not
         * have even resolved.
         *
         * Returns the [Job] so tests (and this store's own KDoc contract) can
         * await it deterministically.
         */
        fun attach(): Job {
            if (_sending.value) return recoveryJob
            if (sessionManager.sessionState.value !is SessionState.SignedIn) return completedJob()
            val job = sessionScope.launch { runRecovery() }
            recoveryJob = job
            return job
        }

        /** The actual recovery body shared by every [attach] call. */
        private suspend fun runRecovery() {
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
                // A second (or later) attach() must not re-append the same
                // still-pending card every time chat is reopened — compare
                // against the already-shown active card (there's no server
                // id on ConfirmationCard to key off; content equality is the
                // available substitute) and only append when it's actually
                // new/different. Normalize the mealType the same way
                // appendCard does first — otherwise a raw "unspecified" from
                // the wire would never equal the already-defaulted active
                // card and this would re-append every time.
                if (recovered != null && withDefaultMealType(recovered) != activeCard()) {
                    appendCard(recovered)
                }
                _offline.value = false
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: IOException) {
                _offline.value = true
            } catch (exc: Exception) {
                // HttpException or anything else on recovery isn't fatal —
                // the existing transcript (if any) stays as-is.
            }
        }

        /**
         * Sends [text] as a new turn: appends a user bubble, then handles the
         * result. Returns the underlying [Job] purely so tests can [Job.join] it.
         */
        fun send(text: String): Job {
            appendUser(text)
            _sending.value = true
            return sessionScope.launch {
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
         * [app.mealsy.data.image.ImageEncoder], appends a photo bubble, then
         * handles the result exactly like [send]. Returns the underlying [Job]
         * purely so tests can [Job.join] it.
         */
        fun sendPhoto(bitmap: android.graphics.Bitmap): Job {
            _messages.value = _messages.value + ChatMsg.Photo(newId(), clock.millis(), bitmap)
            _sending.value = true
            return sessionScope.launch {
                try {
                    // JPEG compression is CPU-bound; keep it off the main thread
                    // so a large capture doesn't cause a frame-drop stutter.
                    val imageB64 =
                        withContext(Dispatchers.Default) {
                            app.mealsy.data.image.ImageEncoder.encode(bitmap)
                        }
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

        /** Fills in [ConfirmationCard.mealType] via [defaultMealCategory] when the wire left it "unspecified". */
        private fun withDefaultMealType(card: ConfirmationCard): ConfirmationCard =
            if (card.mealType == "unspecified") card.copy(mealType = defaultMealCategory(clock)) else card

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
            val withMealType = withDefaultMealType(card)
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
         * The active card's message id, card, and state exactly as they were
         * just before the most recent [removeItem] call — what [undoRemove]
         * restores. `null` once consumed by [undoRemove] or once a different
         * mutation makes "undo the removal" no longer meaningful is NOT
         * tracked separately here; the "Removed X" toast's own 4s auto-
         * dismiss (see [ConfirmCardView]) is what actually bounds how long
         * undo stays offered in the UI.
         */
        private var lastRemoved: Triple<String, ConfirmationCard, CardState>? = null

        /**
         * Removes the active card's item at [index]; a no-op if [index] is
         * stale. Removing the LAST item dismisses the card locally — no
         * backend call — matching the web's behavior. Snapshots the card
         * beforehand into [lastRemoved] so [undoRemove] can restore it
         * (#46 — the "Removed X" toast's Undo used to be wired to nothing).
         */
        fun removeItem(index: Int) {
            val activeId = activeCardId() ?: return
            val card = activeCard() ?: return
            if (index !in card.items.indices) return
            val stateBefore =
                (_messages.value.firstOrNull { it.id == activeId } as? ChatMsg.Card)?.state ?: CardState.Active
            lastRemoved = Triple(activeId, card, stateBefore)
            if (card.items.size == 1) {
                dropActiveCard()
                return
            }
            replaceActiveCard(CardEditor.removeItem(card, index), CardState.Active)
        }

        /**
         * Restores the card exactly as it was before the most recent
         * [removeItem] call — either back into the still-present card
         * message (its id unchanged), or, if removing the last item dropped
         * the message entirely, by re-appending it. A no-op if nothing has
         * been removed since the last [undoRemove].
         */
        fun undoRemove() {
            val (id, card, state) = lastRemoved ?: return
            lastRemoved = null
            val stillPresent = _messages.value.any { it.id == id }
            _messages.value =
                if (stillPresent) {
                    _messages.value.map { msg ->
                        if (msg is ChatMsg.Card && msg.id == id) msg.copy(card = card, state = state) else msg
                    }
                } else {
                    _messages.value + ChatMsg.Card(id, clock.millis(), card, state)
                }
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

        /** The active card exactly as it was just before the most recent [swapItem] call. */
        private var lastSwap: Pair<Int, app.mealsy.domain.CardItem>? = null

        /**
         * Applies the food picker's local swap (spec 003, T027) to the active
         * card's item at [index]: replaces it with [newItem] (already fetched
         * from `GET /foods/{fdc_id}`) via [CardEditor.swapItem], keeping its
         * grams and meal type, no network round trip. A no-op if [index] is
         * stale.
         */
        fun swapItem(
            index: Int,
            newItem: app.mealsy.domain.CardItem,
            method: String,
            query: String? = null,
        ) {
            val card = activeCard() ?: return
            if (index !in card.items.indices) return
            lastSwap = index to card.items[index]
            replaceActiveCard(CardEditor.swapItem(card, index, newItem, method, query), CardState.Active)
        }

        /**
         * Restores the item most recently changed by [swapItem], dropping its
         * pending correction. A no-op if nothing has been swapped since the
         * last [undoSwap].
         */
        fun undoSwap() {
            val (index, previous) = lastSwap ?: return
            lastSwap = null
            val card = activeCard() ?: return
            if (index !in card.items.indices) return
            replaceActiveCard(CardEditor.undoSwap(card, index, previous), CardState.Active)
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
            return sessionScope.launch {
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

        /**
         * Applies a free-text re-description to the active card's item at
         * [index] (#39's "None of these — describe it differently" fallback):
         * marks the card [CardState.Swapping] and sends the description back
         * through the paused graph for re-resolution, then handles the result
         * exactly like [onSwapCandidate].
         */
        fun onDescribeItemDifferently(
            index: Int,
            description: String,
        ): Job? {
            val card = activeCard() ?: return null
            if (index !in card.items.indices) return null
            val from = card.items[index].foodName
            replaceActiveCard(CardEditor.replaceCandidate(card, index, description), CardState.Swapping)
            _sending.value = true
            return sessionScope.launch {
                try {
                    when (val result = repository.describeItemDifferently(from, description)) {
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
            return sessionScope.launch {
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
            return sessionScope.launch {
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
            return sessionScope.launch {
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
            return sessionScope.launch {
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
            return sessionScope.launch {
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
