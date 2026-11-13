package app.mealsy.android.ui.profile

import androidx.annotation.PluralsRes
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
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
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.R
import app.mealsy.android.design.components.InsetDivider
import app.mealsy.android.design.components.ListContainer
import app.mealsy.android.design.components.MealsyButton
import app.mealsy.android.design.components.MealsyButtonStyle
import app.mealsy.android.design.components.MealsyDialog
import app.mealsy.android.design.components.PastelIconCircle
import app.mealsy.android.design.components.TagChip
import app.mealsy.android.design.components.TagTone
import app.mealsy.android.design.components.formatThousands
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.design.theme.mealsyScreenPadding
import app.mealsy.android.ui.common.ErrorKind
import app.mealsy.android.ui.common.ErrorState
import app.mealsy.android.ui.common.LoadingState
import app.mealsy.android.ui.settings.HeaderRow
import app.mealsy.data.api.HardEntryDto
import app.mealsy.data.api.LimitProgressDto
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.util.UUID
import kotlin.math.roundToInt

/** The tone and initial each entry type uses for its icon circle (and count chip on the Profile tab). */
internal fun CareType.tone(): TagTone =
    when (this) {
        CareType.Allergy -> TagTone.Pink
        CareType.Diagnosis -> TagTone.Powder
        CareType.Medication -> TagTone.Butter
        CareType.PhysicalLimitation -> TagTone.Leaf
        CareType.NutrientLimit, CareType.DietSetting, CareType.FoodExclusion -> TagTone.Powder
    }

private fun CareType.initial(): Char = stringInitial[this] ?: '?'

private val stringInitial =
    mapOf(
        CareType.Allergy to 'A',
        CareType.Diagnosis to 'D',
        CareType.Medication to 'M',
        CareType.PhysicalLimitation to 'P',
        CareType.NutrientLimit to 'N',
        CareType.DietSetting to 'S',
        CareType.FoodExclusion to 'F',
    )

/** What the editor sheet is open for: a new entry, or an existing one. */
private sealed interface Editor {
    data object Add : Editor

    data class Edit(val entry: HardEntryDto) : Editor
}

/**
 * The Care profile screen: everything Mealsy treats as a hard constraint for this patient,
 * grouped by type, with today's progress against nutrient limits. State comes from
 * [CareProfileViewModel], shared with the Profile tab.
 *
 * @param onBack Pops back to the Profile tab.
 * @param onOpenHistory Opens the entry history.
 */
@Composable
fun CareProfileScreen(
    onBack: () -> Unit,
    onOpenHistory: () -> Unit,
    viewModel: CareProfileViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val save by viewModel.save.collectAsStateWithLifecycle()
    var editor by remember { mutableStateOf<Editor?>(null) }
    var retiring by remember { mutableStateOf<HardEntryDto?>(null) }

    CareProfileContent(
        uiState = uiState,
        onBack = onBack,
        onRetry = { viewModel.load() },
        onAdd = { editor = Editor.Add },
        onEdit = { editor = Editor.Edit(it) },
        onConfirm = { viewModel.confirm(it.id) },
        onDeny = { viewModel.deny(it.id) },
        onRetireInferred = { retiring = it },
        onOpenHistory = onOpenHistory,
        actionFailed = save.failed && editor == null,
        modifier = Modifier.fillMaxSize(),
    )

    retiring?.let { entry ->
        MealsyDialog(
            onDismissRequest = { retiring = null },
            title = stringResource(R.string.entry_retire_title),
            body = stringResource(R.string.entry_retire_body, entry.label),
            buttons = {
                MealsyButton(
                    text = stringResource(R.string.entry_retire_confirm),
                    onClick = {
                        retiring = null
                        viewModel.retire(entry.id, UUID.randomUUID().toString()) {}
                    },
                    style = MealsyButtonStyle.Destructive,
                )
                MealsyButton(
                    text = stringResource(R.string.settings_cancel),
                    onClick = { retiring = null },
                    style = MealsyButtonStyle.Secondary,
                )
            },
        )
    }

    editor?.let { target ->
        val close = {
            viewModel.clearSaveError()
            editor = null
        }
        val entry = (target as? Editor.Edit)?.entry
        EntryEditorSheet(
            entry = entry,
            save = save,
            onSave = { type, value, requestId -> viewModel.saveEntry(type, value, entry?.id, requestId, close) },
            onRetire = { requestId -> entry?.let { viewModel.retire(it.id, requestId, close) } },
            onDismiss = close,
        )
    }
}

