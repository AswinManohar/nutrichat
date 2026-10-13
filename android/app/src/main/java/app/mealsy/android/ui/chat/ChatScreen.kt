package app.mealsy.android.ui.chat

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.ImageDecoder
import android.net.Uri
import android.speech.SpeechRecognizer
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.IconButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.R
import app.mealsy.android.design.components.ChatBubble
import app.mealsy.android.design.components.ChatBubbleAuthor
import app.mealsy.android.design.components.CircleIconButton
import app.mealsy.android.design.components.FilterChipPill
import app.mealsy.android.design.components.InkToast
import app.mealsy.android.design.components.MarkdownText
import app.mealsy.android.design.components.TagChip
import app.mealsy.android.design.components.TagTone
import app.mealsy.android.design.components.TypingIndicator
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.mascot.Olli
import app.mealsy.android.design.mascot.OlliSize
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.design.theme.mealsyTween
import app.mealsy.android.design.theme.motionDurationMs
import app.mealsy.domain.PastelTone
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.IOException
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * The chat screen: header, inline transcript (including the confirmation
 * card as a first-class transcript entry), and input bar.
 *
 * Laid out like a full-screen Claude conversation: `AppNav` hides the bottom
 * nav pill here, and the header's back button returns to Home. The today totals/goals header that used to live here
 * (`TodayHeader`) was retired — Home owns that display now and refreshes
 * itself via `TodayRefreshSignal` on `ON_RESUME`, so this screen no longer
 * needs its own refresh hook for it.
 *
 * @param quickLog Whether this screen was opened via the Home FAB's
 *   "quick log" shortcut. When true, the message input requests focus and an
 *   [InkToast] confirms the shortcut for 2 seconds — both fire exactly once
 *   per screen instance (see [rememberSaveable] guard below), so a
 *   recomposition or configuration change doesn't replay them.
 * @param onBack Invoked by the header's back button; returns to Home.
 */
