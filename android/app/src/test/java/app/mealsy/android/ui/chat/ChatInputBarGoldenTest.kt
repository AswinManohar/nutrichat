package app.mealsy.android.ui.chat

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import app.mealsy.android.ui.AppScreenshotTestBase
import org.junit.Test

/** Goldens for [ChatInputBar]: idle, typing, attached, recording (light + dark), plus idle at font 2.0. */
class ChatInputBarGoldenTest : AppScreenshotTestBase() {
    private fun photo(): Bitmap =
        Bitmap.createBitmap(96, 96, Bitmap.Config.ARGB_8888).also { bmp ->
            val canvas = Canvas(bmp)
            val paint = Paint()
            val colors = intArrayOf(0xFFB9503A.toInt(), 0xFFE8C46A.toInt(), 0xFF8FA65A.toInt(), 0xFFD9D2B8.toInt())
            for (i in 0 until 4) {
                paint.color = colors[i]
                canvas.drawRect((i % 2) * 48f, (i / 2) * 48f, (i % 2) * 48f + 48f, (i / 2) * 48f + 48f, paint)
            }
            paint.color = Color.WHITE
        }

    @Composable
    private fun Bar(
        input: String = "",
        attached: Boolean = false,
        voice: VoiceUiState = VoiceUiState(),
    ) {
        val bitmap = remember { photo() }
        ChatInputBar(
            input = input,
            onInputChange = {},
            enabled = true,
            attachment = if (attached) bitmap else null,
            voice = voice,
            notice = null,
            onAttachClick = {},
            onCameraClick = {},
            onRemoveAttachment = {},
            onMicClick = {},
            onDiscardRecording = {},
            onFinishRecording = {},
            onSend = {},
        )
    }

    private val recording =
        VoiceUiState(
            recording = true,
            elapsedMs = 3_000,
            levels = List(WAVEFORM_BARS) { i -> (kotlin.math.abs(kotlin.math.sin(i * 0.9)) * 0.9).toFloat() },
        )

    @Test fun idle_light() = captureMealsy("ChatBar_idle", false) { Bar() }

    @Test fun idle_dark() = captureMealsy("ChatBar_idle", true) { Bar() }

    @Test fun idle_font2() = captureMealsy("ChatBar_idle", false, fontScale = 2f) { Bar() }

    @Test fun typing_light() = captureMealsy("ChatBar_typing", false) { Bar(input = "Pasta with meatballs") }

    @Test fun typing_dark() = captureMealsy("ChatBar_typing", true) { Bar(input = "Pasta with meatballs") }

    @Test fun attached_light() = captureMealsy("ChatBar_attached", false) { Bar(attached = true) }

    @Test fun attached_dark() = captureMealsy("ChatBar_attached", true) { Bar(attached = true) }

    @Test fun recording_light() = captureMealsy("ChatBar_recording", false) { Bar(voice = recording) }

    @Test fun recording_dark() = captureMealsy("ChatBar_recording", true) { Bar(voice = recording) }

    @Test
    fun unavailable_light() = captureMealsy("ChatBar_unavailable", false) { Bar(voice = VoiceUiState(available = false)) }
}
