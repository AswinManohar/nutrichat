package app.mealsy.android.ui.common

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp

import app.mealsy.android.R

/**
 * Shared full-screen error state: [message] plus a "Retry" button calling
 * [onRetry]. Extracted from `TrendsScreen`/`MyMealsScreen`, which had
 * identical private composables before Task 14's sweep — see `ChatScreen`
 * and `SettingsScreen` for why they keep their own, bespoke error
 * presentation instead of this one (documented at each call site).
 */
@Composable
fun ErrorState(message: String, onRetry: () -> Unit, modifier: Modifier = Modifier) {
    Box(modifier = modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(message, modifier = Modifier.padding(bottom = 16.dp))
            Button(onClick = onRetry) { Text(stringResource(R.string.common_retry)) }
        }
    }
}
