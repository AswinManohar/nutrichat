package app.mealsy.android.ui.chat

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.collectAsStateWithLifecycle

/**
 * The chat screen: today header, transcript, pending confirmation card, and input.
 *
 * [onOpenTrends] is a temporary way to reach [app.mealsy.android.ui.trends.TrendsScreen]
 * (Task 11) via a plain button, and [onOpenMyMeals] likewise reaches
 * [app.mealsy.android.ui.mymeals.MyMealsScreen] (Task 12) — a real bottom
 * nav destination replaces both in Task 13.
 *
 * The today header is refreshed on `ON_RESUME` (not just once at startup):
 * `MyMealsScreen`'s quick-log can't refresh this screen's `ChatViewModel`
 * directly (see `MyMealsViewModel`'s doc comment), so returning here via the
 * back stack re-triggers [ChatViewModel.refreshTodayNow] instead.
 */
@Composable
fun ChatScreen(
    viewModel: ChatViewModel = hiltViewModel(),
    onOpenTrends: () -> Unit = {},
    onOpenMyMeals: () -> Unit = {},
) {
    val messages by viewModel.messages.collectAsStateWithLifecycle()
    val pendingCard by viewModel.pendingCard.collectAsStateWithLifecycle()
    val sending by viewModel.sending.collectAsStateWithLifecycle()
    val offline by viewModel.offline.collectAsStateWithLifecycle()
    val today by viewModel.today.collectAsStateWithLifecycle()
    val goals by viewModel.goals.collectAsStateWithLifecycle()
    val lastLoggedCard by viewModel.lastLoggedCard.collectAsStateWithLifecycle()
    val savingMeal by viewModel.savingMeal.collectAsStateWithLifecycle()

    var input by remember { mutableStateOf("") }
    var showCameraSheet by remember { mutableStateOf(false) }

    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) viewModel.refreshTodayNow()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
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

    Column(modifier = Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.End,
        ) {
            Button(onClick = onOpenMyMeals) { Text("My Meals") }
            Button(onClick = onOpenTrends, modifier = Modifier.padding(start = 8.dp)) { Text("Trends") }
        }
        TodayHeader(today = today, goals = goals)
        HorizontalDivider()

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
                modifier = Modifier.weight(1f),
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
}
