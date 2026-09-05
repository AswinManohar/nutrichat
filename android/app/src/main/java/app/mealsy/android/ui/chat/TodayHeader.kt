package app.mealsy.android.ui.chat

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.mealsy.data.api.GoalsResponse
import app.mealsy.data.api.TodayResponse

/**
 * kcal + protein progress against today's goals, refreshed by
 * [ChatViewModel] after every turn or [app.mealsy.data.repo.LogOutcome].
 */
@Composable
fun TodayHeader(today: TodayResponse?, goals: GoalsResponse?, modifier: Modifier = Modifier) {
    Column(modifier = modifier.fillMaxWidth().padding(16.dp)) {
        val kcal = today?.kcal ?: 0.0
        val protein = today?.proteinG ?: 0.0
        val kcalGoal = goals?.kcalGoal
        val proteinGoal = goals?.proteinGoal

        Text(
            text = if (kcalGoal != null) {
                "${kcal.toInt()} / ${kcalGoal.toInt()} kcal"
            } else {
                "${kcal.toInt()} kcal"
            },
            style = MaterialTheme.typography.titleMedium,
        )
        if (kcalGoal != null && kcalGoal > 0) {
            LinearProgressIndicator(
                progress = { (kcal / kcalGoal).toFloat().coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
            )
        }

        Text(
            text = if (proteinGoal != null) {
                "${protein.toInt()} / ${proteinGoal.toInt()} g protein"
            } else {
                "${protein.toInt()} g protein"
            },
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.padding(top = 8.dp),
        )
        if (proteinGoal != null && proteinGoal > 0) {
            LinearProgressIndicator(
                progress = { (protein / proteinGoal).toFloat().coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
            )
        }
    }
}
