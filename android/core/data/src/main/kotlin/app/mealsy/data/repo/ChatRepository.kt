package app.mealsy.data.repo

import app.mealsy.data.api.ItemDto
import app.mealsy.data.api.LogItemsRequest
import app.mealsy.data.api.LogTurnRequest
import app.mealsy.data.api.LogTurnResponse
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.toCard
import app.mealsy.domain.CardItem
import app.mealsy.domain.ConfirmationCard
import java.util.UUID
import javax.inject.Inject

/**
 * Result of a single `POST /meals/log` turn.
 *
 * `UpgradeRequired` is detected on `message` matching the backend's
 * `_UPGRADE_MSG` string (see `src/backend/agent/orchestrator.py` — there is
 * no structured `status`/quota field on this response today; filed as a
 * backend follow-up in the task report). Its [UpgradeRequired.message] is a
 * client-authored, policy-safe string — never the raw backend text, which
 * contains an upgrade URL that must not surface on Android per Play
 * payments policy.
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

/**
 * Drives the `POST /meals/log` confirmation flow: sending turns, recovering
 * a paused card after a dropped connection, and confirming or cancelling it.
 *
 * [conversationId] namespaces the backend's LangGraph thread and rotates
 * after every successful [confirmCard] or [cancelCard] so a new turn starts
 * a fresh conversation rather than resuming a just-closed one.
 */
class ChatRepository @Inject constructor(private val api: MealsyApi) {

    var conversationId: String = UUID.randomUUID().toString()
        private set

    /**
     * `client_request_id` for the confirmation currently in flight. Generated
     * once when a card first enters "confirming" (the first [confirmCard]
     * call for it) and kept across retries of that same call so a dropped
     * response can be safely replayed without double-logging; cleared once
     * that confirmation succeeds.
     */
    private var pendingClientRequestId: String? = null

    suspend fun sendTurn(text: String, imageB64: String? = null): TurnResult {
        val response = api.logTurn(
            LogTurnRequest(userInput = text, conversationId = conversationId, imageB64 = imageB64),
        )
        return response.toTurnResult()
    }

    suspend fun recoverPending(): ConfirmationCard? {
        return api.pending(conversationId).toCard()
    }

    suspend fun confirmCard(card: ConfirmationCard): LogOutcome {
        val clientRequestId = pendingClientRequestId
            ?: UUID.randomUUID().toString().also { pendingClientRequestId = it }

        val response = api.logItems(
            LogItemsRequest(
                mealType = card.mealType,
                portion = card.portion,
                items = card.items.map { it.toItemDto() },
                clientRequestId = clientRequestId,
            ),
        )

        pendingClientRequestId = null
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

    suspend fun cancelCard(): TurnResult {
        val result = sendTurn("cancel")
        rotateConversationId()
        return result
    }

    private fun rotateConversationId() {
        conversationId = UUID.randomUUID().toString()
    }
}

private fun LogTurnResponse.toTurnResult(): TurnResult {
    if (!paused && message.contains(UPGRADE_MSG_MARKER)) {
        return TurnResult.UpgradeRequired(UPGRADE_SAFE_MESSAGE)
    }
    val card = toCard()
    return if (card != null) TurnResult.Card(card) else TurnResult.Reply(message)
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
