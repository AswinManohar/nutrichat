package app.mealsy.android.ui.chat

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import app.mealsy.android.R
import app.mealsy.android.design.components.FilterChipPill
import app.mealsy.data.api.ReadbackDto

/** The plain chat text the backend reads as a yes / no answer to a readback. */
const val READBACK_YES = "yes"
const val READBACK_NO = "no"

/**
 * Yes / No chips under a coach reply that asks about a health fact. Tapping one
 * sends "yes" or "no" through [onAnswer], the same path as typing it.
 *
 * @param readback The open question; a `"retire"` kind words the chips as stopping the fact.
 * @param onAnswer Called with [READBACK_YES] or [READBACK_NO].
 */
@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
fun ReadbackChips(
    readback: ReadbackDto,
    onAnswer: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val retire = readback.kind == "retire"
    FlowRow(
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        modifier = modifier.padding(top = 8.dp),
    ) {
        FilterChipPill(
            text = stringResource(if (retire) R.string.chat_readback_yes_retire else R.string.chat_readback_yes),
            selected = false,
            onClick = { onAnswer(READBACK_YES) },
        )
        FilterChipPill(
            text = stringResource(if (retire) R.string.chat_readback_no_retire else R.string.chat_readback_no),
            selected = false,
            onClick = { onAnswer(READBACK_NO) },
        )
    }
}
