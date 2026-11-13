package app.mealsy.android.ui.profile

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
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
import app.mealsy.android.design.components.InsetDivider
import app.mealsy.android.design.components.ListContainer
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.data.api.HardEntryDto

/** Every Care profile entry, newest first, including ones that were removed or replaced. */
@Composable
fun EntryHistoryScreen(
    onBack: () -> Unit,
    viewModel: EntryHistoryViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    EntryHistoryContent(state = state, onBack = onBack, onRetry = { viewModel.load() }, modifier = Modifier.fillMaxSize())
}

/** Stateless render of [EntryHistoryScreen]. */
@Composable
fun EntryHistoryContent(
    state: LoadState<List<HardEntryDto>>,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    LoadStateScreen(
        title = stringResource(R.string.history_title),
        state = state,
        loadingText = stringResource(R.string.history_loading),
        errorText = stringResource(R.string.history_error),
        onBack = onBack,
        onRetry = onRetry,
        modifier = modifier,
    ) { entries ->
        if (entries.isEmpty()) {
            Text(text = stringResource(R.string.history_empty), style = MealsyType.body, color = MealsyTheme.colors.muted)
        } else {
            ListContainer {
                entries.forEachIndexed { index, entry ->
                    if (index > 0) InsetDivider()
                    HistoryRow(entry)
                }
            }
        }
    }
}

@Composable
private fun HistoryRow(entry: HardEntryDto) {
    val colors = MealsyTheme.colors
    val retired = entry.retiredAt != null
    val type = CareType.entries.firstOrNull { it.wire == entry.type }?.let { stringResource(careTypeTitle(it)) }
    Column(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text(text = entry.label, style = MealsyType.body, color = if (retired) colors.muted else colors.ink)
        val added = formatDate(entry.createdAt)
        val meta = listOfNotNull(type, added?.let { stringResource(R.string.history_since, it) }).joinToString(", ")
        if (meta.isNotEmpty()) Text(text = meta, style = MealsyType.label, color = colors.muted)
        if (retired) {
            val date = formatDate(entry.retiredAt).orEmpty()
            val reason =
                when (entry.retiredReason) {
                    "denied" -> stringResource(R.string.history_reason_denied)
                    "replaced" -> stringResource(R.string.history_reason_replaced)
                    else -> null
                }
            Text(
                text =
                    if (reason == null) {
                        stringResource(R.string.history_retired, date)
                    } else {
                        stringResource(R.string.history_retired_reason, date, reason)
                    },
                style = MealsyType.label,
                color = colors.muted,
            )
        }
        if (entry.replacesId != null) {
            Text(text = stringResource(R.string.history_replaces), style = MealsyType.label, color = colors.muted)
        }
    }
}