/**
 * Stateless render of [CareProfileScreen], driven by hand-built state in goldens.
 *
 * @param initiallyExpanded Sections that start expanded.
 * @param onConfirm Confirms a pending entry or acknowledges an inferred one.
 * @param onDeny Rejects a pending entry.
 * @param onRetireInferred Asks to remove an inferred entry (the screen confirms first).
 * @param onOpenHistory Opens the entry history.
 * @param actionFailed Whether the last confirm, deny or remove failed.
 */
@Composable
fun CareProfileContent(
    uiState: CareProfileUiState,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    onAdd: () -> Unit,
    onEdit: (HardEntryDto) -> Unit,
    modifier: Modifier = Modifier,
    initiallyExpanded: Set<CareType> = emptySet(),
    onConfirm: (HardEntryDto) -> Unit = {},
    onDeny: (HardEntryDto) -> Unit = {},
    onRetireInferred: (HardEntryDto) -> Unit = {},
    onOpenHistory: () -> Unit = {},
    actionFailed: Boolean = false,
) {
    Column(modifier = modifier.verticalScroll(rememberScrollState()).mealsyScreenPadding()) {
        HeaderRow(title = stringResource(R.string.care_eyebrow), onBack = onBack)
        Spacer(modifier = Modifier.height(20.dp))
        when (uiState) {
            CareProfileUiState.Loading -> LoadingState(stringResource(R.string.care_loading), Modifier.height(240.dp))
            is CareProfileUiState.Error ->
                ErrorState(
                    message =
                        uiState.message
                            ?: stringResource(
                                if (uiState.kind == ErrorKind.Offline) R.string.error_offline else R.string.care_error_load_failed,
                            ),
                    onRetry = onRetry,
                    modifier = Modifier.height(240.dp),
                )
            is CareProfileUiState.Loaded ->
                LoadedBody(
                    data = uiState.data,
                    actions = EntryActions(onConfirm, onDeny, onRetireInferred),
                    onAdd = onAdd,
                    onEdit = onEdit,
                    onOpenHistory = onOpenHistory,
                    actionFailed = actionFailed,
                    initiallyExpanded = initiallyExpanded,
                )
        }
    }
}

@Composable
private fun LoadedBody(
    data: CareProfileData,
    actions: EntryActions,
    onAdd: () -> Unit,
    onEdit: (HardEntryDto) -> Unit,
    onOpenHistory: () -> Unit,
    actionFailed: Boolean,
    initiallyExpanded: Set<CareType>,
) {
    val colors = MealsyTheme.colors
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text(text = stringResource(R.string.care_title), style = MealsyType.screenTitle, color = colors.ink)
        Text(
            text = stringResource(R.string.care_history),
            style = MealsyType.body,
            color = colors.ink,
            modifier =
                Modifier
                    .defaultMinSize(minHeight = 48.dp)
                    .clickable(role = Role.Button, onClick = onOpenHistory)
                    .padding(horizontal = 8.dp)
                    .wrapContentHeight(Alignment.CenterVertically),
        )
    }
    CareSubtitle(data)
    if (actionFailed) {
        Spacer(modifier = Modifier.height(8.dp))
        Text(text = stringResource(R.string.care_action_failed), style = MealsyType.label, color = colors.terracottaOutlineText)
    }
    val limits = data.limits
    if (limits != null && limits.total > 0) {
        Spacer(modifier = Modifier.height(16.dp))
        Surface(modifier = Modifier.fillMaxWidth(), shape = MealsyShapes.card, color = colors.olive) {
            Text(
                text =
                    pluralStringResource(R.plurals.care_limits_on_track, limits.total, limits.onTrack, limits.total) +
                        " " + stringResource(R.string.care_today),
                style = MealsyType.body,
                color = colors.oliveText,
                modifier = Modifier.padding(16.dp),
            )
        }
    }
    Spacer(modifier = Modifier.height(20.dp))
    val sections = CareType.entries.filter { data.of(it).isNotEmpty() }
    if (sections.isEmpty()) {
        Text(text = stringResource(R.string.care_empty), style = MealsyType.body, color = colors.muted)
    } else {
        ListContainer {
            sections.forEachIndexed { index, type ->
                if (index > 0) InsetDivider()
                CareSection(type, data, actions, onEdit, startExpanded = type in initiallyExpanded)
            }
        }
    }
    Spacer(modifier = Modifier.height(20.dp))
    MealsyButton(
        text = stringResource(R.string.care_add),
        onClick = onAdd,
        modifier = Modifier.fillMaxWidth(),
        style = MealsyButtonStyle.Secondary,
    )
}

