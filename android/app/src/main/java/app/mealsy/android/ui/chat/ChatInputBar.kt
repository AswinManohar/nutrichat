package app.mealsy.android.ui.chat

import android.graphics.Bitmap
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.mealsy.android.R
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.LocalReducedMotion
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.design.theme.mealsyTween

/**
 * Live voice-recording state shown by [ChatInputBar].
 *
 * @property recording Whether a voice note is being recorded.
 * @property available Whether a speech recognizer exists on this device.
 * @property elapsedMs Time since recording started.
 * @property levels [WAVEFORM_BARS] mic levels in 0..1, newest last.
 */
data class VoiceUiState(
    val recording: Boolean = false,
    val available: Boolean = true,
    val elapsedMs: Long = 0L,
    val levels: List<Float> = emptyLevels(),
)

/**
 * The chat composer, per the "Mealsy Chat Bar" design: attach button, a pill
 * with the text field and camera, and a single primary button that is an olive
 * mic when idle and an ink send arrow otherwise. A picked photo previews above
 * the bar; while recording, the pill shows a timer and waveform and the attach
 * button becomes delete.
 */
@Composable
internal fun ChatInputBar(
    input: String,
    onInputChange: (String) -> Unit,
    enabled: Boolean,
    attachment: Bitmap?,
    voice: VoiceUiState,
    notice: String?,
    onAttachClick: () -> Unit,
    onCameraClick: () -> Unit,
    onRemoveAttachment: () -> Unit,
    onMicClick: () -> Unit,
    onDiscardRecording: () -> Unit,
    onFinishRecording: () -> Unit,
    onSend: () -> Unit,
    modifier: Modifier = Modifier,
    focusRequester: FocusRequester = remember { FocusRequester() },
) {
    val mode = composerMode(input, attachment != null, voice.recording, voice.available)
    Column(
        modifier = modifier.fillMaxWidth().padding(horizontal = 12.dp).alpha(if (enabled) 1f else DISABLED_ALPHA),
    ) {
        if (notice != null && !voice.recording) {
            Text(
                text = notice,
                style = MealsyType.label,
                color = MealsyTheme.colors.muted,
                modifier = Modifier.padding(start = 18.dp, bottom = 4.dp),
            )
        }
        if (attachment != null && !voice.recording) {
            AttachmentPreview(bitmap = attachment, enabled = enabled, onRemove = onRemoveAttachment)
        }
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 6.dp, bottom = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (voice.recording) {
                DeleteButton(enabled = enabled, onClick = onDiscardRecording)
            } else {
                AttachButton(enabled = enabled, onClick = onAttachClick)
            }
            Pill(
                input = input,
                onInputChange = onInputChange,
                enabled = enabled,
                voice = voice,
                focusRequester = focusRequester,
                onCameraClick = onCameraClick,
                onSend = onSend,
                modifier = Modifier.weight(1f),
            )
            PrimaryButton(
                mode = mode,
                enabled = enabled,
                onMic = onMicClick,
                onSend = onSend,
                onFinish = onFinishRecording,
            )
        }
    }
}

private const val DISABLED_ALPHA = 0.35f

@Composable
private fun CircleButton(
    description: String,
    enabled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Box(
        modifier =
            modifier
                .clip(CircleShape)
                .clickable(enabled = enabled, role = Role.Button, onClick = onClick)
                .semantics { contentDescription = description },
        contentAlignment = Alignment.Center,
    ) { content() }
}

@Composable
private fun AttachButton(
    enabled: Boolean,
    onClick: () -> Unit,
) {
    val colors = MealsyTheme.colors
    CircleButton(
        description = stringResource(R.string.chat_attach_description),
        enabled = enabled,
        onClick = onClick,
        modifier = Modifier.size(44.dp).border(1.dp, colors.hairline, CircleShape),
    ) {
        Icon(imageVector = MealsyIcons.Plus, contentDescription = null, tint = colors.ink, modifier = Modifier.size(18.dp))
    }
}

