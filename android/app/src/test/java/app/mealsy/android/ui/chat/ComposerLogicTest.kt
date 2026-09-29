package app.mealsy.android.ui.chat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ComposerLogicTest {
    private fun mode(
        text: String = "",
        attached: Boolean = false,
        recording: Boolean = false,
        available: Boolean = true,
    ) = composerMode(text, attached, recording, available)

    @Test
    fun idleIsMic() = assertEquals(ComposerMode.Mic, mode())

    @Test
    fun whitespaceOnlyStaysMic() = assertEquals(ComposerMode.Mic, mode(text = "   "))

    @Test
    fun typingIsSend() = assertEquals(ComposerMode.Send, mode(text = "eggs"))

    @Test
    fun attachmentEnablesSendWithEmptyText() = assertEquals(ComposerMode.Send, mode(attached = true))

    @Test
    fun recordingWinsOverTextAndAttachment() = assertEquals(ComposerMode.Recording, mode(text = "x", attached = true, recording = true))

    @Test
    fun recognizerUnavailableDisablesMicButKeepsSend() {
        assertEquals(ComposerMode.MicUnavailable, mode(available = false))
        assertEquals(ComposerMode.Send, mode(text = "eggs", available = false))
    }

    @Test
    fun timerFormatsMinutesAndSeconds() {
        assertEquals("0:00", formatRecordingTime(0))
        assertEquals("0:03", formatRecordingTime(3_400))
        assertEquals("1:05", formatRecordingTime(65_000))
        assertEquals("0:00", formatRecordingTime(-5))
    }

    @Test
    fun rmsNormalisesAndClamps() {
        assertEquals(0f, normalizeRms(-10f), 0f)
        assertEquals(1f, normalizeRms(30f), 0f)
        assertEquals(0.5f, normalizeRms(4f), 0.001f)
    }

    @Test
    fun waveformKeepsExactlyEighteenBarsNewestLast() {
        var levels = emptyLevels()
        repeat(40) { levels = pushLevel(levels, 0f) }
        levels = pushLevel(levels, 1f)
        assertEquals(WAVEFORM_BARS, levels.size)
        assertEquals(true, levels.last() > levels[levels.size - 2])
        assertEquals(true, levels.all { it in 0f..1f })
    }

    @Test
    fun transcriptPrefersFinalThenPartialThenNothing() {
        val t = TranscriptAccumulator()
        assertNull(t.resolve())
        t.onPartial("two eg")
        assertEquals("two eg", t.resolve())
        t.onFinal("two eggs")
        assertEquals("two eggs", t.resolve())
        t.onFinal("")
        assertEquals("two eggs", t.resolve())
        t.reset()
        assertNull(t.resolve())
    }

    @Test
    fun blankFinalFallsBackToPartial() {
        val t = TranscriptAccumulator()
        t.onPartial("toast")
        t.onFinal("  ")
        assertEquals("toast", t.resolve())
    }
}