/** "Updated {date}" plus the care-team line, the latter only when someone is on the team. */
@Composable
private fun CareSubtitle(data: CareProfileData) {
    val colors = MealsyTheme.colors
    data.updatedOn?.let {
        Text(
            text = stringResource(R.string.care_updated, it.format(DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM))),
            style = MealsyType.label,
            color = colors.muted,
        )
    }
    if (data.careTeam.isNotEmpty()) {
        Text(text = careTeamLine(data), style = MealsyType.label, color = colors.muted)
    }
}

/** "Shared with Name, role; ..." for a non-empty care team. */
@Composable
internal fun careTeamLine(data: CareProfileData): String {
    val members = data.careTeam.map { stringResource(R.string.care_team_member, it.name, it.role) }
    return stringResource(R.string.care_shared_with, members.joinToString("; "))
}

/** One expandable row (icon, title, count badge, rotating chevron) and, when open, its entries. */
@Composable
private fun CareSection(
    type: CareType,
    data: CareProfileData,
    actions: EntryActions,
    onEdit: (HardEntryDto) -> Unit,
    startExpanded: Boolean,
) {
    val colors = MealsyTheme.colors
    var expanded by rememberSaveable(type) { mutableStateOf(startExpanded) }
    val entries = data.of(type)
    val title = stringResource(careTypeTitle(type))
    val state = stringResource(if (expanded) R.string.care_collapse else R.string.care_expand, title)
    Row(
        modifier =
            Modifier
                .fillMaxWidth()
                .defaultMinSize(minHeight = 48.dp)
                .clickable(role = Role.Button) { expanded = !expanded }
                .semantics { stateDescription = state }
                .padding(vertical = 9.dp, horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        PastelIconCircle(initial = type.initial(), tone = type.tone())
        Text(text = title, style = MealsyType.body, color = colors.ink, modifier = Modifier.weight(1f))
        Surface(shape = MealsyShapes.pill, color = colors.ink) {
            Text(
                text = entries.size.toString(),
                style = MealsyType.badge,
                color = colors.canvas,
                modifier = Modifier.padding(vertical = 2.dp, horizontal = 9.dp),
            )
        }
        Icon(
            imageVector = MealsyIcons.ChevronRight,
            contentDescription = null,
            tint = colors.inactive,
            modifier = Modifier.size(13.dp).rotate(if (expanded) 90f else 0f),
        )
    }
    if (expanded) {
        val limitsByEntry = data.limits?.limits.orEmpty().associateBy { it.entryId }
        entries.forEach { entry ->
            val editable = type in EDITABLE_TYPES && entry.state == "confirmed"
            Column(
                modifier =
                    Modifier
                        .fillMaxWidth()
                        .then(if (editable) Modifier.clickable(role = Role.Button) { onEdit(entry) } else Modifier)
                        .padding(start = 62.dp, end = 16.dp, top = 6.dp, bottom = 10.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                EntryBody(entry, limitsByEntry[entry.id])
                EntryReview(entry, actions)
            }
        }
    }
}

@Composable
private fun EntryBody(
    entry: HardEntryDto,
    limit: LimitProgressDto?,
) {
    val colors = MealsyTheme.colors
    if (limit == null) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(text = entry.label, style = MealsyType.body, color = colors.ink, modifier = Modifier.weight(1f, fill = false))
            if (entry.state == "pending") TagChip(stringResource(R.string.care_awaiting), TagTone.Butter)
            if (entry.needsAcknowledgement()) TagChip(stringResource(R.string.care_inferred), TagTone.Powder)
        }
        return
    }
    val name = NUTRIENTS[limit.nutrient]?.let { stringResource(it.first) } ?: limit.nutrient
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text(text = name, style = MealsyType.body, color = colors.ink)
        Text(text = limit.label, style = MealsyType.label, color = colors.muted)
    }
    LimitBar(soFar = limit.soFar, amount = limit.amount, over = !limit.onTrack)
    val soFar = formatAmount(limit.soFar)
    Text(
        text =
            stringResource(
                if (limit.unknownItems > 0) R.string.care_so_far_unknown else R.string.care_so_far,
                soFar,
                limit.unit,
            ),
        style = MealsyType.label,
        color = if (limit.onTrack) colors.muted else colors.terracottaOutlineText,
    )
}

