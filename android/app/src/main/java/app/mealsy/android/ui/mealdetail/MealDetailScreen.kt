package app.mealsy.android.ui.mealdetail

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.R
import app.mealsy.android.design.components.CircleIconButton
import app.mealsy.android.design.components.CoachNote
import app.mealsy.android.design.components.Eyebrow
import app.mealsy.android.design.components.InkToast
import app.mealsy.android.design.components.InsetDivider
import app.mealsy.android.design.components.ListContainer
import app.mealsy.android.design.components.MealsyButton
import app.mealsy.android.design.components.MealsyButtonStyle
import app.mealsy.android.design.components.MetaTag
import app.mealsy.android.design.components.PastelIconCircle
import app.mealsy.android.design.components.SegmentedControl
import app.mealsy.android.design.components.StatusPillPlain
import app.mealsy.android.design.components.TagTone
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.design.theme.mealsyScreenPadding
import app.mealsy.android.ui.common.ErrorState
import app.mealsy.android.ui.common.LoadingState
import app.mealsy.android.ui.meals.formatLoggedAtTime
import androidx.compose.ui.platform.LocalContext

/**
 * Meal detail: shows a logged meal or a saved "My Meal", with a "log again"
 * bottom sheet and (logged mode only) delete.
 *
 * @param onBack Navigates back.
 * @param onDeleted Called once the logged meal has actually been deleted —
 *   the caller pops the back stack.
 * @param onLogged Called once a log-again submission succeeds — the caller
 *   pops (or otherwise navigates away, e.g. back to Home).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MealDetailScreen(
    onBack: () -> Unit,
    onDeleted: () -> Unit,
    onLogged: () -> Unit,
    viewModel: MealDetailViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val sheet by viewModel.sheetState.collectAsStateWithLifecycle()
    var showDeleteDialog by remember { mutableStateOf(false) }
    var showLoggedToast by remember { mutableStateOf(false) }

    LaunchedEffect(viewModel) {
        viewModel.events.collect { event ->
            when (event) {
                MealDetailEvent.Deleted -> onDeleted()
                MealDetailEvent.Logged -> {
                    showLoggedToast = true
                    onLogged()
                }
            }
        }
    }

    if (showDeleteDialog) {
        DeleteMealDialog(
            onConfirm = {
                showDeleteDialog = false
                viewModel.delete()
            },
            onDismiss = { showDeleteDialog = false },
        )
    }

    Box(modifier = Modifier.fillMaxSize()) {
        when (val s = state) {
            MealDetailUiState.Loading ->
                LoadingState(message = stringResource(R.string.meal_detail_loading), modifier = Modifier.fillMaxSize())
            is MealDetailUiState.Error ->
                ErrorState(message = s.message, onRetry = viewModel::retry, modifier = Modifier.fillMaxSize())
            is MealDetailUiState.Loaded -> MealDetailContent(
                state = s,
                onBack = onBack,
                onLogAgain = viewModel::openSheet,
                onEditPortions = viewModel::editPortions,
                onDeleteRequested = { showDeleteDialog = true },
                modifier = Modifier.fillMaxSize(),
            )
        }

        if (showLoggedToast) {
            InkToast(
                text = stringResource(R.string.meal_detail_logged_toast),
                modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 24.dp),
            )
        }
    }

    if (sheet.visible) {
        LogAgainSheet(
            sheet = sheet,
            isMyMeal = viewModel.mode is MealDetailMode.MyMeal,
            onSelectMealType = viewModel::selectSheetMealType,
            onSelectPortion = viewModel::selectSheetPortion,
            onConfirm = viewModel::confirmSheet,
            onDismiss = viewModel::dismissSheet,
        )
    }
}

@Composable
private fun MealDetailContent(
    state: MealDetailUiState.Loaded,
    onBack: () -> Unit,
    onLogAgain: () -> Unit,
    onEditPortions: () -> Unit,
    onDeleteRequested: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    Column(
        modifier = modifier
            .verticalScroll(rememberScrollState())
            .mealsyScreenPadding(showsBottomNav = false),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            CircleIconButton(
                icon = MealsyIcons.ChevronLeft,
                contentDescription = stringResource(R.string.meal_detail_back),
                onClick = onBack,
            )
            Eyebrow(text = headerEyebrow(state))
            Spacer(modifier = Modifier.width(38.dp))
        }

        Spacer(modifier = Modifier.height(14.dp))

        Surface(
            modifier = Modifier.fillMaxWidth().height(210.dp),
            shape = RoundedCornerShape(18.dp),
            color = colors.surface,
        ) {
            Box(contentAlignment = Alignment.Center) {
                PastelIconCircle(
                    icon = mealDetailIcon(state.mealType),
                    tone = state.heroTone,
                    size = 36.dp,
                    contentDescription = null,
                )
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        Text(text = state.title, style = MealsyType.display, color = colors.ink)

        Spacer(modifier = Modifier.height(12.dp))

        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            MetaTag(text = stringResource(R.string.meal_detail_kcal_chip, state.kcal), tone = TagTone.Butter)
            MetaTag(text = stringResource(R.string.meal_detail_protein_chip, state.proteinG), tone = TagTone.Leaf)
            when (state.thirdTag) {
                MealDetailThirdTag.UsdaVerified ->
                    MetaTag(text = stringResource(R.string.meal_detail_usda_verified), tone = TagTone.Powder)
                MealDetailThirdTag.Estimated ->
                    MetaTag(text = stringResource(R.string.meal_detail_estimated), tone = TagTone.Powder)
                MealDetailThirdTag.None -> Unit
            }
        }

        Spacer(modifier = Modifier.height(18.dp))

        val (statusLabel, statusValue) = statusText(state.status)
        StatusPillPlain(label = statusLabel, value = statusValue)

        Spacer(modifier = Modifier.height(24.dp))

        Text(text = stringResource(R.string.meal_detail_whats_in_it), style = MealsyType.section, color = colors.ink)

        Spacer(modifier = Modifier.height(10.dp))

        ListContainer {
            state.items.forEachIndexed { index, item ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 12.dp, horizontal = 16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(text = item.humanizedName, style = MealsyType.body, color = colors.ink)
                        if (item.rawName != null) {
                            Text(
                                text = item.rawName,
                                style = MealsyType.label,
                                color = colors.muted,
                            )
                        }
                    }
                    Text(
                        text = stringResource(R.string.meal_detail_item_meta, item.qtyG, item.kcal),
                        style = MealsyType.label,
                        color = colors.muted,
                    )
                }
                if (index != state.items.lastIndex) InsetDivider()
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        coachNoteText(state.coachNote)?.let { CoachNote(text = it) }

        Spacer(modifier = Modifier.height(20.dp))

        when (state.mode) {
            is MealDetailMode.Logged -> {
                MealsyButton(
                    text = stringResource(R.string.meal_detail_log_this_meal),
                    onClick = onLogAgain,
                    style = MealsyButtonStyle.Primary,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(modifier = Modifier.height(10.dp))
                MealsyButton(
                    text = stringResource(R.string.meal_detail_delete),
                    onClick = onDeleteRequested,
                    style = MealsyButtonStyle.DestructiveOutline,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            is MealDetailMode.MyMeal -> {
                MealsyButton(
                    text = stringResource(R.string.meal_detail_log_this_meal),
                    onClick = onLogAgain,
                    style = MealsyButtonStyle.Primary,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(modifier = Modifier.height(10.dp))
                MealsyButton(
                    text = stringResource(R.string.meal_detail_edit_portions),
                    onClick = onEditPortions,
                    style = MealsyButtonStyle.Secondary,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }
}

@Composable
private fun headerEyebrow(state: MealDetailUiState.Loaded): String {
    return if (state.mealType != null && state.timeLabel != null) {
        val context = LocalContext.current
        stringResource(
            R.string.meal_detail_header,
            stringResource(mealTypeLabelRes(state.mealType)),
            formatLoggedAtTime(state.timeLabel, context),
        )
    } else {
        stringResource(R.string.meal_detail_my_meal_eyebrow)
    }
}

@Composable
private fun statusText(status: MealDetailStatus): Pair<String, String> = when (status) {
    is MealDetailStatus.FitsBudget -> stringResource(R.string.meal_detail_status_fits_label) to
        stringResource(R.string.meal_detail_status_fits_value, status.kcalRemaining)
    is MealDetailStatus.OverBudget -> stringResource(R.string.meal_detail_status_over_label) to
        stringResource(R.string.meal_detail_status_over_value, status.kcalOver)
    MealDetailStatus.Logged -> stringResource(R.string.meal_detail_status_logged_label) to
        stringResource(R.string.meal_detail_status_no_target)
}

@Composable
private fun coachNoteText(note: MealDetailCoachNote): String? = when (note) {
    is MealDetailCoachNote.ProteinSource -> {
        val proteinSentence = stringResource(R.string.meal_detail_coach_protein, note.itemName)
        if (note.alsoEstimated) {
            proteinSentence + " " + stringResource(R.string.meal_detail_coach_estimate)
        } else {
            proteinSentence
        }
    }
    MealDetailCoachNote.EstimateOnly -> stringResource(R.string.meal_detail_coach_estimate)
    MealDetailCoachNote.None -> null
}

private fun mealTypeLabelRes(mealType: String): Int = when (mealType) {
    "breakfast" -> R.string.home_meal_breakfast
    "lunch" -> R.string.home_meal_lunch
    "dinner" -> R.string.home_meal_dinner
    else -> R.string.home_meal_snack
}

private fun mealDetailIcon(mealType: String?) = when (mealType) {
    "breakfast" -> MealsyIcons.Breakfast
    "lunch" -> MealsyIcons.Lunch
    "dinner" -> MealsyIcons.Dinner
    "snack" -> MealsyIcons.Snack
    else -> MealsyIcons.BowlBars
}

@Composable
private fun DeleteMealDialog(onConfirm: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.meal_detail_delete_dialog_title)) },
        text = { Text(stringResource(R.string.meal_detail_delete_dialog_body)) },
        confirmButton = {
            TextButton(onClick = onConfirm) { Text(stringResource(R.string.meal_detail_delete_dialog_confirm)) }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.meal_detail_delete_dialog_cancel)) }
        },
    )
}

private val PORTION_OPTIONS = listOf(0.5, 1.0, 1.5, 2.0)
private val MEAL_TYPE_OPTIONS = listOf("breakfast", "lunch", "dinner", "snack")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LogAgainSheet(
    sheet: LogAgainSheetState,
    isMyMeal: Boolean,
    onSelectMealType: (String) -> Unit,
    onSelectPortion: (Double) -> Unit,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    val colors = MealsyTheme.colors
    val sheetState = rememberModalBottomSheetState()

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        containerColor = colors.surface,
        shape = RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp),
    ) {
        Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp)) {
            val mealTypeLabels = MEAL_TYPE_OPTIONS.associateWith { stringResource(mealTypeLabelRes(it)) }
            val portionLabels = mapOf(
                0.5 to stringResource(R.string.meal_detail_portion_half),
                1.0 to stringResource(R.string.meal_detail_portion_one),
                1.5 to stringResource(R.string.meal_detail_portion_one_half),
                2.0 to stringResource(R.string.meal_detail_portion_two),
            )

            Text(text = stringResource(R.string.meal_detail_sheet_log_as), style = MealsyType.label, color = colors.muted)
            Spacer(modifier = Modifier.height(8.dp))
            SegmentedControl(
                options = MEAL_TYPE_OPTIONS,
                selected = sheet.mealType,
                onSelect = onSelectMealType,
                label = { mealTypeLabels.getValue(it) },
            )

            Spacer(modifier = Modifier.height(18.dp))

            Text(text = stringResource(R.string.meal_detail_sheet_portion), style = MealsyType.label, color = colors.muted)
            Spacer(modifier = Modifier.height(8.dp))
            SegmentedControl(
                options = PORTION_OPTIONS,
                selected = sheet.portion,
                onSelect = onSelectPortion,
                label = { portionLabels.getValue(it) },
            )

            if (sheet.error != null) {
                Spacer(modifier = Modifier.height(10.dp))
                Text(text = sheet.error, style = MealsyType.label, color = colors.muted)
            }

            Spacer(modifier = Modifier.height(20.dp))

            MealsyButton(
                text = stringResource(R.string.meal_detail_sheet_confirm),
                onClick = onConfirm,
                enabled = !sheet.submitting,
                style = MealsyButtonStyle.Primary,
                modifier = Modifier.fillMaxWidth(),
            )

            Spacer(modifier = Modifier.height(24.dp))
        }
    }
}
