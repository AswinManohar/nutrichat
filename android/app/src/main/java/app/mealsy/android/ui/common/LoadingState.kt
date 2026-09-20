package app.mealsy.android.ui.common

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier

/**
 * Shared full-screen loading placeholder — [message] names what's loading
 * (e.g. "Loading trends…") so screens keep a distinct, screen-specific copy
 * instead of a generic spinner. Extracted from `TrendsScreen`/`MyMealsScreen`,
 * which had near-identical private composables before Task 14's sweep.
 */
@Composable
fun LoadingState(
    message: String,
    modifier: Modifier = Modifier,
) {
    Box(modifier = modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(message)
    }
}