@Composable
private fun DeleteButton(
    enabled: Boolean,
    onClick: () -> Unit,
) {
    val colors = MealsyTheme.colors
    CircleButton(
        description = stringResource(R.string.chat_discard_recording_description),
        enabled = enabled,
        onClick = onClick,
        modifier = Modifier.size(44.dp).border(1.dp, colors.terracotta, CircleShape),
    ) {
        Icon(imageVector = MealsyIcons.Trash, contentDescription = null, tint = colors.terracotta, modifier = Modifier.size(18.dp))
    }
}

@Composable
private fun PrimaryButton(
    mode: ComposerMode,
    enabled: Boolean,
    onMic: () -> Unit,
    onSend: () -> Unit,
    onFinish: () -> Unit,
) {
    val colors = MealsyTheme.colors
    val isMic = mode == ComposerMode.Mic || mode == ComposerMode.MicUnavailable
    val background by animateColorAsState(if (isMic) colors.olive else colors.ink, mealsyTween(150), label = "primaryBg")
    val description =
        stringResource(
            when (mode) {
                ComposerMode.Mic -> R.string.chat_mic_description
                ComposerMode.MicUnavailable -> R.string.chat_mic_unavailable_description
                ComposerMode.Send -> R.string.chat_send_description
                ComposerMode.Recording -> R.string.chat_finish_recording_description
            },
        )
    val clickable = enabled && mode != ComposerMode.MicUnavailable
    Box(
        modifier =
            Modifier
                .size(48.dp)
                .clip(CircleShape)
                .background(background)
                .alpha(if (mode == ComposerMode.MicUnavailable) DISABLED_ALPHA else 1f)
                .clickable(enabled = clickable, role = Role.Button) {
                    when (mode) {
                        ComposerMode.Mic -> onMic()
                        ComposerMode.Send -> onSend()
                        ComposerMode.Recording -> onFinish()
                        ComposerMode.MicUnavailable -> Unit
                    }
                }.semantics { contentDescription = description },
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = if (isMic) ChatBarIcons.Mic else MealsyIcons.Send,
            contentDescription = null,
            tint = if (isMic) colors.oliveText else colors.canvas,
            modifier = Modifier.size(20.dp),
        )
    }
}

