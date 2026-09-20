package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.R
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * The content of the "Not the right food?" bottom sheet from a confirm-card
 * food row (README §5 item 3). Only the sheet's content lives here — the
 * `ModalBottomSheet` container itself is owned by `:app`, so this composable
 * can be golden-tested standalone without pulling in a sheet host.
 *
 * @param currentName The food row's currently selected name, shown both in
 *   the "Currently: ..." line and via a check icon on the matching row.
 * @param candidates The alternate food names to choose from. The entry
 *   equal to [currentName], if present, is still tappable — re-selecting
 *   the current food is a no-op for the caller but not disabled here.
 * @param onSelect Invoked with the tapped candidate's name.
 * @param modifier The modifier applied to the sheet content's column.
 */
@Composable
fun CandidatePickerSheetContent(
    currentName: String,
    candidates: List<String>,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    Column(modifier = modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Eyebrow(text = stringResource(R.string.candidate_sheet_eyebrow))
            Text(
                text = stringResource(R.string.candidate_sheet_current, currentName),
                style = MealsyType.label,
                color = colors.muted,
            )
        }
        Column(modifier = Modifier.padding(top = 12.dp, bottom = 24.dp)) {
            ListContainer(modifier = Modifier.padding(horizontal = 16.dp)) {
                candidates.forEachIndexed { index, candidate ->
                    CandidateRow(
                        name = candidate,
                        isCurrent = candidate == currentName,
                        onClick = { onSelect(candidate) },
                    )
                    if (index != candidates.lastIndex) InsetDivider()
                }
            }
        }
    }
}

/**
 * One selectable row inside [CandidatePickerSheetContent], mirroring
 * [ListRow]'s pressed-state handling but with a leading check icon on the
 * current candidate instead of a chevron.
 */
@Composable
private fun CandidateRow(
    name: String,
    isCurrent: Boolean,
    onClick: () -> Unit,
) {
    val colors = MealsyTheme.colors
    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()
    val background = if (pressed) colors.surfacePressed else Color.Transparent

    Row(
        modifier =
            Modifier
                .fillMaxWidth()
                .background(background)
                .clickable(
                    interactionSource = interactionSource,
                    indication = null,
                    onClick = onClick,
                )
                .semantics {
                    role = Role.Button
                    selected = isCurrent
                    contentDescription = if (isCurrent) "$name, current selection" else name
                }
                .padding(vertical = 14.dp, horizontal = 16.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text = name, style = MealsyType.body, color = colors.ink)
        if (isCurrent) {
            Icon(
                imageVector = MealsyIcons.Check,
                contentDescription = null,
                tint = colors.ink,
                modifier = Modifier.size(16.dp),
            )
        }
    }
}

@Preview(name = "CandidatePickerSheetContent light", widthDp = 390)
@Composable
private fun CandidatePickerSheetContentLightPreview() {
    MealsyTheme {
        Surface(color = MealsyTheme.colors.surface) {
            CandidatePickerSheetContent(
                currentName = "Vinaigrette dressing",
                candidates =
                    listOf(
                        "Vinaigrette dressing",
                        "Balsamic vinaigrette",
                        "Italian dressing",
                        "Red wine vinaigrette",
                    ),
                onSelect = {},
                modifier = Modifier.padding(top = 20.dp),
            )
        }
    }
}

@Preview(
    name = "CandidatePickerSheetContent dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun CandidatePickerSheetContentDarkPreview() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.surface) {
            CandidatePickerSheetContent(
                currentName = "Grilled chicken breast",
                candidates = listOf("Grilled chicken breast", "Roasted chicken breast"),
                onSelect = {},
                modifier = Modifier.padding(top = 20.dp),
            )
        }
    }
}
