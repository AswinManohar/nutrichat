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
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
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
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.ui.common.ErrorState
import app.mealsy.android.ui.common.LoadingState
import app.mealsy.data.repo.SavedMeal
import kotlinx.coroutines.launch

private const val SWIPE_DELETE_THRESHOLD_PX = 300f

/**
 * My Meals screen: saved quick-log meals with per-meal macros, tap to open
 * meal detail (which offers its own log-again flow), swipe-to-delete with an
 * undo snackbar.
 *
 * [onLoggedNavigateToChat] is retained for API compatibility with existing
 * call sites but is no longer invoked from a row tap — logging now happens
 * from [app.mealsy.android.ui.mealdetail.MealDetailScreen] after
 * [onOpenMeal] navigates there.
 *
 * @param onOpenMeal Navigates to the meal-detail screen (My-Meal mode) for a
 *   tapped row's meal id.
 */
@Composable
fun MyMealsScreen(
    viewModel: MyMealsViewModel = hiltViewModel(),
    onLoggedNavigateToChat: () -> Unit = {},
    onOpenMeal: (String) -> Unit = {},
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val hiddenIds by viewModel.hiddenIds.collectAsStateWithLifecycle()

    val snackbarHostState = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()

    Scaffold(snackbarHost = { SnackbarHost(snackbarHostState) }) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            Text(
                text = "My Meals",
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.padding(16.dp),
            )

            when (val state = uiState) {
                MyMealsUiState.Loading -> LoadingState("Loading your meals…")
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
                                    onTap = { onOpenMeal(meal.id) },
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
private fun EmptyState() {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(
            text = "No saved meals yet. Save one from a logged meal in chat.",
            style = MaterialTheme.typography.bodyLarge,
            modifier = Modifier.padding(32.dp),
        )
    }
}

/** One saved meal: name, macros, ingredient count. Tap to open meal detail, swipe left to delete. */
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
            }
            // The whole card is one tap-to-log/swipe-to-delete target with
            // no separately interactive children (unlike CardItemRow's
            // editable qty field), so clearing and setting one description
            // is safe here and avoids TalkBack reading three disjoint texts.
            .clearAndSetSemantics {
                contentDescription = "${meal.name}, ${meal.kcal.toInt()} kcal, " +
                    "${meal.proteinG.toInt()}g protein"
                customActions = listOf(
                    CustomAccessibilityAction("Delete meal") { onSwipeDelete(); true },
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
