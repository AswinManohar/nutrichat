package app.mealsy.android.ui.chat

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import app.mealsy.android.ui.AppScreenshotTestBase
import app.mealsy.domain.ConfirmationCard
import app.mealsy.domain.CardItem
import app.mealsy.domain.PastelTone
import org.junit.Test

/**
 * Goldens for [ChatScreen]'s designed states, light and dark.
 * [EmptyState], [ChatMessageRow], and [ConfirmCardView] are rendered
 * directly with hand-built state — no ViewModel, no network, deterministic
 * frames. The candidate-correction sheet is covered by
 * `core/ui`'s `CandidatePickerSheetContent` golden and is not duplicated
 * here.
 */
class ChatScreenGoldenTest : AppScreenshotTestBase() {

    // --- Empty state ---------------------------------------------------------

    @Test
    fun chatEmpty_light() = captureMealsy("Chat_empty", false) {
        EmptyState(onSuggestionTapped = {})
    }

    @Test
    fun chatEmpty_dark() = captureMealsy("Chat_empty", true) {
        EmptyState(onSuggestionTapped = {})
    }

    // --- Typing indicator ------------------------------------------------------

    @Composable
    private fun renderRow(msg: ChatMsg, sending: Boolean = false) {
        ChatMessageRow(
            msg = msg,
            timestamp = "07:39 PM",
            sending = sending,
            savingMeal = false,
            onEditQty = { _, _ -> },
            onRemoveItem = {},
            onSetMealType = {},
            onSetPortion = {},
            onSwapCandidate = { _, _ -> },
            onDecompose = {},
            onCombine = {},
            onConfirm = {},
            onCancel = {},
            onSaveAsMyMeal = {},
            onFeedback = { _, _ -> },
        )
    }

    @Test
    fun chatTypingIndicator_light() = captureMealsy("Chat_typingIndicator", false) {
        androidx.compose.foundation.layout.Row(modifier = Modifier.fillMaxWidth()) {
            app.mealsy.android.design.components.TypingIndicator()
        }
    }

    @Test
    fun chatTypingIndicator_dark() = captureMealsy("Chat_typingIndicator", true) {
        androidx.compose.foundation.layout.Row(modifier = Modifier.fillMaxWidth()) {
            app.mealsy.android.design.components.TypingIndicator()
        }
    }

    // --- Coach reply with macro tags -------------------------------------------

    private fun coachWithTags() = ChatMsg.Coach(
        id = "coach_1",
        timestampMillis = 0L,
        text = "Logged breakfast. That's a solid start to the day.",
        tags = listOf(
            MacroTag("412 kcal", PastelTone.Butter),
            MacroTag("28g protein", PastelTone.Leaf),
        ),
    )

    @Test
    fun chatCoachReplyWithTags_light() = captureMealsy("Chat_coachReplyWithTags", false) {
        renderRow(coachWithTags())
    }

    @Test
    fun chatCoachReplyWithTags_dark() = captureMealsy("Chat_coachReplyWithTags", true) {
        renderRow(coachWithTags())
    }

    // --- Over-quota card (UpgradeNotice) ----------------------------------------

    private fun upgradeNotice() = ChatMsg.UpgradeNotice(
        id = "upgrade_1",
        timestampMillis = 0L,
        text = "You've used all your free logs for today. Upgrade to keep going.",
    )

    @Test
    fun chatOverQuotaCard_light() = captureMealsy("Chat_overQuotaCard", false) {
        renderRow(upgradeNotice())
    }

    @Test
    fun chatOverQuotaCard_dark() = captureMealsy("Chat_overQuotaCard", true) {
        renderRow(upgradeNotice())
    }

    // --- Confirm card: default ---------------------------------------------------

    private fun eggItem() = CardItem(
        foodName = "Egg, whole, cooked, fried",
        qtyG = 100.0,
        targetQtyG = 100.0,
        kcal = 155.0,
        proteinG = 13.0,
        carbsG = 1.1,
        fatG = 11.0,
        fiberG = 0.0,
        fdcId = 12345L,
    )

    private fun defaultCard() = ConfirmationCard(
        message = "",
        mealType = "breakfast",
        portion = 1.0,
        items = listOf(eggItem()),
    )

    private fun cardMsg(card: ConfirmationCard, state: CardState) = ChatMsg.Card(
        id = "card_1",
        timestampMillis = 0L,
        card = card,
        state = state,
    )