@Composable
private fun Pill(
    input: String,
    onInputChange: (String) -> Unit,
    enabled: Boolean,
    voice: VoiceUiState,
    focusRequester: FocusRequester,
    onCameraClick: () -> Unit,
    onSend: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    var focused by remember { mutableStateOf(false) }
    val active = focused || input.isNotEmpty() || voice.recording
    val borderColor by animateColorAsState(if (active) colors.ink else colors.hairline, mealsyTween(150), label = "pillBorder")
    Row(
        modifier =
            modifier
                .heightIn(min = 48.dp)
                .clip(MealsyShapes.pill)
                .background(colors.surface)
                .border(BorderStroke(1.dp, borderColor), MealsyShapes.pill)
                .padding(start = 18.dp, end = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        if (voice.recording) {
            RecordingContent(voice)
        } else {
            BasicTextField(
                value = input,
                onValueChange = onInputChange,
                modifier =
                    Modifier
                        .weight(1f)
                        .focusRequester(focusRequester)
                        .onFocusChanged { focused = it.isFocused },
                enabled = enabled,
                singleLine = true,
                textStyle = MealsyType.button.copy(fontSize = 15.sp, fontWeight = FontWeight.Normal, color = colors.ink),
                cursorBrush = SolidColor(colors.ink),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = { onSend() }),
                decorationBox = { inner ->
                    Box(contentAlignment = Alignment.CenterStart) {
                        if (input.isEmpty()) {
                            Text(
                                text = stringResource(R.string.chat_input_placeholder),
                                style = MealsyType.button.copy(fontSize = 15.sp, fontWeight = FontWeight.Normal),
                                color = colors.inactive,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                        inner()
                    }
                },
            )
            CircleButton(
                description = stringResource(R.string.chat_camera_description),
                enabled = enabled,
                onClick = onCameraClick,
                modifier = Modifier.size(36.dp),
            ) {
                Icon(imageVector = ChatBarIcons.Camera, contentDescription = null, tint = colors.muted, modifier = Modifier.size(19.dp))
            }
        }
    }
}

@Composable
private fun androidx.compose.foundation.layout.RowScope.RecordingContent(voice: VoiceUiState) {
    val colors = MealsyTheme.colors
    val timer = formatRecordingTime(voice.elapsedMs)
    val reduced = LocalReducedMotion.current
    val blink by
        rememberInfiniteTransition(label = "blink").animateFloat(
            initialValue = 1f,
            targetValue = if (reduced) 1f else 0.3f,
            animationSpec = infiniteRepeatable(tween(600), RepeatMode.Reverse),
            label = "dotAlpha",
        )
    val description = stringResource(R.string.chat_recording_description, timer)
    Row(
        modifier = Modifier.weight(1f).clearAndSetSemantics { contentDescription = description },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(8.dp).alpha(blink).background(colors.terracotta, CircleShape))
        Text(
            text = timer,
            style = MealsyType.button.copy(fontSize = 15.sp, fontWeight = FontWeight.Normal),
            color = colors.ink,
            modifier = Modifier.padding(start = 10.dp),
        )
        Spacer(Modifier.weight(1f))
        Waveform(levels = voice.levels, color = colors.ink, modifier = Modifier.padding(end = 12.dp))
    }
}

@Composable
private fun Waveform(
    levels: List<Float>,
    color: Color,
    modifier: Modifier = Modifier,
) {
    val barWidth = 2.5.dp
    val gap = 2.dp
    Canvas(
        modifier = modifier.size(width = barWidth * WAVEFORM_BARS + gap * (WAVEFORM_BARS - 1), height = 22.dp),
    ) {
        val w = barWidth.toPx()
        val g = gap.toPx()
        levels.takeLast(WAVEFORM_BARS).forEachIndexed { i, level ->
            val h = (4.dp.toPx() + level.coerceIn(0f, 1f) * 18.dp.toPx())
            drawRoundRect(
                color = color,
                topLeft = Offset(i * (w + g), (size.height - h) / 2f),
                size = Size(w, h),
                cornerRadius = CornerRadius(w / 2f),
            )
        }
    }
}

@Composable
private fun AttachmentPreview(
    bitmap: Bitmap,
    enabled: Boolean,
    onRemove: () -> Unit,
) {
    val colors = MealsyTheme.colors
    Row(
        modifier =
            Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(16.dp))
                .background(colors.surface)
                .padding(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Image(
            bitmap = bitmap.asImageBitmap(),
            contentDescription = stringResource(R.string.chat_attachment_thumbnail_description),
            contentScale = ContentScale.Crop,
            modifier = Modifier.size(48.dp).clip(RoundedCornerShape(10.dp)),
        )
        Column(modifier = Modifier.weight(1f).padding(horizontal = 12.dp)) {
            Text(
                text = stringResource(R.string.chat_attachment_title),
                style = MealsyType.body.copy(fontSize = 14.sp, fontWeight = FontWeight.Medium),
                color = colors.ink,
            )
            Text(
                text = stringResource(R.string.chat_attachment_subtitle),
                style = MealsyType.label,
                color = colors.muted,
            )
        }
        CircleButton(
            description = stringResource(R.string.chat_remove_photo_description),
            enabled = enabled,
            onClick = onRemove,
            modifier = Modifier.size(48.dp),
        ) {
            Icon(imageVector = MealsyIcons.Close, contentDescription = null, tint = colors.muted, modifier = Modifier.size(16.dp))
        }
    }
}