@Composable
fun ChatScreen(
    quickLog: Boolean = false,
    onBack: () -> Unit = {},
    viewModel: ChatViewModel = hiltViewModel(),
) {
    val messages by viewModel.messages.collectAsStateWithLifecycle()
    val sending by viewModel.sending.collectAsStateWithLifecycle()
    val offline by viewModel.offline.collectAsStateWithLifecycle()
    val savingMeal by viewModel.savingMeal.collectAsStateWithLifecycle()
    val undoToast by viewModel.undoToast.collectAsStateWithLifecycle()

    var input by remember { mutableStateOf("") }
    var showCameraSheet by remember { mutableStateOf(false) }

    val inputFocusRequester = remember { FocusRequester() }
    var quickLogConsumed by rememberSaveable { mutableStateOf(false) }
    var showQuickLogToast by remember { mutableStateOf(false) }
    LaunchedEffect(quickLog) {
        if (quickLog && !quickLogConsumed) {
            quickLogConsumed = true
            inputFocusRequester.requestFocus()
            showQuickLogToast = true
            delay(2_000)
            showQuickLogToast = false
        }
    }

    // One-shot toast events from the view model (logged/save results, etc).
    var activeToast by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) {
        viewModel.toasts.collect { text ->
            activeToast = text
            delay(2_500)
            if (activeToast == text) activeToast = null
        }
    }

    // POST_NOTIFICATIONS is requested contextually now (batch J: the settings
    // reminder-toggle flow), not as a cold system dialog on first chat entry
    // (#44) — that used to fire right when the user was trying to type their
    // first meal, before they had any reason to want notifications.
    val context = LocalContext.current

    // Speech recognition is optional: when no recognizer is registered the
    // idle mic stays in the layout, disabled ("Voice input unavailable").
    val recognizerAvailable = remember { SpeechRecognizer.isRecognitionAvailable(context) }
    var attachment by remember { mutableStateOf<Bitmap?>(null) }
    var notice by remember { mutableStateOf<String?>(null) }
    val didntCatch = stringResource(R.string.chat_didnt_catch_that)
    val scope = rememberCoroutineScope()
    val recorder =
        remember {
            SpeechRecorder(context) { text, sent ->
                when {
                    text == null -> notice = didntCatch
                    sent -> viewModel.send(text)
                    // The recognizer ended on its own (silence): keep the words
                    // in the field for the user to review rather than auto-send.
                    else -> input = if (input.isEmpty()) text else "$input $text"
                }
            }
        }
    DisposableEffect(recorder) { onDispose { recorder.release() } }
    LaunchedEffect(notice) {
        if (notice != null) {
            delay(2_500)
            notice = null
        }
    }
    var elapsedMs by remember { mutableStateOf(0L) }
    LaunchedEffect(recorder.recording) {
        while (recorder.recording) {
            elapsedMs = System.currentTimeMillis() - recorder.startedAtMs
            delay(200)
        }
    }
    val micPermissionLauncher =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) recorder.start()
        }
    val photoPicker =
        rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
            if (uri != null) {
                scope.launch { attachment = decodeAttachment(context, uri) ?: attachment }
            }
        }

    if (showCameraSheet) {
        CameraSheet(
            onUsePhoto = { bitmap ->
                showCameraSheet = false
                attachment = bitmap
            },
            onDismiss = { showCameraSheet = false },
        )
    }

    val colors = MealsyTheme.colors
    val listState = rememberLazyListState()
    // The typing indicator is appended as a synthetic extra row (key
    // "typing") after `messages` below, not as a `ChatMsg` — so when it's
    // showing, the "last item" to scroll to is one past `messages.size - 1`,
    // not `messages.size - 1` itself (#49: this used to leave the typing row
    // sitting below the fold).
    val lastCardForScroll = messages.lastOrNull() as? ChatMsg.Card
    val showTypingRow = sending && lastCardForScroll?.state !is CardState.Swapping
    LaunchedEffect(messages.size, showTypingRow) {
        if (messages.isEmpty() && !showTypingRow) return@LaunchedEffect
        val lastIndex = if (showTypingRow) messages.size else messages.size - 1
        listState.animateScrollToItem(lastIndex.coerceAtLeast(0))
    }

    Box(modifier = Modifier.fillMaxSize().background(colors.canvas)) {
        // No bottom nav pill on this screen, so the composer only clears the
        // keyboard (`imePadding()`) or, at rest, the system navigation bar.
        // `imePadding()` consumes the overlapping inset, so the composer's
        // `navigationBarsPadding()` adds nothing while the keyboard is open.
        Column(modifier = Modifier.fillMaxSize().imePadding()) {
            ChatHeader(onBack = onBack)

            if (messages.isEmpty() && !sending) {
                EmptyState(
                    modifier = Modifier.weight(1f),
                    onSuggestionTapped = { suggestion -> input = suggestion },
                )
            } else {
                LazyColumn(
                    state = listState,
                    modifier = Modifier.weight(1f).fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    contentPadding =
                        androidx.compose.foundation.layout.PaddingValues(
                            horizontal = 18.dp,
                            vertical = 16.dp,
                        ),
                ) {
                    items(messages, key = { it.id }) { msg ->
                        val isLastOfRun = isLastOfAuthorRun(messages, msg)
                        ChatMessageRow(
                            msg = msg,
                            timestamp = if (isLastOfRun) formatTimestamp(msg.timestampMillis) else null,
                            sending = sending,
                            savingMeal = savingMeal,
                            onEditQty = viewModel::editQty,
                            onRemoveItem = viewModel::removeItem,
                            onSetMealType = viewModel::setMealType,
                            onSetPortion = viewModel::setPortion,
                            onSwapCandidate = viewModel::onSwapCandidate,
                            onSwapItem = viewModel::swapItem,
                            onDescribeItemDifferently = viewModel::onDescribeItemDifferently,
                            onDecompose = viewModel::onDecompose,
                            onCombine = viewModel::onCombine,
                            onConfirm = viewModel::confirm,
                            onCancel = viewModel::cancel,
                            onSaveAsMyMeal = viewModel::onSaveAsMyMeal,
                            onFeedback = viewModel::submitFeedback,
                            // #49: no LazyColumn in the app used
                            // `animateItem()`, so a removal/undo/merge made
                            // every row below it pop to its new position
                            // instead of sliding.
                            modifier = Modifier.animateItem(),
                        )
                    }
                    if (showTypingRow) {
                        item(key = "typing") {
                            Row(modifier = Modifier.fillMaxWidth().animateItem()) {
                                TypingIndicator()
                            }
                        }
                    }
                }
            }

            ChatInputBar(
                input = input,
                onInputChange = { input = it },
                enabled = !sending && !offline,
                focusRequester = inputFocusRequester,
                attachment = attachment,
                voice =
                    VoiceUiState(
                        recording = recorder.recording,
                        available = recognizerAvailable,
                        elapsedMs = elapsedMs,
                        levels = recorder.levels,
                    ),
                notice = notice,
                onAttachClick = {
                    photoPicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                },
                onCameraClick = { showCameraSheet = true },
                onRemoveAttachment = { attachment = null },
                onMicClick = {
                    notice = null
                    if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                        PackageManager.PERMISSION_GRANTED
                    ) {
                        recorder.start()
                    } else {
                        micPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                    }
                },
                onDiscardRecording = recorder::discard,
                onFinishRecording = recorder::finish,
                onSend = {
                    val text = input.trim()
                    val photo = attachment
                    if (photo != null) {
                        viewModel.sendPhoto(photo, text)
                        attachment = null
                        input = ""
                    } else if (text.isNotEmpty()) {
                        viewModel.send(text)
                        input = ""
                    }
                },
                modifier = Modifier.navigationBarsPadding(),
            )
        }

        Column(
            modifier = Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(bottom = 128.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            InkToast(text = stringResource(R.string.chat_quick_log_opened), visible = showQuickLogToast)
            InkToast(
                text = stringResource(R.string.chat_offline_banner),
                visible = offline,
                modifier = Modifier.padding(top = 8.dp),
            )
            activeToast?.let { text ->
                InkToast(text = text, visible = true, modifier = Modifier.padding(top = 8.dp))
            }
            undoToast?.let { toast ->
                ChatUndoToast(
                    toast = toast,
                    onUndo = { t ->
                        when (t) {
                            is UndoToast.Swapped -> viewModel.undoSwap()
                            is UndoToast.Removed -> viewModel.undoRemove()
                        }
                    },
                    onDismiss = viewModel::dismissUndoToast,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }
        }
    }
}

