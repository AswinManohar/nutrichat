package app.mealsy.android.ui.chat

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.R
import app.mealsy.android.design.components.InkToast
import kotlinx.coroutines.delay

/**
 * The chat screen: transcript, pending confirmation card, and input.
 *
 * Home, Trends, and My Meals are reached via `AppNav`'s [app.mealsy.android.design.components.BottomNavPill],
 * not from this screen. The today totals/goals header that used to live here
 * (`TodayHeader`) was retired — Home owns that display now and refreshes
 * itself via `TodayRefreshSignal` on `ON_RESUME`, so this screen no longer
 * needs its own refresh hook for it.
 *
 * @param quickLog Whether this screen was opened via the Home FAB's
 *   "quick log" shortcut. When true, the message input requests focus and an
 *   [InkToast] confirms the shortcut for 2 seconds — both fire exactly once
 *   per screen instance (see [rememberSaveable] guard below), so a
 *   recomposition or configuration change doesn't replay them.
 */
@Composable
fun ChatScreen(quickLog: Boolean = false, viewModel: ChatViewModel = hiltViewModel()) {
    val messages by viewModel.messages.collectAsStateWithLifecycle()
    val pendingCard by viewModel.pendingCard.collectAsStateWithLifecycle()
    val sending by viewModel.sending.collectAsStateWithLifecycle()
    val offline by viewModel.offline.collectAsStateWithLifecycle()
    val lastLoggedCard by viewModel.lastLoggedCard.collectAsStateWithLifecycle()
    val savingMeal by viewModel.savingMeal.collectAsStateWithLifecycle()

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

    // POST_NOTIFICATIONS is a runtime permission on API 33+; request it the
    // first time the user reaches the chat screen (the only place FCM
    // notifications are relevant), rather than at app startup.
    val context = LocalContext.current
    val notificationPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { /* no-op: MealsyMessagingService already guards notify() against denial */ }
    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val granted = ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.POST_NOTIFICATIONS,
            ) == PackageManager.PERMISSION_GRANTED
            if (!granted) {
                notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }

    if (showCameraSheet) {
        CameraSheet(
            onUsePhoto = { bitmap ->
                showCameraSheet = false
                viewModel.sendPhoto(bitmap)
            },
            onDismiss = { showCameraSheet = false },
        )
    }

    Box(modifier = Modifier.fillMaxSize()) {
        Column(modifier = Modifier.fillMaxSize()) {
            if (offline) {
                Text(
                    text = "Offline — check your connection.",
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(8.dp),
                )
            }

            LazyColumn(modifier = Modifier.weight(1f).fillMaxWidth()) {
                items(messages) { msg ->
                    val (prefix, text) = when (msg) {
                        is ChatMsg.User -> "You" to msg.text
                        is ChatMsg.Assistant -> "Mealsy" to msg.text
                    }
                    Text(
                        text = "$prefix: $text",
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                    )
                }
            }

            val card = pendingCard
            if (card != null) {
                ConfirmationCardView(
                    card = card,
                    sending = sending,
                    onEditQty = viewModel::editQty,
                    onRemoveItem = viewModel::removeItem,
                    onSetMealType = viewModel::setMealType,
                    onSetPortion = viewModel::setPortion,
                    onConfirm = viewModel::confirm,
                    onCancel = viewModel::cancel,
                )
            }

            lastLoggedCard?.let { loggedCard ->
                LoggedSuccessSaveMealPrompt(
                    card = loggedCard,
                    saving = savingMeal,
                    onSave = viewModel::saveAsMyMeal,
                    onDismiss = viewModel::dismissSaveMealPrompt,
                )
            }

            Row(
                modifier = Modifier.fillMaxWidth().padding(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedTextField(
                    value = input,
                    onValueChange = { input = it },
                    modifier = Modifier.weight(1f).focusRequester(inputFocusRequester),
                    enabled = !sending && !offline,
                    label = { Text("Describe a meal") },
                )
                Button(
                    onClick = { showCameraSheet = true },
                    enabled = !sending && !offline,
                    modifier = Modifier.padding(start = 8.dp),
                ) {
                    Text("Photo")
                }
                Button(
                    onClick = {
                        val text = input.trim()
                        if (text.isNotEmpty()) {
                            viewModel.send(text)
                            input = ""
                        }
                    },
                    enabled = !sending && !offline,
                    modifier = Modifier.padding(start = 8.dp),
                ) {
                    Text("Send")
                }
            }
        }
        InkToast(
            text = stringResource(R.string.chat_quick_log_opened),
            visible = showQuickLogToast,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = 90.dp),
        )
    }
}