/** What the patient can do with entries that need a decision. */
private class EntryActions(
    val onConfirm: (HardEntryDto) -> Unit,
    val onDeny: (HardEntryDto) -> Unit,
    val onRetireInferred: (HardEntryDto) -> Unit,
)

/** An inferred entry the patient has not yet agreed with. */
private fun HardEntryDto.needsAcknowledgement(): Boolean = source == "inferred" && state == "confirmed" && !acknowledged

/** Confirm / Not right for a pending entry; That's right / Not right for an inferred one. */
@Composable
private fun EntryReview(
    entry: HardEntryDto,
    actions: EntryActions,
) {
    val pending = entry.state == "pending"
    if (!pending && !entry.needsAcknowledgement()) return
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
        MealsyButton(
            text = stringResource(if (pending) R.string.care_confirm else R.string.care_thats_right),
            onClick = { actions.onConfirm(entry) },
            modifier = Modifier.weight(1f),
        )
        MealsyButton(
            text = stringResource(R.string.care_not_right),
            onClick = { if (pending) actions.onDeny(entry) else actions.onRetireInferred(entry) },
            modifier = Modifier.weight(1f),
            style = MealsyButtonStyle.Secondary,
        )
    }
}

/** Today's intake as a bar filled to `soFar / amount` (capped at 1) with a marker at the limit. */
@Composable
private fun LimitBar(
    soFar: Double,
    amount: Double,
    over: Boolean,
) {
    val colors = MealsyTheme.colors
    val fraction = if (amount > 0) (soFar / amount).toFloat().coerceIn(0f, 1f) else 0f
    Box(
        modifier = Modifier.fillMaxWidth().height(8.dp).background(colors.divider, MealsyShapes.pill),
    ) {
        Box(
            modifier =
                Modifier
                    .fillMaxWidth(fraction)
                    .fillMaxHeight()
                    .background(if (over) colors.terracotta else colors.ink, MealsyShapes.pill),
        )
        Box(modifier = Modifier.align(Alignment.CenterEnd).width(2.dp).fillMaxHeight().background(colors.muted))
    }
}

private fun formatAmount(value: Double): String =
    if (value >= 10) formatThousands(value.roundToInt()) else "%.1f".format(value).removeSuffix(".0")

/**
 * The count chip text for [type] on the Profile tab card, e.g. "3 allergies"; null for types
 * the card does not summarise.
 */
@PluralsRes
internal fun chipPlural(type: CareType): Int? =
    when (type) {
        CareType.Allergy -> R.plurals.care_chip_allergy
        CareType.Diagnosis -> R.plurals.care_chip_diagnosis
        CareType.Medication -> R.plurals.care_chip_medication
        CareType.PhysicalLimitation -> R.plurals.care_chip_limitation
        CareType.NutrientLimit -> R.plurals.care_chip_nutrient_limit
        CareType.DietSetting, CareType.FoodExclusion -> null
    }
