package app.mealsy.android.ui.chat

import android.graphics.Bitmap
import androidx.lifecycle.ViewModel
import app.mealsy.domain.ConfirmationCard
import app.mealsy.domain.PastelTone
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
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
 * Drives the chat screen. This is now a thin per-nav-entry forwarder onto
 * [ChatSessionStore] — a `@Singleton` that actually owns the transcript and
 * launches all network work — rather than holding that state itself.
 *
 * That split is the #40 fix: [androidx.hilt.navigation.compose.hiltViewModel]
 * scopes a `ChatViewModel` to its own backstack entry, so the FAB's
 * `chat?quickLog=true` entry and the Chat tab's `chat` entry used to get two
 * independent `ChatViewModel`s — two empty transcripts, two different
 * "active" cards, and a `viewModelScope` that died the moment either entry
 * was popped mid-request. Routing every screen instance through the same
 * injected [ChatSessionStore] singleton means:
 *  - the FAB and the Chat tab always render the same transcript/active card
 *    (#40 part 1) — no separate conversation state to keep in sync.
 *  - a send/confirm/cancel keeps running on the store's app-scoped coroutine
 *    even after this `ViewModel` (and its `viewModelScope`) is cleared by
 *    navigating away (#40 part 2).
 *  - construction re-runs pending-card recovery via [ChatSessionStore.attach]
 *    (skipped while a send is in flight, or while signed out) — every chat
 *    open re-checks `GET /meals/pending`, not just the first one — and the
 *    store resets itself on sign-out/sign-in so one user's transcript never
 *    leaks into another's session (see [ChatSessionStore]'s KDoc).
 *
 * Home, Trends, and My Meals are reached via `AppNav`'s [app.mealsy.android.design.components.BottomNavPill],
 * not from this screen. The today totals/goals header that used to live here
 * (`TodayHeader`) was retired — Home owns that display now and refreshes
 * itself via `TodayRefreshSignal` on `ON_RESUME`, so this screen no longer
 * needs its own refresh hook for it.
 */
@HiltViewModel
class ChatViewModel
    @Inject
    constructor(
        private val session: ChatSessionStore,
    ) : ViewModel() {
        val messages: StateFlow<List<ChatMsg>> = session.messages
        val sending: StateFlow<Boolean> = session.sending
        val offline: StateFlow<Boolean> = session.offline
        val savingMeal: StateFlow<Boolean> = session.savingMeal
        val toasts: SharedFlow<String> = session.toasts
        val undoToast: StateFlow<UndoToast?> = session.undoToast

        /**
         * Re-runs pending-card recovery for this screen open (see
         * [ChatSessionStore.attach]). Called once per `ChatViewModel`
         * instance — i.e. once per chat-screen open, FAB or tab — not just
         * the first ever. Exposed as a `Job` so tests can [Job.join] it
         * deterministically.
         */
        val readyJob: Job = session.attach()

        fun send(text: String): Job = session.send(text)

        fun sendPhoto(
            bitmap: Bitmap,
            text: String = "",
        ): Job = session.sendPhoto(bitmap, text)

        fun editQty(
            index: Int,
            newQtyG: Double,
        ) = session.editQty(index, newQtyG)

        fun removeItem(index: Int) = session.removeItem(index)

        fun undoRemove() = session.undoRemove()

        fun dismissUndoToast() = session.dismissUndoToast()

        fun setMealType(mealType: String) = session.setMealType(mealType)

        fun setPortion(portion: Double) = session.setPortion(portion)

        fun onSwapCandidate(
            index: Int,
            newName: String,
        ): Job? = session.onSwapCandidate(index, newName)

        /** Local, network-free swap from the food picker (spec 003, T027). */
        fun swapItem(
            index: Int,
            newItem: app.mealsy.domain.CardItem,
            method: String,
            query: String? = null,
        ) = session.swapItem(index, newItem, method, query)

        /** Undoes the most recent [swapItem]. */
        fun undoSwap() = session.undoSwap()

        fun onDescribeItemDifferently(
            index: Int,
            description: String,
        ): Job? = session.onDescribeItemDifferently(index, description)

        fun onDecompose(): Job? = session.onDecompose()

        fun onCombine(): Job? = session.onCombine()

        fun confirm(): Job? = session.confirm()

        fun cancel(): Job? = session.cancel()

        fun onSaveAsMyMeal(name: String): Job? = session.onSaveAsMyMeal(name)

        fun submitFeedback(
            messageId: String,
            rating: Int,
        ): Job? = session.submitFeedback(messageId, rating)
    }
