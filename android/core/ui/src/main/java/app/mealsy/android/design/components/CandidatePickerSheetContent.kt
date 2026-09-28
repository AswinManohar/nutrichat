package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.R
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import kotlin.math.roundToInt

/**
 * One selectable food row in [CandidatePickerSheetContent] — a suggestion
 * (from `candidate_details`) or a search result (from `GET /foods/search`).
 * A separate type from any DTO/domain shape so `:core:ui` doesn't depend on
 * `:core:data` — the host maps its own types onto this.
 */
data class PickerRow(
    val fdcId: Long,
    val name: String,
    val kcal: Double,
    val proteinG: Double,
    val isCurrent: Boolean = false,
)

/** The picker's search-results section state (`:core:ui`'s own copy — see [PickerRow]). */
sealed interface PickerResultsState {
    /** Fewer than 2 trimmed characters typed, or the field hasn't been used yet. */
    data object Idle : PickerResultsState

    data object Loading : PickerResultsState

    data class Loaded(val rows: List<PickerRow>) : PickerResultsState

    data object Empty : PickerResultsState

    /** Covers both a `503` and a network/timeout failure. */
    data object Unavailable : PickerResultsState
}

/**
 * The content of the "Not the right food?" bottom sheet from a confirm-card
 * food row (spec 003, `contracts/android-picker-ui.md`). Only the sheet's
 * content lives here — the `ModalBottomSheet` container itself is owned by
 * `:app`, so this composable can be golden-tested standalone without pulling
 * in a sheet host. Stateless: all state and callbacks are passed in.
 *
 * @param currentName The food row's currently selected name, shown in the
 *   "Currently: ..." line.
 * @param query The search field's current value.
 * @param onQueryChange Invoked as the user types.
 * @param online Whether the device has connectivity; the search field is
 *   disabled with "You're offline" when `false`.
 * @param resultsState The search-results section's current state.
 * @param onSelectResult Invoked with a search result's fdc id and name.
 * @param suggestions Alternatives from `candidate_details`, preview-scaled
 *   to the item's current grams (US2). The "Suggestions" section is hidden
 *   when this is empty.
 * @param onSelectSuggestion Invoked with a suggestion's fdc id and name.
 * @param onRemove Invoked when the user taps the trailing "None of these —
 *   remove it" row. `null` hides that row.
 * @param onDescribeDifferently Invoked with the user's free-text
 *   replacement once they submit it from "Describe it differently".
 *   `null` hides that row entirely.
 * @param modifier The modifier applied to the sheet content's column.
 */