/** True when [msg] is the last message in its consecutive run of same-author messages. */
private fun isLastOfAuthorRun(
    messages: List<ChatMsg>,
    msg: ChatMsg,
): Boolean {
    val index = messages.indexOfFirst { it.id == msg.id }
    if (index == messages.lastIndex) return true
    val next = messages[index + 1]
    return authorKeyOf(msg) != authorKeyOf(next)
}

/** Groups messages by "side" for the purposes of run-based timestamp placement. */
private fun authorKeyOf(msg: ChatMsg): String =
    when (msg) {
        is ChatMsg.User -> "user"
        is ChatMsg.Photo -> "user"
        is ChatMsg.Coach -> "coach"
        is ChatMsg.UpgradeNotice -> "coach"
        is ChatMsg.Card -> "coach"
    }

private fun formatTimestamp(epochMillis: Long): String {
    val formatter = DateTimeFormatter.ofPattern("hh:mm a", Locale.getDefault())
    return java.time.Instant.ofEpochMilli(epochMillis).atZone(ZoneId.systemDefault()).format(formatter)
}

/**
 * The chat header, Claude-style: a back button on the left, Olli + "Coach"
 * centred, and an equal-width spacer on the right so the title stays centred.
 * No divider — the transcript scrolls straight up under it.
 */
@Composable
private fun ChatHeader(onBack: () -> Unit) {
    val colors = MealsyTheme.colors
    Row(
        modifier =
            Modifier
                .fillMaxWidth()
                .statusBarsPadding()
                .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CircleIconButton(
            icon = MealsyIcons.ChevronLeft,
            contentDescription = stringResource(R.string.chat_back_description),
            onClick = onBack,
            size = 40.dp,
        )
        Row(
            modifier = Modifier.weight(1f),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Olli(size = OlliSize.Header, bob = true)
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                text = stringResource(R.string.chat_coach_title),
                style = MealsyType.body.copy(fontSize = 16.sp, fontWeight = FontWeight.Medium),
                color = colors.ink,
            )
        }
        Spacer(modifier = Modifier.width(40.dp))
    }
}