    @Test
    fun chatConfirmCardDefault_light() = captureMealsy("Chat_confirmCardDefault", false) {
        renderRow(cardMsg(defaultCard(), CardState.Active))
    }

    @Test
    fun chatConfirmCardDefault_dark() = captureMealsy("Chat_confirmCardDefault", true) {
        renderRow(cardMsg(defaultCard(), CardState.Active))
    }

    // --- Confirm card: estimated + low-confidence item ---------------------------

    private fun estimatedLowConfidenceCard() = ConfirmationCard(
        message = "",
        mealType = "lunch",
        portion = 1.0,
        items = listOf(
            eggItem(),
            CardItem(
                foodName = "Rice, white, long-grain, regular, cooked",
                qtyG = 200.0,
                targetQtyG = 200.0,
                kcal = 260.0,
                proteinG = 5.0,
                carbsG = 56.0,
                fatG = 0.4,
                fiberG = 1.0,
                fdcId = 2L,
                estimated = true,
                candidates = listOf("White rice", "Brown rice"),
                confidence = 0.4,
            ),
        ),
    )

    @Test
    fun chatConfirmCardEstimatedLowConfidence_light() =
        captureMealsy("Chat_confirmCardEstimatedLowConfidence", false) {
            renderRow(cardMsg(estimatedLowConfidenceCard(), CardState.Active))
        }

    @Test
    fun chatConfirmCardEstimatedLowConfidence_dark() =
        captureMealsy("Chat_confirmCardEstimatedLowConfidence", true) {
            renderRow(cardMsg(estimatedLowConfidenceCard(), CardState.Active))
        }

    // --- Composite dish grouping --------------------------------------------------

    private fun compositeDishCard() = ConfirmationCard(
        message = "",
        mealType = "lunch",
        portion = 1.0,
        items = listOf(
            CardItem(
                foodName = "Chicken, broilers or fryers, breast, meat only, cooked, roasted",
                qtyG = 150.0,
                targetQtyG = 150.0,
                kcal = 231.0,
                proteinG = 43.0,
                carbsG = 0.0,
                fatG = 5.0,
                fiberG = 0.0,
                fdcId = 1L,
                sourceDish = "Chicken caesar salad",
            ),
            CardItem(
                foodName = "Lettuce, cos or romaine, raw",
                qtyG = 80.0,
                targetQtyG = 80.0,
                kcal = 14.0,
                proteinG = 1.0,
                carbsG = 2.6,
                fatG = 0.2,
                fiberG = 1.7,
                fdcId = 2L,
                sourceDish = "Chicken caesar salad",
            ),
        ),
    )

    @Test
    fun chatCompositeDishGrouping_light() = captureMealsy("Chat_compositeDishGrouping", false) {
        renderRow(cardMsg(compositeDishCard(), CardState.Active))
    }

    @Test
    fun chatCompositeDishGrouping_dark() = captureMealsy("Chat_compositeDishGrouping", true) {
        renderRow(cardMsg(compositeDishCard(), CardState.Active))
    }

    // --- Collapsed older cards: Logged / Not logged / Discarded -------------------

    @Test
    fun chatCollapsedCardLogged_light() = captureMealsy("Chat_collapsedCardLogged", false) {
        renderRow(cardMsg(defaultCard(), CardState.Logged(label = "Egg", kcal = 155)))
    }

    @Test
    fun chatCollapsedCardLogged_dark() = captureMealsy("Chat_collapsedCardLogged", true) {
        renderRow(cardMsg(defaultCard(), CardState.Logged(label = "Egg", kcal = 155)))
    }

    @Test
    fun chatCollapsedCardNotLogged_light() = captureMealsy("Chat_collapsedCardNotLogged", false) {
        renderRow(cardMsg(defaultCard(), CardState.NotLogged))
    }

    @Test
    fun chatCollapsedCardNotLogged_dark() = captureMealsy("Chat_collapsedCardNotLogged", true) {
        renderRow(cardMsg(defaultCard(), CardState.NotLogged))
    }

    @Test
    fun chatCollapsedCardDiscarded_light() = captureMealsy("Chat_collapsedCardDiscarded", false) {
        renderRow(cardMsg(defaultCard(), CardState.Discarded))
    }

    @Test
    fun chatCollapsedCardDiscarded_dark() = captureMealsy("Chat_collapsedCardDiscarded", true) {
        renderRow(cardMsg(defaultCard(), CardState.Discarded))
    }
}