@Composable
fun CandidatePickerSheetContent(
    currentName: String,
    query: String,
    onQueryChange: (String) -> Unit,
    online: Boolean,
    resultsState: PickerResultsState,
    onSelectResult: (fdcId: Long, name: String) -> Unit,
    modifier: Modifier = Modifier,
    suggestions: List<PickerRow> = emptyList(),
    onSelectSuggestion: (fdcId: Long, name: String) -> Unit = onSelectResult,
    onRemove: (() -> Unit)? = null,
    onDescribeDifferently: ((String) -> Unit)? = null,
) {
    val colors = MealsyTheme.colors
    var describing by rememberSaveable { mutableStateOf(false) }
    var description by rememberSaveable { mutableStateOf("") }

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

        Column(modifier = Modifier.padding(start = 16.dp, top = 12.dp, end = 16.dp, bottom = 0.dp)) {
            val searchLabel = stringResource(R.string.candidate_sheet_search_label)
            PillInput(
                value = query,
                onValueChange = onQueryChange,
                placeholder =
                    if (online) {
                        stringResource(R.string.candidate_sheet_search_placeholder)
                    } else {
                        stringResource(R.string.candidate_sheet_offline)
                    },
                enabled = online,
                keyboardOptions =
                    androidx.compose.foundation.text.KeyboardOptions(
                        imeAction = androidx.compose.ui.text.input.ImeAction.Search,
                    ),
                modifier = Modifier.fillMaxWidth().semantics { contentDescription = searchLabel },
            )
        }

        Column(modifier = Modifier.padding(top = 12.dp, bottom = 24.dp)) {
            if (suggestions.isNotEmpty()) {
                SectionHeading(stringResource(R.string.candidate_sheet_suggestions_heading))
                ListContainer(modifier = Modifier.padding(horizontal = 16.dp)) {
                    suggestions.forEachIndexed { index, row ->
                        PickerFoodRow(row = row, onClick = { onSelectSuggestion(row.fdcId, row.name) })
                        if (index != suggestions.lastIndex) InsetDivider()
                    }
                }
            }

            SectionHeading(stringResource(R.string.candidate_sheet_results_heading))
            ResultsAnnouncement(resultsState)
            ListContainer(modifier = Modifier.padding(horizontal = 16.dp)) {
                when (resultsState) {
                    PickerResultsState.Idle -> Unit
                    PickerResultsState.Loading -> {
                        repeat(3) { index ->
                            RowSkeleton()
                            if (index != 2) InsetDivider()
                        }
                    }

                    is PickerResultsState.Loaded -> {
                        resultsState.rows.forEachIndexed { index, row ->
                            PickerFoodRow(row = row, onClick = { onSelectResult(row.fdcId, row.name) })
                            if (index != resultsState.rows.lastIndex) InsetDivider()
                        }
                    }

                    PickerResultsState.Empty -> {
                        MessageRow(stringResource(R.string.candidate_sheet_no_results, query))
                    }

                    PickerResultsState.Unavailable -> {
                        MessageRow(stringResource(R.string.candidate_sheet_unavailable))
                    }
                }

                if (onDescribeDifferently != null) {
                    if (needsLeadingDivider(resultsState)) InsetDivider()
                    CandidateRow(
                        name = stringResource(R.string.candidate_sheet_describe_differently),
                        isCurrent = false,
                        onClick = { describing = !describing },
                    )
                    if (onRemove != null) InsetDivider()
                }
                if (onRemove != null) {
                    CandidateRow(
                        name = stringResource(R.string.candidate_sheet_none_of_these),
                        isCurrent = false,
                        muted = true,
                        onClick = onRemove,
                    )
                }
            }
            if (describing && onDescribeDifferently != null) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    PillInput(
                        value = description,
                        onValueChange = { description = it },
                        placeholder = stringResource(R.string.candidate_sheet_describe_placeholder),
                        modifier = Modifier.weight(1f),
                    )
                    MealsyButton(
                        text = stringResource(R.string.candidate_sheet_describe_submit),
                        onClick = {
                            val trimmed = description.trim()
                            if (trimmed.isNotEmpty()) {
                                onDescribeDifferently(trimmed)
                                describing = false
                                description = ""
                            }
                        },
                        style = MealsyButtonStyle.Secondary,
                        enabled = description.isNotBlank(),
                    )
                }
            }
        }
    }
}

/** Whether the results block above rendered any row, so the fallback rows need a leading divider. */
private fun needsLeadingDivider(state: PickerResultsState): Boolean =
    when (state) {
        PickerResultsState.Idle -> false
        PickerResultsState.Loading -> true
        is PickerResultsState.Loaded -> state.rows.isNotEmpty()
        PickerResultsState.Empty -> true
        PickerResultsState.Unavailable -> true
    }

/** Politely announces the result count once results load — FR-011's live-region requirement. */
@Composable
private fun ResultsAnnouncement(state: PickerResultsState) {
    if (state !is PickerResultsState.Loaded) return
    val text =
        androidx.compose.ui.res.pluralStringResource(
            R.plurals.candidate_sheet_results_announcement,
            state.rows.size,
            state.rows.size,
        )
    androidx.compose.foundation.layout.Box(
        modifier =
            Modifier
                .size(1.dp)
                .semantics {
                    liveRegion = LiveRegionMode.Polite
                    contentDescription = text
                },
    )
}

