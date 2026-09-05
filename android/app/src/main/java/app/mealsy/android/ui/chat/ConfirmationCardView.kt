package app.mealsy.android.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import app.mealsy.domain.CardEditor
import app.mealsy.domain.CardItem
import app.mealsy.domain.ConfirmationCard

private val MEAL_TYPES = listOf("breakfast", "lunch", "snack", "dinner")

/** Editable confirmation card: item rows, meal type, portion, totals, confirm/cancel. */
@Composable
fun ConfirmationCardView(
    card: ConfirmationCard,
    sending: Boolean,
    onEditQty: (index: Int, newQtyG: Double) -> Unit,
    onRemoveItem: (index: Int) -> Unit,
    onSetMealType: (String) -> Unit,
    onSetPortion: (Double) -> Unit,
    onConfirm: () -> Unit,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val totals = CardEditor.totals(card)

    Card(modifier = modifier.fillMaxWidth().padding(16.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(text = card.message, style = MaterialTheme.typography.bodyLarge)

            LazyColumn(modifier = Modifier.padding(top = 12.dp)) {
                items(card.items.size) { index ->
                    CardItemRow(
                        item = card.items[index],
                        onEditQty = { newQty -> onEditQty(index, newQty) },
                        onRemove = { onRemoveItem(index) },
                    )
                }
            }

            SingleChoiceSegmentedButtonRow(modifier = Modifier.padding(top = 12.dp)) {
                MEAL_TYPES.forEachIndexed { index, mealType ->
                    SegmentedButton(
                        selected = card.mealType == mealType,
                        onClick = { onSetMealType(mealType) },
                        shape = SegmentedButtonDefaults.itemShape(index, MEAL_TYPES.size),
                    ) {
                        Text(mealType.replaceFirstChar { it.uppercase() })
                    }
                }
            }

            Row(
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text("Portion: ${card.portion}x")
                Row {
                    OutlinedButton(
                        onClick = { onSetPortion((card.portion - 0.25).coerceAtLeast(0.25)) },
                    ) { Text("-") }
                    OutlinedButton(
                        onClick = { onSetPortion(card.portion + 0.25) },
                        modifier = Modifier.padding(start = 8.dp),
                    ) { Text("+") }
                }
            }

            Text(
                text = "Total: ${totals.kcal.toInt()} kcal, ${totals.proteinG.toInt()}g protein",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(top = 12.dp),
            )

            Row(
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                horizontalArrangement = Arrangement.End,
            ) {
                OutlinedButton(onClick = onCancel, enabled = !sending) { Text("Cancel") }
                Button(
                    onClick = onConfirm,
                    enabled = !sending && card.items.isNotEmpty(),
                    modifier = Modifier.padding(start = 8.dp),
                ) { Text("Confirm") }
            }
        }
    }
}

/**
 * Shown after a [ConfirmationCard] is successfully logged, offering to save
 * its items as a reusable "My Meal" (`POST /my-meals`). [card] is the card
 * exactly as it was confirmed — its post-edit gram weights and portion are
 * what gets saved (see `MyMealsRepository.save`/`CardItem.toSavedIngredientDto`).
 */
@Composable
fun LoggedSuccessSaveMealPrompt(
    card: ConfirmationCard,
    saving: Boolean,
    onSave: (name: String) -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var name by remember(card) { mutableStateOf("") }

    Card(modifier = modifier.fillMaxWidth().padding(16.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("Save this as a My Meal?", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(
                value = name,
                onValueChange = { name = it },
                label = { Text("Meal name") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                enabled = !saving,
            )
            Row(
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                horizontalArrangement = Arrangement.End,
            ) {
                OutlinedButton(onClick = onDismiss, enabled = !saving) { Text("No thanks") }
                Button(
                    onClick = { onSave(name.trim()) },
                    enabled = !saving && name.isNotBlank(),
                    modifier = Modifier.padding(start = 8.dp),
                ) { Text("Save") }
            }
        }
    }
}

@Composable
private fun CardItemRow(item: CardItem, onEditQty: (Double) -> Unit, onRemove: () -> Unit) {
    // The qty field commits on focus-loss/IME-done rather than per keystroke:
    // committing per keystroke fights the `remember(item.targetQtyG)` key —
    // every commit changes targetQtyG, which re-keys the remember and snaps
    // the field back to the just-committed value mid-edit (e.g. typing "150"
    // reverts to "1" after the first digit lands).
    var qtyText by remember(item.targetQtyG) { mutableStateOf(item.targetQtyG.toString()) }
    var dragOffset by remember { mutableStateOf(0f) }

    fun commitQty() {
        qtyText.toDoubleOrNull()?.let { if (it > 0) onEditQty(it) }
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp)
            .pointerInput(item) {
                detectHorizontalDragGestures(
                    onDragEnd = {
                        // Swipe-to-remove: a leftward drag past a small threshold removes the row.
                        if (dragOffset < -SWIPE_REMOVE_THRESHOLD_PX) onRemove()
                        dragOffset = 0f
                    },
                    onHorizontalDrag = { _, dragAmount -> dragOffset += dragAmount },
                )
            }
            .background(MaterialTheme.colorScheme.surface)
            // Announced alongside (not instead of — the qty field below must
            // stay independently focusable/editable for TalkBack) the row's
            // individual child nodes, so a swipe-to-remove target with no
            // visible affordance still reads as a coherent item summary.
            .semantics {
                contentDescription =
                    "${item.foodName}, ${item.targetQtyG.toInt()}g, ${item.kcal.toInt()} kcal"
            },
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = item.foodName,
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.padding(top = 12.dp),
        )
        OutlinedTextField(
            value = qtyText,
            onValueChange = { newValue -> qtyText = newValue },
            label = { Text("g") },
            modifier = Modifier
                .padding(horizontal = 8.dp)
                .onFocusChanged { focusState -> if (!focusState.isFocused) commitQty() },
            singleLine = true,
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Number,
                imeAction = ImeAction.Done,
            ),
            keyboardActions = KeyboardActions(onDone = { commitQty() }),
        )
        Text(
            text = "${item.kcal.toInt()} kcal",
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.padding(top = 12.dp),
        )
    }
}

private const val SWIPE_REMOVE_THRESHOLD_PX = 300f