/**
 * The empty-transcript state: mascot, prompt copy, and suggestion chips.
 *
 * `internal` (rather than `private`) so [app.mealsy.android.ui.chat.ChatScreenGoldenTest]
 * can capture it directly without a ViewModel.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun EmptyState(
    modifier: Modifier = Modifier,
    onSuggestionTapped: (String) -> Unit,
) {
    val colors = MealsyTheme.colors
    val suggestions =
        listOf(
            stringResource(R.string.chat_suggestion_eggs),
            stringResource(R.string.chat_suggestion_salad),
            stringResource(R.string.chat_suggestion_protein_question),
            stringResource(R.string.chat_suggestion_dinner_question),
        )
    Column(
        modifier = modifier.fillMaxWidth().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Olli(size = OlliSize.Done, bob = true)
        Text(
            text = stringResource(R.string.chat_empty_prompt),
            style = MealsyType.body,
            color = colors.ink,
            modifier = Modifier.padding(top = 16.dp, bottom = 20.dp),
        )
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            // 12dp so the 48dp touch targets of adjacent rows don't overlap
            // (#48 item 6).
            verticalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            suggestions.forEach { suggestion ->
                FilterChipPill(
                    text = suggestion,
                    selected = false,
                    onClick = { onSuggestionTapped(suggestion) },
                )
            }
        }
    }
}

/**
 * Renders one transcript entry. `internal` (rather than `private`) so
 * [app.mealsy.android.ui.chat.ChatScreenGoldenTest] can capture individual
 * message states directly, without a ViewModel or network.
 */
