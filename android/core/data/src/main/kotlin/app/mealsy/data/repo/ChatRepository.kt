package app.mealsy.data.repo

import app.mealsy.data.api.ItemDto
import app.mealsy.data.api.LogItemsRequest
import app.mealsy.data.api.LogTurnRequest
import app.mealsy.data.api.LogTurnResponse
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.toCard
import app.mealsy.domain.CardItem
import app.mealsy.domain.ConfirmationCard
import java.io.IOException
import java.util.UUID
import javax.inject.Inject
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Result of a single `POST /meals/log` turn.
 *
 * `UpgradeRequired` is detected two ways: a fast-path match on the backend's
 * `_UPGRADE_MSG` string (see `src/backend/agent/orchestrator.py` — there is
 * no structured `status`/quota field on this response today; filed as a
 * backend follow-up in the task report), and — when a turn comes back
 * unpaused with no items and no marker match (e.g. the backend's copy
 * drifts) — a fallback `GET /quota` check for `remaining <= 0`. Its
 * [UpgradeRequired.message] is always a client-authored, policy-safe
 * string — never the raw backend text, which contains an upgrade URL that
 * must not surface on Android per Play payments policy. [Reply.message] is
 * also scrubbed of URLs for the same reason, since any turn's reply text
 * could in principle carry one.
 */
sealed interface TurnResult {
    data class Reply(val message: String) : TurnResult
    data class Card(val card: ConfirmationCard) : TurnResult
    data class UpgradeRequired(val message: String) : TurnResult
}

/** Result of `POST /meals/log-items`. */
data class LogOutcome(
    val mealId: String,
    val mealType: String,
    val kcal: Double,
    val proteinG: Double,
    val carbsG: Double,
    val fatG: Double,
    val fiberG: Double,
    val message: String,
    val deduplicated: Boolean,
)

/**
 * The exact string the backend returns as `message` on `POST /meals/log`
 * when a user's free quota is exhausted (`_UPGRADE_MSG` in
 * `src/backend/agent/orchestrator.py`). There is no structured field for
 * this today, so detection is a message match — a backend follow-up should
 * add a `status == "quota_exhausted"` field so this doesn't depend on exact
 * copy staying in sync between the two repos.
 */
private const val UPGRADE_MSG_MARKER = "used all your free AI requests"

/** Policy-safe upgrade message shown on Android — no link, no price (Play payments policy). */
private const val UPGRADE_SAFE_MESSAGE = "You've reached your free daily limit for today."

/** Matches bare/scheme-prefixed URLs so raw backend text never surfaces one on Android. */
private val URL_PATTERN = Regex(
    """(https?://\S+)|(\b[a-zA-Z0-9-]+\.[a-zA-Z]{2,6}(?:/[\w\-./?%&=]*)?\b)""",
)

private fun stripUrls(text: String): String =
    text.replace(URL_PATTERN, "").replace(Regex("\\s{2,}"), " ").trim()

/**
 * Drives the `POST /meals/log` confirmation flow: sending turns, recovering
 * a paused card after a dropped connection, and confirming or cancelling it.
 *
 * The active conversation id is namespaced per backend LangGraph thread and
 * persisted via [conversationIdStore] so [recoverPending] can target the
 * same conversation across process death, not just within one repository
 * instance's lifetime. It rotates (a fresh UUID is generated and persisted)
 * after every successful [confirmCard] or [cancelCard] so a new turn starts
 * a fresh conversation rather than resuming a just-closed one.
 */