@Composable
private fun SectionHeading(text: String) {
    val colors = MealsyTheme.colors
    Text(
        text = text,
        style = MealsyType.label,
        color = colors.muted,
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
    )
}

@Composable
private fun MessageRow(text: String) {
    val colors = MealsyTheme.colors
    Text(
        text = text,
        style = MealsyType.body,
        color = colors.muted,
        modifier = Modifier.fillMaxWidth().defaultMinSize(minHeight = 48.dp).padding(vertical = 14.dp),
    )
}

@Composable
private fun RowSkeleton() {
    val colors = MealsyTheme.colors
    Row(
        modifier = Modifier.fillMaxWidth().defaultMinSize(minHeight = 48.dp).padding(vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Surface(
            modifier = Modifier.fillMaxWidth().size(16.dp),
            shape = RoundedCornerShape(4.dp),
            color = colors.surfacePressed,
        ) {}
    }
}

/**
 * One food row: name + "{kcal} kcal · {protein} g protein", with a check on
 * the current match. One merged semantics node per FR-011.
 */
@Composable
private fun PickerFoodRow(
    row: PickerRow,
    onClick: () -> Unit,
) {
    val colors = MealsyTheme.colors
    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()
    val background = if (pressed) colors.surfacePressed else Color.Transparent
    val kcalText = formatThousands(row.kcal.roundToInt())
    val proteinText = formatThousands(row.proteinG.roundToInt())
    val description =
        if (row.isCurrent) {
            stringResource(R.string.candidate_sheet_row_content_description_selected, row.name, kcalText, proteinText)
        } else {
            stringResource(R.string.candidate_sheet_row_content_description, row.name, kcalText, proteinText)
        }

    Row(
        modifier =
            Modifier
                .fillMaxWidth()
                .defaultMinSize(minHeight = 48.dp)
                .background(background)
                .clickable(interactionSource = interactionSource, indication = null, onClick = onClick)
                .semantics(mergeDescendants = true) {
                    role = Role.Button
                    selected = row.isCurrent
                    contentDescription = description
                }
                .padding(vertical = 12.dp, horizontal = 16.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        // Top-aligned rather than centered: a long name can wrap to 2-3
        // lines at larger font scales, and centering the checkmark against
        // the whole block makes it overlap the wrapped text (spec 003).
        verticalAlignment = Alignment.Top,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(text = row.name, style = MealsyType.body, color = colors.ink)
            Text(
                text = stringResource(R.string.candidate_sheet_row_kcal_protein, kcalText, proteinText),
                style = MealsyType.label,
                color = colors.muted,
            )
        }
        if (row.isCurrent) {
            Icon(
                imageVector = MealsyIcons.Check,
                contentDescription = null,
                tint = colors.ink,
                modifier = Modifier.padding(top = 2.dp).size(16.dp),
            )
        }
    }
}

/**
 * A fallback row ("Describe it differently" / "None of these — remove it"),
 * mirroring [PickerFoodRow]'s pressed-state handling but with plain text,
 * no macros.
 */
@Composable
private fun CandidateRow(
    name: String,
    isCurrent: Boolean,
    onClick: () -> Unit,
    muted: Boolean = false,
) {
    val colors = MealsyTheme.colors
    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()
    val background = if (pressed) colors.surfacePressed else Color.Transparent

    Row(
        modifier =
            Modifier
                .fillMaxWidth()
                .defaultMinSize(minHeight = 48.dp)
                .background(background)
                .clickable(interactionSource = interactionSource, indication = null, onClick = onClick)
                .semantics {
                    role = Role.Button
                    selected = isCurrent
                    contentDescription = if (isCurrent) "$name, current selection" else name
                }
                .padding(vertical = 14.dp, horizontal = 16.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text = name, style = MealsyType.body, color = if (muted) colors.muted else colors.ink)
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

private fun previewRow(
    name: String,
    fdcId: Long,
    isCurrent: Boolean = false,
) = PickerRow(fdcId = fdcId, name = name, kcal = 82.0, proteinG = 2.5, isCurrent = isCurrent)

@Preview(name = "CandidatePickerSheetContent loaded results", widthDp = 390)
@Composable
private fun CandidatePickerSheetContentLoadedPreview() {
    MealsyTheme {
        Surface(color = MealsyTheme.colors.surface) {
            CandidatePickerSheetContent(
                currentName = "Shrimp toast",
                query = "white bread toasted",
                onQueryChange = {},
                online = true,
                resultsState =
                    PickerResultsState.Loaded(
                        listOf(
                            previewRow("Bread, white, commercially prepared, toasted", 172687),
                            previewRow("Melba toast", 111222),
                        ),
                    ),
                onSelectResult = { _, _ -> },
                onRemove = {},
                onDescribeDifferently = {},
                modifier = Modifier.padding(top = 20.dp),
            )
        }
    }
}

@Preview(
    name = "CandidatePickerSheetContent loaded results dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun CandidatePickerSheetContentDarkPreview() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.surface) {
            CandidatePickerSheetContent(
                currentName = "Grilled chicken breast",
                query = "chicken",
                onQueryChange = {},
                online = true,
                resultsState = PickerResultsState.Loaded(listOf(previewRow("Roasted chicken breast", 42, isCurrent = true))),
                onSelectResult = { _, _ -> },
                modifier = Modifier.padding(top = 20.dp),
            )
        }
    }
}

@Preview(name = "CandidatePickerSheetContent loading", widthDp = 390)
@Composable
private fun CandidatePickerSheetContentLoadingPreview() {
    MealsyTheme {
        Surface(color = MealsyTheme.colors.surface) {
            CandidatePickerSheetContent(
                currentName = "Shrimp toast",
                query = "toa",
                onQueryChange = {},
                online = true,
                resultsState = PickerResultsState.Loading,
                onSelectResult = { _, _ -> },
                onRemove = {},
                onDescribeDifferently = {},
                modifier = Modifier.padding(top = 20.dp),
            )
        }
    }
}

@Preview(name = "CandidatePickerSheetContent empty", widthDp = 390)
@Composable
private fun CandidatePickerSheetContentEmptyPreview() {
    MealsyTheme {
        Surface(color = MealsyTheme.colors.surface) {
            CandidatePickerSheetContent(
                currentName = "Shrimp toast",
                query = "xyzzy",
                onQueryChange = {},
                online = true,
                resultsState = PickerResultsState.Empty,
                onSelectResult = { _, _ -> },
                onRemove = {},
                onDescribeDifferently = {},
                modifier = Modifier.padding(top = 20.dp),
            )
        }
    }
}

@Preview(name = "CandidatePickerSheetContent unavailable", widthDp = 390)
@Composable
private fun CandidatePickerSheetContentUnavailablePreview() {
    MealsyTheme {
        Surface(color = MealsyTheme.colors.surface) {
            CandidatePickerSheetContent(
                currentName = "Shrimp toast",
                query = "toast",
                onQueryChange = {},
                online = true,
                resultsState = PickerResultsState.Unavailable,
                onSelectResult = { _, _ -> },
                onRemove = {},
                onDescribeDifferently = {},
                modifier = Modifier.padding(top = 20.dp),
            )
        }
    }
}

@Preview(name = "CandidatePickerSheetContent offline", widthDp = 390)
@Composable
private fun CandidatePickerSheetContentOfflinePreview() {
    MealsyTheme {
        Surface(color = MealsyTheme.colors.surface) {
            CandidatePickerSheetContent(
                currentName = "Shrimp toast",
                query = "",
                onQueryChange = {},
                online = false,
                resultsState = PickerResultsState.Idle,
                onSelectResult = { _, _ -> },
                onRemove = {},
                onDescribeDifferently = {},
                modifier = Modifier.padding(top = 20.dp),
            )
        }
    }
}
