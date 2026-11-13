package app.mealsy.android.ui.chat

import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.Composable
import app.mealsy.android.ui.AppScreenshotTestBase
import app.mealsy.data.api.ReadbackDto
import org.junit.Test

/** Goldens for [ReadbackChips] under a coach reply, light and dark. */
class ReadbackChipsGoldenTest : AppScreenshotTestBase() {
    @Composable
    private fun reply(kind: String) =
        Column {
            CoachReply(
                text = "Is it right that you have celiac disease?",
                tags = emptyList(),
                timestamp = "07:39 PM",
            )
            ReadbackChips(ReadbackDto("e-1", "Is it right that you have celiac disease?", kind), onAnswer = {})
        }

    @Test
    fun readbackAdd_light() = captureMealsy("ReadbackChips_add", false) { reply("add") }

    @Test
    fun readbackAdd_dark() = captureMealsy("ReadbackChips_add", true) { reply("add") }

    @Test
    fun readbackRetire_light() = captureMealsy("ReadbackChips_retire", false) { reply("retire") }

    @Test
    fun readbackRetire_dark() = captureMealsy("ReadbackChips_retire", true) { reply("retire") }
}