class ChatRepository @Inject constructor(
    private val api: MealsyApi,
    private val conversationIdStore: ConversationIdStore,
) {

    private val conversationIdMutex = Mutex()
    private var cachedConversationId: String? = null

    /**
     * `client_request_id` for the confirmation currently in flight, and the
     * identity of the card it belongs to. Generated once when a card first
     * enters "confirming" and kept across retries of *that same card* so a
     * dropped response can be safely replayed without double-logging.
     * Cleared whenever a confirmation succeeds, whenever the card is
     * cancelled, or whenever a fresh card supersedes it — a failed confirm
     * of card A must never let card B (or a retried-but-different A) inherit
     * A's id, or the server's dedup would silently drop B.
     */
    private var pendingConfirmation: Pair<ConfirmationCard, String>? = null

    /** Returns the persisted conversation id, generating and persisting one on first use. */
    suspend fun conversationId(): String {
        cachedConversationId?.let { return it }
        return conversationIdMutex.withLock {
            cachedConversationId?.let { return@withLock it }
            val loaded = conversationIdStore.get() ?: UUID.randomUUID().toString().also {
                conversationIdStore.set(it)
            }
            cachedConversationId = loaded
            loaded
        }
    }

    suspend fun sendTurn(text: String, imageB64: String? = null): TurnResult {
        val id = conversationId()
        val response = try {
            api.logTurn(LogTurnRequest(userInput = text, conversationId = id, imageB64 = imageB64))
        } catch (exc: IOException) {
            // The request may or may not have committed server-side (see the
            // mobile API contract: POST /meals/log must never be blindly
            // retried). Recover the actual state instead of guessing.
            val recovered = api.pending(id).toCard()
            if (recovered != null) return TurnResult.Card(recovered)
            throw exc
        }
        return toTurnResult(response)
    }

    suspend fun recoverPending(): ConfirmationCard? {
        return api.pending(conversationId()).toCard()
    }

    suspend fun confirmCard(card: ConfirmationCard): LogOutcome {
        val existing = pendingConfirmation
        val clientRequestId = if (existing != null && existing.first == card) {
            existing.second
        } else {
            UUID.randomUUID().toString().also { pendingConfirmation = card to it }
        }

        val response = api.logItems(
            LogItemsRequest(
                mealType = card.mealType,
                portion = card.portion,
                items = card.items.map { it.toItemDto() },
                clientRequestId = clientRequestId,
            ),
        )

        pendingConfirmation = null
        rotateConversationId()

        return LogOutcome(
            mealId = response.mealId,
            mealType = response.mealType,
            kcal = response.kcal,
            proteinG = response.proteinG,
            carbsG = response.carbsG,
            fatG = response.fatG,
            fiberG = response.fiberG,
            message = response.message,
            deduplicated = response.deduplicated,
        )
    }

    /**
     * Cancels the paused conversation. The conversation id only rotates —
     * and [pendingConfirmation] only clears — when the cancel actually
     * lands ([TurnResult.Reply]/[TurnResult.UpgradeRequired]). If
     * `sendTurn("cancel")` drops with an [IOException] and recovers a still-
     * pending [TurnResult.Card] (see [sendTurn]'s recovery path), the card
     * was never actually cancelled server-side: rotating here would orphan
     * it (a later [recoverPending] would target the new id and never find
     * it again), and clearing [pendingConfirmation] would hand a re-confirm
     * of that same card a fresh `client_request_id`, double-logging a
     * confirm that may have already committed.
     */
    suspend fun cancelCard(): TurnResult {
        val result = sendTurn("cancel")
        when (result) {
            is TurnResult.Reply, is TurnResult.UpgradeRequired -> {
                pendingConfirmation = null
                rotateConversationId()
            }
            is TurnResult.Card -> Unit
        }
        return result
    }

    private suspend fun rotateConversationId() {
        val fresh = UUID.randomUUID().toString()
        conversationIdStore.set(fresh)
        cachedConversationId = fresh
    }

    private suspend fun toTurnResult(response: LogTurnResponse): TurnResult {
        if (!response.paused && response.message.contains(UPGRADE_MSG_MARKER)) {
            return TurnResult.UpgradeRequired(UPGRADE_SAFE_MESSAGE)
        }
        val card = response.toCard()
        if (card != null) {
            // A fresh card supersedes any confirmation id from a previous,
            // different card — never let a failed confirm of the old card
            // bleed its client_request_id into this new one.
            pendingConfirmation = null
            return TurnResult.Card(card)
        }
        if (!response.paused && response.items.isEmpty()) {
            val quota = runCatching { api.quota() }.getOrNull()
            if (quota != null && quota.remaining <= 0) {
                return TurnResult.UpgradeRequired(UPGRADE_SAFE_MESSAGE)
            }
        }
        return TurnResult.Reply(stripUrls(response.message))
    }
}

private fun CardItem.toItemDto(): ItemDto = ItemDto(
    foodName = foodName,
    qtyG = qtyG,
    targetQtyG = targetQtyG,
    kcal = kcal,
    proteinG = proteinG,
    carbsG = carbsG,
    fatG = fatG,
    fiberG = fiberG,
    fdcId = fdcId,
    estimated = estimated,
    extras = extras,
)
