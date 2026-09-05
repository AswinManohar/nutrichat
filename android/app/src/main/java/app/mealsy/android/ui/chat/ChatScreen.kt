package app.mealsy.android.ui.chat

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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle

/** The chat screen: today header, transcript, pending confirmation card, and input. */
@Composable
fun ChatScreen(viewModel: ChatViewModel = hiltViewModel()) {
    val messages by viewModel.messages.collectAsStateWithLifecycle()
    val pendingCard by viewModel.pendingCard.collectAsStateWithLifecycle()
    val sending by viewModel.sending.collectAsStateWithLifecycle()
    val offline by viewModel.offline.collectAsStateWithLifecycle()
    val today by viewModel.today.collectAsStateWithLifecycle()
    val goals by viewModel.goals.collectAsStateWithLifecycle()

    var input by remember { mutableStateOf("") }

    Column(modifier = Modifier.fillMaxSize()) {
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
