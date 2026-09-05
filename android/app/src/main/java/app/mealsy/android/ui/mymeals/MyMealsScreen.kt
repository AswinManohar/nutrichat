package app.mealsy.android.ui.mymeals

import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.PointerInputScope
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.data.repo.SavedMeal
import kotlinx.coroutines.launch

// Mirrors the backend's MEAL_CATEGORIES (src/backend/agent/tools/meals.py).
private val MEAL_TYPES = listOf("breakfast", "brunch", "lunch", "snack", "dinner")
private const val SWIPE_DELETE_THRESHOLD_PX = 300f

/**
 * My Meals screen: saved quick-log meals with per-meal macros, tap to
 * quick-log (via a meal-type picker sheet), swipe-to-delete with an undo
 * snackbar.
 *
 * [onLoggedNavigateToChat] is called once a quick-log actually succeeds —
 * see [MyMealsViewModel]'s doc for why the today-header refresh happens on
 * the chat screen's `ON_RESUME` rather than here.
 */
@Composable
fun MyMealsScreen(
    viewModel: MyMealsViewModel = hiltViewModel(),
    onLoggedNavigateToChat: () -> Unit = {},
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val hiddenIds by viewModel.hiddenIds.collectAsStateWithLifecycle()

    var mealTypeSheetFor by remember { mutableStateOf<SavedMeal?>(null) }
    var quickLogging by remember { mutableStateOf(false) }
    val snackbarHostState = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()

    mealTypeSheetFor?.let { meal ->
        MealTypeDialog(
            mealName = meal.name,
            enabled = !quickLogging,
            onSelect = { mealType ->
                quickLogging = true
                scope.launch {
                    val ok = viewModel.quickLog(meal.id, mealType).await()
                    quickLogging = false
                    mealTypeSheetFor = null
                    if (ok) {
                        onLoggedNavigateToChat()
                    } else {
                        snackbarHostState.showSnackbar("Couldn't log that. Try again.")
                    }
                }
            },
            onDismiss = { if (!quickLogging) mealTypeSheetFor = null },
        )
    }

    Scaffold(snackbarHost = { SnackbarHost(snackbarHostState) }) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            Text(
                text = "My Meals",
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.padding(16.dp),
            )

            when (val state = uiState) {
                MyMealsUiState.Loading -> LoadingState()
                MyMealsUiState.Empty -> EmptyState()
                is MyMealsUiState.Error -> ErrorState(state.message, onRetry = viewModel::load)
                is MyMealsUiState.Loaded -> {
                    val visible = state.meals.filterNot { it.id in hiddenIds }
                    if (visible.isEmpty()) {
                        EmptyState()
                    } else {
                        LazyColumn(modifier = Modifier.fillMaxSize()) {
                            items(visible, key = { it.id }) { meal ->
                                SavedMealRow(
                                    meal = meal,
                                    onTap = { mealTypeSheetFor = meal },
                                    onSwipeDelete = {
                                        viewModel.deleteWithUndo(meal.id)
                                        scope.launch {
                                            val result = snackbarHostState.showSnackbar(
                                                message = "Deleted \"${meal.name}\"",
                                                actionLabel = "Undo",
                                            )
                                            if (result == SnackbarResult.ActionPerformed) {
                                                viewModel.undoDelete(meal.id)
                                            }
                                        }
                                    },
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun LoadingState() {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text("Loading your meals…")
    }
}

@Composable
private fun EmptyState() {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(
            text = "No saved meals yet. Save one from a logged meal in chat.",
            style = MaterialTheme.typography.bodyLarge,
            modifier = Modifier.padding(32.dp),
        )
    }
}

@Composable
private fun ErrorState(message: String, onRetry: () -> Unit) {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(message, modifier = Modifier.padding(bottom = 16.dp))
            Button(onClick = onRetry) { Text("Retry") }
        }
    }
}

/** One saved meal: name, macros, ingredient count. Tap to quick-log, swipe left to delete. */
@Composable
private fun SavedMealRow(meal: SavedMeal, onTap: () -> Unit, onSwipeDelete: () -> Unit) {
    var dragOffset by remember { mutableStateOf(0f) }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp)
            .pointerInput(meal.id) {
                detectHorizontalDragGestures(
                    onDragEnd = {
                        if (dragOffset < -SWIPE_DELETE_THRESHOLD_PX) onSwipeDelete()
                        dragOffset = 0f
                    },
                    onHorizontalDrag = { _, dragAmount -> dragOffset += dragAmount },
                )
            },
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp)
                .pointerInput(meal.id) {
                    // A plain tap (no drag) opens the meal-type sheet.
                    detectTapToLog(onTap)
                },
        ) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(meal.name, style = MaterialTheme.typography.titleMedium)
                Text("${meal.kcal.toInt()} kcal")
            }
            Text(
                text = "${meal.proteinG.toInt()}g protein · ${meal.nIngredients} ingredients" +
                    if (meal.loggedToday) " · logged today" else "",
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

private suspend fun PointerInputScope.detectTapToLog(onTap: () -> Unit) {
    detectTapGestures(onTap = { onTap() })
}

@Composable
private fun MealTypeDialog(
    mealName: String,
    enabled: Boolean,
    onSelect: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var selected by remember { mutableStateOf(MEAL_TYPES.first()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Log \"$mealName\" as…") },
        text = {
            SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                MEAL_TYPES.forEachIndexed { index, mealType ->
                    SegmentedButton(
                        selected = selected == mealType,
                        onClick = { selected = mealType },
                        shape = SegmentedButtonDefaults.itemShape(index, MEAL_TYPES.size),
                        enabled = enabled,
                    ) {
                        Text(mealType.replaceFirstChar { it.uppercase() })
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onSelect(selected) }, enabled = enabled) { Text("Log it") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = enabled) { Text("Cancel") }
        },
    )
}
