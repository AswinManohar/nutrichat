package app.mealsy.android.ui.chat

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/**
 * Wraps [SpeechRecognizer] as the chat bar's voice-recording state: a timer
 * start time, the live waveform levels, and the transcript. Must be used from
 * the main thread (a [SpeechRecognizer] requirement).
 *
 * @param onTranscript Called once when a recording finishes: `text` is the
 *   resolved transcript (null when nothing was recognised) and `sent` is true
 *   when the user tapped send (as opposed to the recognizer ending on its own).
 */
class SpeechRecorder(
    private val context: Context,
    private val onTranscript: (text: String?, sent: Boolean) -> Unit,
) {
    var recording by mutableStateOf(false)
        private set
    var levels by mutableStateOf(emptyLevels())
        private set
    var startedAtMs by mutableStateOf(0L)
        private set

    private var recognizer: SpeechRecognizer? = null
    private val transcript = TranscriptAccumulator()
    private var finishing = false

    /** Starts listening. No-op when already recording. */
    fun start() {
        if (recording) return
        transcript.reset()
        finishing = false
        levels = emptyLevels()
        startedAtMs = System.currentTimeMillis()
        val sr = SpeechRecognizer.createSpeechRecognizer(context)
        recognizer = sr
        sr.setRecognitionListener(listener)
        sr.startListening(
            Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            },
        )
        recording = true
    }

    /** Stops listening; the final transcript is delivered as a send. */
    fun finish() {
        if (!recording) return
        finishing = true
        recognizer?.stopListening()
    }

    /** Cancels the recognizer and discards everything. */
    fun discard() {
        release()
        transcript.reset()
    }

    /** Releases the recognizer (call from `onDispose`). */
    fun release() {
        recognizer?.cancel()
        recognizer?.destroy()
        recognizer = null
        recording = false
        finishing = false
    }

    private fun complete() {
        val sent = finishing
        val text = transcript.resolve()
        release()
        transcript.reset()
        onTranscript(text, sent)
    }

    private val listener =
        object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) = Unit

            override fun onBeginningOfSpeech() = Unit

            override fun onRmsChanged(rmsdB: Float) {
                levels = pushLevel(levels, normalizeRms(rmsdB))
            }

            override fun onBufferReceived(buffer: ByteArray?) = Unit

            override fun onEndOfSpeech() = Unit

            override fun onError(error: Int) = complete()

            override fun onResults(results: Bundle?) {
                transcript.onFinal(
                    results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull(),
                )
                complete()
            }

            override fun onPartialResults(partialResults: Bundle?) {
                transcript.onPartial(
                    partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull(),
                )
            }

            override fun onEvent(
                eventType: Int,
                params: Bundle?,
            ) = Unit
        }
}
