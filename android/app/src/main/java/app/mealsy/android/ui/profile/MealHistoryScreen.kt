package app.mealsy.android.ui.profile

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.R
import app.mealsy.android.design.components.Eyebrow
import app.mealsy.android.design.components.InsetDivider
import app.mealsy.android.design.components.ListContainer
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.data.api.LoggedMealDto
import app.mealsy.data.api.ProfileMealsDto
import app.mealsy.data.api.RecommendationDto

/** The last 21 days: recipes Mealsy suggested (with what you said about them) and meals you logged. */
@Composable
fun MealHistoryScreen(
    onBack: () -> Unit,
    viewModel: MealHistoryViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    MealHistoryContent(state = state, onBack = onBack, onRetry = { viewModel.load() }, modifier = Modifier.fillMaxSize())
}

/** Stateless render of [MealHistoryScreen]. */
@Composable
fun MealHistoryContent(
    state: LoadState<ProfileMealsDto>,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    LoadStateScreen(
        title = stringResource(R.string.meal_history_title),
        state = state,
        loadingText = stringResource(R.string.meal_history_loading),
        errorText = stringResource(R.string.meal_history_error),
        onBack = onBack,
        onRetry = onRetry,
        modifier = modifier,
    ) { meals ->
        Text(text = stringResource(R.string.meal_history_window), style = MealsyType.label, color = colors.muted)
        Spacer(modifier = Modifier.height(16.dp))
        if (meals.recommendations.isEmpty() && meals.logged.isEmpty()) {
            Text(text = stringResource(R.string.meal_history_empty), style = MealsyType.body, color = colors.muted)
            return@LoadStateScreen
        }
        if (meals.recommendations.isNotEmpty()) {
            Eyebrow(text = stringResource(R.string.meal_history_recommended))
            Spacer(modifier = Modifier.height(10.dp))
            ListContainer {
                meals.recommendations.forEachIndexed { index, rec ->
                    if (index > 0) InsetDivider()
                    RecommendationRow(rec)
                }
            }
            Spacer(modifier = Modifier.height(24.dp))
        }
        if (meals.logged.isNotEmpty()) {
            Eyebrow(text = stringResource(R.string.meal_history_logged))
            Spacer(modifier = Modifier.height(10.dp))
            ListContainer {
                meals.logged.forEachIndexed { index, meal ->
                    if (index > 0) InsetDivider()
                    LoggedRow(meal)
                }
            }
        }
    }
}

@Composable
private fun RecommendationRow(rec: RecommendationDto) {
    val colors = MealsyTheme.colors
    val status =
        stringResource(
            when (rec.status) {
                "accepted" -> R.string.meal_history_status_accepted
                "rejected" -> R.string.meal_history_status_rejected
                else -> R.string.meal_history_status_shown
            },
        )
    Column(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text(text = rec.name, style = MealsyType.body, color = colors.ink)
        Text(
            text = listOfNotNull(formatDate(rec.createdAt), status).joinToString(", "),
            style = MealsyType.label,
            color = colors.muted,
        )
        rec.rejectionReason?.takeIf { it.isNotBlank() }?.let {
            Text(text = stringResource(R.string.meal_history_reason, it), style = MealsyType.label, color = colors.muted)
        }
    }
}

@Composable
private fun LoggedRow(meal: LoggedMealDto) {
    val colors = MealsyTheme.colors
    Column(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text(text = meal.label, style = MealsyType.body, color = colors.ink)
        formatDate(meal.loggedAt)?.let { Text(text = it, style = MealsyType.label, color = colors.muted) }
    }
}