@Composable
internal fun ChatMessageRow(
    msg: ChatMsg,
    timestamp: String?,
    sending: Boolean,
    savingMeal: Boolean,
    onEditQty: (Int, Double) -> Unit,
    onRemoveItem: (Int) -> Unit,
    onSetMealType: (String) -> Unit,
    onSetPortion: (Double) -> Unit,
    onSwapCandidate: (Int, String) -> Unit,
    onSwapItem: (Int, app.mealsy.domain.CardItem, String, String?) -> Unit,
    onDescribeItemDifferently: (Int, String) -> Unit,
    onDecompose: () -> Unit,
    onCombine: () -> Unit,
    onConfirm: () -> Unit,
    onCancel: () -> Unit,
    onSaveAsMyMeal: (String) -> Unit,
    onFeedback: (String, Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    Box(modifier = modifier) {
        when (msg) {
            is ChatMsg.User -> ChatBubble(text = msg.text, author = ChatBubbleAuthor.User, timestamp = timestamp)

            is ChatMsg.Photo ->
                Column(modifier = Modifier.fillMaxWidth(), horizontalAlignment = Alignment.End) {
                    Image(
                        bitmap = msg.bitmap.asImageBitmap(),
                        contentDescription = stringResource(R.string.chat_photo_description),
                        contentScale = ContentScale.Crop,
                        modifier =
                            Modifier
                                .widthIn(max = 220.dp)
                                .clip(RoundedCornerShape(18.dp)),
                    )
                    if (timestamp != null) {
                        Text(
                            text = timestamp,
                            style = MealsyType.label.copy(fontSize = 11.sp),
                            color = colors.inactive,
                            modifier = Modifier.padding(top = 4.dp),
                        )
                    }
                }

            is ChatMsg.Coach ->
                Column(modifier = Modifier.fillMaxWidth()) {
                    CoachReply(text = msg.text, tags = msg.tags, timestamp = timestamp)
                    if (msg.responseId != null) {
                        Row(
                            modifier = Modifier.padding(start = 4.dp, top = 2.dp),
                            horizontalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            FeedbackGlyph(
                                glyph = "↑",
                                selected = msg.feedback == 1,
                                contentDescription = stringResource(R.string.chat_thumb_up_description),
                                onClick = { onFeedback(msg.id, 1) },
                            )
                            FeedbackGlyph(
                                glyph = "↓",
                                selected = msg.feedback == -1,
                                contentDescription = stringResource(R.string.chat_thumb_down_description),
                                onClick = { onFeedback(msg.id, -1) },
                            )
                        }
                    }
                }

            is ChatMsg.UpgradeNotice ->
                Surface(
                    color = colors.surface,
                    shape = RoundedCornerShape(18.dp),
                ) {
                    Text(
                        text = msg.text,
                        style = MealsyType.body,
                        color = colors.ink,
                        modifier = Modifier.padding(16.dp),
                    )
                }

            is ChatMsg.Card -> {
                // #49 item 3: the Active/Swapping card <-> collapsed-bubble swap
                // used to be a plain `when`, so the ~1,500px card vanished and
                // the small bubble popped in on the same frame, jumping
                // everything below it. AnimatedContent cross-fades + grows/
                // shrinks between the two shapes instead. `contentKey` groups
                // Active and Swapping together so an in-place edit (portion,
                // qty, a swap round-tripping) never replays this transition —
                // only an actual category change (into/out of "still
                // interactive") does.
                val cardMotionMs = motionDurationMs(220)
                AnimatedContent(
                    targetState = msg.state,
                    contentKey = { it.isInteractive() },
                    transitionSpec = {
                        (fadeIn(tween(cardMotionMs)) + expandVertically(tween(cardMotionMs)))
                            .togetherWith(fadeOut(tween(cardMotionMs)) + shrinkVertically(tween(cardMotionMs)))
                    },
                    label = "confirm-card-state",
                ) { state ->
                    when (state) {
                        is CardState.Active, is CardState.Swapping -> {
                            // Alias the row's callback lambdas under distinct names before
                            // building the anonymous ConfirmCardCallbacks below — inside
                            // that object's member bodies, an unqualified name matching a
                            // member (e.g. `onRemoveItem`) resolves to the member itself
                            // (infinite self-recursion), not the captured outer lambda.
                            val doSetMealType = onSetMealType
                            val doSetPortion = onSetPortion
                            val doEditQty = onEditQty
                            val doRemoveItem = onRemoveItem
                            val doSwapCandidate = onSwapCandidate
                            val doSwapItem = onSwapItem
                            val doDescribeItemDifferently = onDescribeItemDifferently
                            val doDecompose = onDecompose
                            val doCombine = onCombine
                            val doConfirm = onConfirm
                            val doCancel = onCancel
                            val doSaveAsMyMeal = onSaveAsMyMeal
                            HighlightOnChange(changeKey = msg.card) { highlightModifier ->
                                ConfirmCardView(
                                    card = msg.card,
                                    callbacks =
                                        object : ConfirmCardCallbacks {
                                            override fun onMealTypeChange(mealType: String) = doSetMealType(mealType)

                                            override fun onPortionChange(portion: Double) = doSetPortion(portion)

                                            override fun onQtyChange(
                                                index: Int,
                                                newQtyG: Double,
                                            ) = doEditQty(index, newQtyG)

                                            override fun onRemoveItem(index: Int) = doRemoveItem(index)

                                            override fun onSwapCandidate(
                                                index: Int,
                                                newName: String,
                                            ) = doSwapCandidate(index, newName)

                                            override fun onSwapItem(
                                                index: Int,
                                                newItem: app.mealsy.domain.CardItem,
                                                method: String,
                                                query: String?,
                                            ) = doSwapItem(index, newItem, method, query)

                                            override fun onDescribeItemDifferently(
                                                index: Int,
                                                description: String,
                                            ) = doDescribeItemDifferently(index, description)

                                            override fun onDecompose() = doDecompose()

                                            override fun onCombine() = doCombine()

                                            override fun onConfirm() = doConfirm()

                                            override fun onCancel() = doCancel()

                                            override fun onSaveAsMyMeal(name: String) = doSaveAsMyMeal(name)
                                        },
                                    busy = sending,
                                    swapping = state is CardState.Swapping,
                                    savingMeal = savingMeal,
                                    timestamp = timestamp,
                                    modifier = highlightModifier,
                                )
                            }
                        }
                        is CardState.Logged ->
                            CoachReply(
                                text = stringResource(R.string.chat_card_logged, state.label, state.kcal),
                                tags = emptyList(),
                                timestamp = timestamp,
                            )
                        is CardState.NotLogged ->
                            CollapsedCardLine(
                                text = stringResource(R.string.chat_card_not_logged),
                                strikethrough = true,
                                timestamp = timestamp,
                            )
                        is CardState.Discarded ->
                            CollapsedCardLine(
                                text = stringResource(R.string.chat_card_discarded),
                                strikethrough = false,
                                timestamp = timestamp,
                            )
                    }
                }
            }
        }
    }
}

/** Groups [CardState] into "still interactive" vs "collapsed", for [AnimatedContent]'s `contentKey`. */
private fun CardState.isInteractive(): Boolean = this is CardState.Active || this is CardState.Swapping

/**
 * Wraps [content] with a background tint that briefly flashes (`oliveTrack`
 * -> transparent) whenever [changeKey] changes after the first composition —
 * a merge (a new user message folded into this card) or a candidate
 * swap/re-describe landing. Respects [LocalReducedMotion] via [mealsyTween].
 * Self-contained per #49 item 3's brief: no shared component change needed.
 */
@Composable
private fun HighlightOnChange(
    changeKey: Any,
    content: @Composable (Modifier) -> Unit,
) {
    val colors = MealsyTheme.colors
    var previousKey by remember { mutableStateOf(changeKey) }
    var flashing by remember { mutableStateOf(false) }
    LaunchedEffect(changeKey) {
        if (changeKey != previousKey) {
            previousKey = changeKey
            flashing = true
            delay(600)
            flashing = false
        }
    }
    val tint by
        animateColorAsState(
            targetValue = if (flashing) colors.oliveTrack else Color.Transparent,
            animationSpec = mealsyTween(600),
            label = "card-row-highlight",
        )
    content(Modifier.background(tint, RoundedCornerShape(18.dp)))
}

/**
 * Renders a coach reply the way Claude renders its own: Markdown body as
 * plain full-width text on the canvas, no bubble, so long answers read like
 * a document rather than a chat balloon. Only the user's messages keep a
 * bubble.
 */
@Composable
private fun CoachReply(
    text: String,
    tags: List<MacroTag>,
    timestamp: String?,
) {
    val colors = MealsyTheme.colors
    Column(modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        MarkdownText(markdown = text, color = colors.ink)
        if (tags.isNotEmpty()) {
            Row(
                modifier = Modifier.padding(top = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                tags.forEach { tag ->
                    TagChip(text = tag.text, tone = tag.tone.toTagTone())
                }
            }
        }
        if (timestamp != null) {
            Text(
                text = timestamp,
                style = MealsyType.label.copy(fontSize = 11.sp),
                color = colors.inactive,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

/**
 * A muted, one-line collapsed record of a card that is no longer
 * interactive: `Not logged` (with strikethrough) or `Discarded — nothing
 * logged.`. [CardState.Logged] renders as a normal [ChatBubble] instead,
 * since it carries a real coach reply and macro tags.
 */
@Composable
private fun CollapsedCardLine(
    text: String,
    strikethrough: Boolean,
    timestamp: String?,
) {
    val colors = MealsyTheme.colors
    Column(modifier = Modifier.fillMaxWidth(), horizontalAlignment = Alignment.Start) {
        Text(
            text = text,
            style =
                MealsyType.body.copy(
                    textDecoration = if (strikethrough) TextDecoration.LineThrough else TextDecoration.None,
                ),
            color = colors.muted,
        )
        if (timestamp != null) {
            Text(
                text = timestamp,
                style = MealsyType.label.copy(fontSize = 11.sp),
                color = colors.inactive,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

private fun PastelTone.toTagTone(): TagTone =
    when (this) {
        PastelTone.Leaf -> TagTone.Leaf
        PastelTone.Butter -> TagTone.Butter
        PastelTone.Powder -> TagTone.Powder
        PastelTone.Pink -> TagTone.Pink
    }

/**
 * A muted up/down feedback glyph. `:core:ui`'s [MealsyIcons] has no
 * thumb-up/thumb-down icons, and this affordance never renders on this
 * branch anyway (see [ChatViewModel.submitFeedback] KDoc) — a text glyph
 * avoids adding icons to the shared design system for dead code.
 */
@Composable
private fun FeedbackGlyph(
    glyph: String,
    selected: Boolean,
    contentDescription: String,
    onClick: () -> Unit,
) {
    val colors = MealsyTheme.colors
    IconButton(
        onClick = onClick,
        modifier =
            Modifier
                .size(24.dp)
                .semantics { this.contentDescription = contentDescription },
    ) {
        Text(
            text = glyph,
            style = MealsyType.label.copy(fontSize = 14.sp),
            color = if (selected) colors.ink else colors.inactive,
        )
    }
}

/** Decodes a photo-picker [uri] to a downsampled software bitmap off the main thread; null on failure. */
private suspend fun decodeAttachment(
    context: Context,
    uri: Uri,
): Bitmap? =
    withContext(Dispatchers.IO) {
        try {
            val source = ImageDecoder.createSource(context.contentResolver, uri)
            ImageDecoder.decodeBitmap(source) { decoder, info, _ ->
                decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
                val longest = maxOf(info.size.width, info.size.height)
                if (longest > MAX_ATTACHMENT_PX) {
                    val scale = MAX_ATTACHMENT_PX.toFloat() / longest
                    decoder.setTargetSize((info.size.width * scale).toInt(), (info.size.height * scale).toInt())
                }
            }
        } catch (exc: IOException) {
            null
        } catch (exc: SecurityException) {
            null
        }
    }

private const val MAX_ATTACHMENT_PX = 1600
