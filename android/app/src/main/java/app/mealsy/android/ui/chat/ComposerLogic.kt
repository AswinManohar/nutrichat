package app.mealsy.android.ui.chat

/** What the chat bar's primary (right-hand) button currently does. */
enum class ComposerMode {
    /** Idle: olive mic, starts voice recording. */
    Mic,

    /** Idle but no speech recognizer is registered: disabled olive mic. */
    MicUnavailable,

    /** Text and/or a photo is ready: ink send arrow. */
    Send,

    /** Voice recording in progress: ink send arrow that finishes the note. */
    Recording,
}

/** Number of bars in the recording waveform. */
const val WAVEFORM_BARS = 18

/**
 * The composer's mode machine (idle -> typing/attached -> send, idle ->
 * recording -> send/discard).
 *
 * Recording always wins; otherwise any non-blank text or an attached photo
 * means "send" (a photo alone enables send); otherwise the mic.
 */
fun composerMode(
    text: String,
    hasAttachment: Boolean,
    recording: Boolean,
    recognizerAvailable: Boolean,
): ComposerMode =
    when {
        recording -> ComposerMode.Recording
        text.isNotBlank() || hasAttachment -> ComposerMode.Send
        recognizerAvailable -> ComposerMode.Mic
        else -> ComposerMode.MicUnavailable
    }

/** Formats elapsed recording time as `m:ss`. */
fun formatRecordingTime(elapsedMs: Long): String {
    val totalSeconds = (elapsedMs / 1000).coerceAtLeast(0)
    return "${totalSeconds / 60}:${(totalSeconds % 60).toString().padStart(2, '0')}"
}

/**
 * Maps a `RecognitionListener.onRmsChanged` value (roughly -2..10 dB) to 0..1.
 */
fun normalizeRms(rmsDb: Float): Float = ((rmsDb + 2f) / 12f).coerceIn(0f, 1f)

/**
 * Pushes a new mic level into the waveform: the bars scroll left and the newest
 * bar is an exponential blend of the previous newest bar and [level], so the
 * 18 bars read as a smooth trail rather than jitter.
 */
fun pushLevel(
    levels: List<Float>,
    level: Float,
): List<Float> {
    val previous = levels.lastOrNull() ?: 0f
    val smoothed = previous * 0.5f + level.coerceIn(0f, 1f) * 0.5f
    return (levels + smoothed).takeLast(WAVEFORM_BARS)
}

/** A flat waveform (all bars at the minimum height). */
fun emptyLevels(): List<Float> = List(WAVEFORM_BARS) { 0f }

/**
 * Collects a speech recognizer's partial and final transcripts and decides what
 * to send when the user taps send: the final transcript, else the latest
 * partial, else nothing.
 */
class TranscriptAccumulator {
    private var partial: String = ""
    private var final: String = ""

    fun onPartial(text: String?) {
        if (!text.isNullOrBlank()) partial = text.trim()
    }

    fun onFinal(text: String?) {
        if (!text.isNullOrBlank()) final = text.trim()
    }

    /** The transcript to send, or null when nothing was recognised. */
    fun resolve(): String? = final.ifBlank { partial }.ifBlank { null }

    fun reset() {
        partial = ""
        final = ""
    }
}
