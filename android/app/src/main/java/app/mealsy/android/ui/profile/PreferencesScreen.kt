package app.mealsy.android.ui.profile

import androidx.annotation.StringRes
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.R
import app.mealsy.android.design.components.Eyebrow
import app.mealsy.android.design.components.FilterChipPill
import app.mealsy.android.design.components.InsetDivider
import app.mealsy.android.design.components.ListContainer
import app.mealsy.android.design.components.MealsyButton
import app.mealsy.android.design.components.MealsyButtonStyle
import app.mealsy.android.design.components.MealsyDialog
import app.mealsy.android.design.components.PillInput
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.data.api.SoftFactDto

/** Soft-fact kinds in display order, with their wire value. */
private val KIND_LABELS =
    linkedMapOf(
        "like" to R.string.remembers_kind_like,
        "dislike" to R.string.remembers_kind_dislike,
        "cuisine" to R.string.remembers_kind_cuisine,
        "budget" to R.string.remembers_kind_budget,
        "cooking_time" to R.string.remembers_kind_cooking_time,
        "habit" to R.string.remembers_kind_habit,
        "context" to R.string.remembers_kind_context,
    )

/** The kinds the editor offers: the ones the server accepts today. */
private val EDITABLE_KINDS = listOf("like", "dislike", "cuisine", "budget", "cooking_time", "habit", "context")

@StringRes
private fun kindTitle(kind: String): Int = KIND_LABELS[kind] ?: R.string.remembers_kind_other

/** What Mealsy remembers about the patient's tastes and habits, with edit and delete. */
@Composable
fun PreferencesScreen(
    onBack: () -> Unit,
    viewModel: PreferencesViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val save by viewModel.save.collectAsStateWithLifecycle()
    var editing by remember { mutableStateOf<SoftFactDto?>(null) }

    PreferencesContent(
        state = state,
        onBack = onBack,
        onRetry = { viewModel.load() },
        onEdit = { editing = it },
        modifier = Modifier.fillMaxSize(),
    )

    editing?.let { fact ->
        val close = {
            viewModel.clearSaveError()
            editing = null
        }
        PreferenceEditSheet(
            fact = fact,
            save = save,
            onSave = { text, kind -> viewModel.edit(fact.id, text, kind, close) },
            onDelete = { viewModel.delete(fact.id, close) },
            onDismiss = close,
        )
    }
}

/** Stateless render of [PreferencesScreen]: facts grouped by kind, each with "since {date}". */
@Composable
fun PreferencesContent(
    state: LoadState<List<SoftFactDto>>,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    onEdit: (SoftFactDto) -> Unit,
    modifier: Modifier = Modifier,
) {
    LoadStateScreen(
        title = stringResource(R.string.remembers_title),
        state = state,
        loadingText = stringResource(R.string.remembers_loading),
        errorText = stringResource(R.string.remembers_error),
        onBack = onBack,
        onRetry = onRetry,
        modifier = modifier,
    ) { facts ->
        if (facts.isEmpty()) {
            Text(text = stringResource(R.string.remembers_empty), style = MealsyType.body, color = MealsyTheme.colors.muted)
            return@LoadStateScreen
        }
        val groups = facts.groupBy { if (it.kind in KIND_LABELS) it.kind else "other" }
        (KIND_LABELS.keys + "other").filter { it in groups }.forEachIndexed { index, kind ->
            if (index > 0) Spacer(modifier = Modifier.height(24.dp))
            Eyebrow(text = stringResource(kindTitle(kind)))
            Spacer(modifier = Modifier.height(10.dp))
            ListContainer {
                groups.getValue(kind).forEachIndexed { i, fact ->
                    if (i > 0) InsetDivider()
                    FactRow(fact, onEdit)
                }
            }
        }
    }
}

@Composable
private fun FactRow(
    fact: SoftFactDto,
    onEdit: (SoftFactDto) -> Unit,
) {
    val colors = MealsyTheme.colors
    Column(
        modifier =
            Modifier
                .fillMaxWidth()
                .defaultMinSize(minHeight = 48.dp)
                .clickable(role = Role.Button, onClickLabel = stringResource(R.string.remembers_edit, fact.text)) { onEdit(fact) }
                .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text(text = fact.text, style = MealsyType.body, color = colors.ink)
        formatDate(fact.createdAt)?.let {
            Text(text = stringResource(R.string.remembers_since, it), style = MealsyType.label, color = colors.muted)
        }
    }
}

/** Bottom sheet to change a preference's text and kind, or delete it after a confirmation. */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun PreferenceEditSheet(
    fact: SoftFactDto,
    save: CareSaveState,
    onSave: (text: String, kind: String) -> Unit,
    onDelete: () -> Unit,
    onDismiss: () -> Unit,
) {
    val colors = MealsyTheme.colors
    var text by remember { mutableStateOf(fact.text) }
    var kind by remember { mutableStateOf(fact.kind) }
    var confirmDelete by remember { mutableStateOf(false) }
    val kinds = if (fact.kind in EDITABLE_KINDS || fact.kind.isBlank()) EDITABLE_KINDS else listOf(fact.kind) + EDITABLE_KINDS

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = colors.surface,
        shape = RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp),
    ) {
        Column(
            modifier = Modifier.verticalScroll(rememberScrollState()).navigationBarsPadding().padding(horizontal = 20.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(text = stringResource(R.string.remembers_edit_title), style = MealsyType.section, color = colors.ink)
            Eyebrow(text = stringResource(R.string.remembers_field_text))
            PillInput(value = text, onValueChange = { text = it }, modifier = Modifier.fillMaxWidth())
            Eyebrow(text = stringResource(R.string.remembers_field_kind))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                kinds.forEach { k -> FilterChipPill(stringResource(kindTitle(k)), kind == k, { kind = k }) }
            }
            if (save.failed) {
                Text(stringResource(R.string.remembers_failed), style = MealsyType.label, color = colors.terracottaOutlineText)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                MealsyButton(
                    text = stringResource(R.string.remembers_save),
                    onClick = { onSave(text.trim(), kind) },
                    modifier = Modifier.weight(1f),
                    enabled = text.isNotBlank() && !save.saving,
                )
                MealsyButton(
                    text = stringResource(R.string.remembers_delete),
                    onClick = { confirmDelete = true },
                    modifier = Modifier.weight(1f),
                    style = MealsyButtonStyle.Destructive,
                    enabled = !save.saving,
                )
            }
        }
    }

    if (confirmDelete) {
        MealsyDialog(
            onDismissRequest = { confirmDelete = false },
            title = stringResource(R.string.remembers_delete_title),
            body = stringResource(R.string.remembers_delete_body, fact.text),
            buttons = {
                MealsyButton(
                    text = stringResource(R.string.remembers_delete),
                    onClick = {
                        confirmDelete = false
                        onDelete()
                    },
                    style = MealsyButtonStyle.Destructive,
                )
                MealsyButton(
                    text = stringResource(R.string.settings_cancel),
                    onClick = { confirmDelete = false },
                    style = MealsyButtonStyle.Secondary,
                )
            },
        )
    }
}
