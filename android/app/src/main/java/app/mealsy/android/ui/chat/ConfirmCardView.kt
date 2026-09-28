package app.mealsy.android.ui.chat

import android.content.res.Configuration
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.selectableGroup
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.mealsy.android.R
import app.mealsy.android.design.components.CandidatePickerSheetContent
import app.mealsy.android.design.components.CompositeDishHeader
import app.mealsy.android.design.components.Eyebrow
import app.mealsy.android.design.components.InkToast
import app.mealsy.android.design.components.InsetDivider
import app.mealsy.android.design.components.MealsyButton
import app.mealsy.android.design.components.MealsyButtonStyle
import app.mealsy.android.design.components.PastelIconCircle
import app.mealsy.android.design.components.PickerResultsState
import app.mealsy.android.design.components.PickerRow
import app.mealsy.android.design.components.PillInput
import app.mealsy.android.design.components.SegmentedControl
import app.mealsy.android.design.components.Stepper
import app.mealsy.android.design.components.TagChip
import app.mealsy.android.design.components.TagTone
import app.mealsy.android.design.components.TotalsStrip
import app.mealsy.android.design.components.TotalsStripEntry
import app.mealsy.android.design.components.TypingIndicator
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.design.theme.rememberMealsyHaptics
import app.mealsy.domain.CardEditor
import app.mealsy.domain.CardItem
import app.mealsy.domain.ConfirmationCard
import app.mealsy.domain.FoodNameHumanizer
import app.mealsy.domain.PastelTone
import app.mealsy.domain.pastelToneFor
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlin.math.roundToInt

/**
 * The four meal-type segments offered by [ConfirmCardView], as canonical
 * lowercase values matching the backend's `meal_type` vocabulary. Display
 * labels come from the shared `home_meal_*` strings (see [mealTypeLabel]) so
 * this segment reads "Snacks", matching the Home row, meal detail, and
 * Log-again sheet — it used to say "Snack" here only (#46).
 */
private val MEAL_TYPE_OPTIONS = listOf("breakfast", "lunch", "dinner", "snack")

/** The shared display labels for [MEAL_TYPE_OPTIONS]'s canonical values. */
@Composable
private fun mealTypeLabels(): Map<String, String> =
    mapOf(
        "breakfast" to stringResource(R.string.home_meal_breakfast),
        "lunch" to stringResource(R.string.home_meal_lunch),
        "dinner" to stringResource(R.string.home_meal_dinner),
        "snack" to stringResource(R.string.home_meal_snack),
    )

/** The four portion multipliers offered by [ConfirmCardView], display-labelled. */
private val PORTION_OPTIONS = listOf("0.5×" to 0.5, "1×" to 1.0, "1.5×" to 1.5, "2×" to 2.0)

/** How long the remove-with-undo toast stays visible before it auto-dismisses. */
private const val UNDO_TOAST_MS = 4_000L

/** Local grouping of item indices sharing a [CardItem.sourceDish]. */
private data class ItemGroup(val dish: String?, val indices: List<Int>)

/**
 * Groups [items] by [CardItem.sourceDish], preserving first-seen order.
 *
 * Ported from `frontend/src/components/chat/ConfirmationCard.tsx`'s
 * `groupByDish`: a null dish is always its own singleton group (a standalone
 * atomic item never merges with anything), while items sharing the same
 * non-null dish name collapse into one group at the position the dish was
 * first seen.
 */
private fun groupByDish(items: List<CardItem>): List<ItemGroup> {
    val groups = mutableListOf<ItemGroup>()
    val positionOf = mutableMapOf<String, Int>()
    items.forEachIndexed { index, item ->
        val dish = item.sourceDish
        if (dish == null) {
            groups.add(ItemGroup(dish = null, indices = listOf(index)))
            return@forEachIndexed
        }
        val at = positionOf[dish]
        if (at == null) {
            positionOf[dish] = groups.size
            groups.add(ItemGroup(dish = dish, indices = listOf(index)))
        } else {
            groups[at] = groups[at].copy(indices = groups[at].indices + index)
        }
    }
    return groups
}

/** Maps a domain [PastelTone] onto the `:core:ui` [TagTone] palette. */
private fun PastelTone.toTagTone(): TagTone =
    when (this) {
        PastelTone.Leaf -> TagTone.Leaf
        PastelTone.Butter -> TagTone.Butter
        PastelTone.Powder -> TagTone.Powder
        PastelTone.Pink -> TagTone.Pink
    }

/**
 * The editable meal confirmation card: item rows (grouped by composite dish),
 * meal type, portion, totals, and confirm/cancel/save actions.
 *
 * Ports the behaviour of `frontend/src/components/chat/ConfirmationCard.tsx`
 * onto the design system's card shell (see `design-handoff/Meal Confirm
 * Card.html`).
 *
 * @param card The card's current (possibly locally edited) state.
 * @param callbacks Host actions this card can trigger; see
 *   [ConfirmCardCallbacks].
 * @param modifier The modifier applied to the card's outer surface.
 * @param busy Whether a confirm/cancel/decompose/combine turn is in flight —
 *   disables the meal-type, portion, and action controls.
 * @param swapping Whether a candidate-correction turn is in flight — shows a
 *   loading state on the affected row (or all rows, conservatively, since
 *   the host does not report which index is swapping).
 * @param savingMeal Whether "Add to My Meals" is in flight.
 * @param timestamp An optional pre-formatted time (e.g. "07:39 PM") rendered
 *   right-aligned below the card.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConfirmCardView(
    card: ConfirmationCard,
    callbacks: ConfirmCardCallbacks,
    modifier: Modifier = Modifier,
    busy: Boolean = false,
    swapping: Boolean = false,
    savingMeal: Boolean = false,
    timestamp: String? = null,
) {
    val colors = MealsyTheme.colors

    // Track a pending single-row undo: the item + its original index, and a
    // monotonic token so a second removal while the toast is showing resets
    // the auto-dismiss timer rather than being silently swallowed.
    var pendingUndo by remember { mutableStateOf<Pair<String, Int>?>(null) }

    // "Swapped to X" toast (spec 003) — separate from [pendingUndo], which is
    // for row removal.
    var swapToastName by remember { mutableStateOf<String?>(null) }

    // Which item's candidate sheet is open, if any.
    var candidateSheetIndex by rememberSaveable { mutableStateOf<Int?>(null) }

    Column(modifier = modifier) {
        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(18.dp),
            color = colors.surface,
        ) {
            Column(
                modifier = Modifier.padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                HeaderRow(itemCount = card.items.size)

                MealTypeSection(
                    mealType = card.mealType,
                    enabled = !busy,
                    onMealTypeChange = callbacks::onMealTypeChange,
                )

                ItemRows(
                    card = card,
                    swapping = swapping,
                    busy = busy,
                    callbacks = callbacks,
                    onOpenCandidateSheet = { candidateSheetIndex = it },
                    onRemoved = { name, index -> pendingUndo = name to index },
                )

                TotalsStrip(entries = totalsEntries(card))

                PortionSection(
                    portion = card.portion,
                    enabled = !busy,
                    onPortionChange = callbacks::onPortionChange,
                )

                ActionsRow(
                    busy = busy,
                    swapping = swapping,
                    onCancel = callbacks::onCancel,
                    onConfirm = callbacks::onConfirm,
                )

                SaveAsMyMealSection(
                    savingMeal = savingMeal,
                    onSave = callbacks::onSaveAsMyMeal,
                )
            }
        }

        if (timestamp != null) {
            Text(
                text = timestamp,
                style = MealsyType.label.copy(fontSize = 11.sp),
                color = colors.inactive,
                textAlign = TextAlign.End,
                modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
            )
        }

        // Remove-with-undo toast. InkToast has no action slot, so this
        // renders its own ink pill matching InkToast's styling rather than
        // modifying :core:ui — see the class doc for why.
        pendingUndo?.let { (name, index) ->
            LaunchedEffect(pendingUndo) {
                delay(UNDO_TOAST_MS)
                pendingUndo = null
            }
            UndoToast(
                text = stringResource(R.string.confirm_card_removed, name),
                onUndo = {
                    pendingUndo = null
                    callbacks.onUndoRemove()
                },
                modifier = Modifier.padding(top = 10.dp),
            )
        }

        swapToastName?.let { name ->
            val haptics = rememberMealsyHaptics()
            LaunchedEffect(name) {
                haptics.confirm()
                delay(UNDO_TOAST_MS)
                swapToastName = null
            }
            UndoToast(
                text = stringResource(R.string.confirm_card_swapped_to, name),
                onUndo = {
                    swapToastName = null
                    callbacks.onUndoSwap()
                },
                modifier = Modifier.padding(top = 10.dp),
            )
        }
    }

    val sheetIndex = candidateSheetIndex
    if (sheetIndex != null && sheetIndex in card.items.indices) {
        val item = card.items[sheetIndex]
        // Fully expanded per contract (#48) — the search field + results
        // need the full sheet height, not a partial peek.
        val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
        val context = LocalContext.current
        val pickerScope =
            remember(sheetIndex, item.fdcId) { CoroutineScope(SupervisorJob() + kotlinx.coroutines.Dispatchers.Main.immediate) }
        DisposableEffect(pickerScope) { onDispose { pickerScope.cancel() } }
        val pickerViewModel =
            remember(sheetIndex, item.fdcId) {
                foodPickerViewModelFactory(context).create(
                    scope = pickerScope,
                    currentFdcId = item.fdcId,
                    initialQuery = item.inputPhrase ?: item.foodName,
                    // Preview rows show what the user currently sees on the
                    // card (target × portion); the actual swap fetch must use
                    // the item's BASE qty_g, never the edited target — or
                    // log-items double-scales (contracts/android-picker-ui.md, U2).
                    previewQtyG = item.targetQtyG * card.portion,
                    baseQtyG = item.qtyG,
                )
            }
        var swapError by remember(sheetIndex, item.fdcId) { mutableStateOf(false) }

        LaunchedEffect(pickerViewModel) {
            pickerViewModel.eventsFlow.collect { event ->
                when (event) {
                    is FoodPickerEvent.SwapReady -> {
                        swapError = false
                        candidateSheetIndex = null
                        callbacks.onSwapItem(sheetIndex, event.item, event.method, event.query)
                        swapToastName = event.item.foodName
                    }
                    FoodPickerEvent.SwapFailed -> swapError = true
                }
            }
        }

        val query by pickerViewModel.query.collectAsState()
        val online by pickerViewModel.isOnline.collectAsState()
        val searchState by pickerViewModel.searchState.collectAsState()

        ModalBottomSheet(
            onDismissRequest = { candidateSheetIndex = null },
            sheetState = sheetState,
            containerColor = colors.surface,
        ) {
            Column(modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp)) {
                // CandidatePickerSheetContent owns its own eyebrow + "Currently:
                // ..." header (:core:ui's golden covers it) — don't duplicate it
                // here.
                CandidatePickerSheetContent(
                    currentName = item.foodName,
                    query = query,
                    onQueryChange = pickerViewModel::onQueryChange,
                    online = online,
                    resultsState = searchState.toPickerResultsState(),
                    onSelectResult = { fdcId, _ ->
                        if (fdcId == item.fdcId) {
                            candidateSheetIndex = null
                        } else {
                            pickerViewModel.select(fdcId, method = "search", query = query)
                        }
                    },
                    onRemove = {
                        pendingUndo = item.foodName to sheetIndex
                        callbacks.onRemoveItem(sheetIndex)
                        candidateSheetIndex = null
                    },
                    onDescribeDifferently = { description ->
                        callbacks.onDescribeItemDifferently(sheetIndex, description)
                        candidateSheetIndex = null
                    },
                )
                if (swapError) {
                    Text(
                        text = stringResource(R.string.confirm_card_swap_failed),
                        style = MealsyType.label,
                        color = colors.muted,
                        modifier = Modifier.padding(start = 16.dp, top = 4.dp, end = 16.dp),
                    )
                }
            }
        }
    }
}

/** Maps [FoodPickerViewModel]'s [SearchState] onto `:core:ui`'s decoupled [PickerResultsState]. */
private fun SearchState.toPickerResultsState(): PickerResultsState =
    when (this) {
        SearchState.Idle -> PickerResultsState.Idle
        SearchState.Loading -> PickerResultsState.Loading
        is SearchState.Loaded ->
            PickerResultsState.Loaded(
                hits.map { hit ->
                    PickerRow(fdcId = hit.fdcId, name = hit.name, kcal = hit.kcal, proteinG = hit.proteinG)
                },
            )
        SearchState.Empty -> PickerResultsState.Empty
        SearchState.Unavailable -> PickerResultsState.Unavailable
    }

@Composable
private fun HeaderRow(itemCount: Int) {
    val colors = MealsyTheme.colors
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Eyebrow(text = stringResource(R.string.confirm_card_eyebrow))
        Text(
            text = pluralStringResourceCompat(itemCount),
            style = MealsyType.label.copy(fontSize = 12.sp),
            color = colors.muted,
        )
    }
}

/**
 * `pluralStringResource` needs the plurals resource wired up by another
 * agent; this wraps it so the rest of the file doesn't import
 * `androidx.compose.ui.res.pluralStringResource` directly in more than one
 * place.
 */
@Composable
private fun pluralStringResourceCompat(itemCount: Int): String =
    androidx.compose.ui.res.pluralStringResource(
        R.plurals.confirm_card_items,
        itemCount,
        itemCount,
    )

@Composable
private fun MealTypeSection(
    mealType: String,
    enabled: Boolean,
    onMealTypeChange: (String) -> Unit,
) {
    val colors = MealsyTheme.colors
    // The ViewModel owns defaulting an "unspecified"/blank meal type (via
    // domain.defaultMealCategory) so the value it confirms matches what this
    // card shows; "Lunch" here is only a last-resort render fallback, never
    // a decision this composable makes on its own.
    val selected =
        MEAL_TYPE_OPTIONS.firstOrNull {
            it.equals(mealType, ignoreCase = true)
        } ?: "lunch"
    val labels = mealTypeLabels()

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            text = stringResource(R.string.confirm_card_log_this_as),
            style = MealsyType.label.copy(fontSize = 12.sp),
            color = colors.muted,
        )
        SegmentedControl(
            options = MEAL_TYPE_OPTIONS,
            selected = selected,
            onSelect = { if (enabled) onMealTypeChange(it) },
            modifier = Modifier.semantics { selectableGroup() }.alpha(if (enabled) 1f else 0.5f),
            label = { labels.getValue(it) },
        )
    }
}

@Composable
private fun PortionSection(
    portion: Double,
    enabled: Boolean,
    onPortionChange: (Double) -> Unit,
) {
    val colors = MealsyTheme.colors
    val selectedLabel =
        PORTION_OPTIONS.firstOrNull { it.second == portion }?.first
            ?: PORTION_OPTIONS[1].first

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            text = stringResource(R.string.confirm_card_portion),
            style = MealsyType.label.copy(fontSize = 12.sp),
            color = colors.muted,
        )
        SegmentedControl(
            options = PORTION_OPTIONS.map { it.first },
            selected = selectedLabel,
            onSelect = { label ->
                if (!enabled) return@SegmentedControl
                val value = PORTION_OPTIONS.first { it.first == label }.second
                onPortionChange(value)
            },
            modifier = Modifier.alpha(if (enabled) 1f else 0.5f),
            label = { it },
        )
    }
}

@Composable
private fun ActionsRow(
    busy: Boolean,
    swapping: Boolean,
    onCancel: () -> Unit,
    onConfirm: () -> Unit,
) {
    val enabled = !busy && !swapping
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        MealsyButton(
            text = stringResource(R.string.confirm_card_cancel),
            onClick = onCancel,
            style = MealsyButtonStyle.Secondary,
            enabled = enabled,
            modifier = Modifier.width(104.dp),
        )
        MealsyButton(
            text = stringResource(R.string.confirm_card_confirm),
            onClick = onConfirm,
            style = MealsyButtonStyle.Primary,
            enabled = enabled,
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun SaveAsMyMealSection(
    savingMeal: Boolean,
    onSave: (String) -> Unit,
) {
    val colors = MealsyTheme.colors
    var name by rememberSaveable { mutableStateOf("") }

    Column {
        Box(
            modifier =
                Modifier
                    .fillMaxWidth()
                    .height(1.dp)
                    .background(colors.hairline)
                    .padding(bottom = 16.dp),
        )
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            PillInput(
                value = name,
                onValueChange = { name = it },
                placeholder = stringResource(R.string.confirm_card_my_meal_name_hint),
                enabled = !savingMeal,
                modifier = Modifier.weight(1f),
            )
            MealsyButton(
                text = stringResource(R.string.confirm_card_add_to_my_meals),
                onClick = {
                    onSave(name.trim())
                    name = ""
                },
                style = MealsyButtonStyle.Secondary,
                enabled = name.isNotBlank() && !savingMeal,
                // MealsyButton's content Row is `fillMaxWidth()`, so in an
                // unconstrained Row it would otherwise greedily claim the
                // entire row (starving the PillInput's weight(1f) neighbor
                // down to zero width). `unbounded = true` is required here:
                // the default `wrapContentWidth()` still measures content
                // against the incoming max-width constraint, which is
                // exactly what lets `fillMaxWidth()` inside claim it all.
                modifier = Modifier.wrapContentWidth(unbounded = true),
            )
        }
    }
}

/** Builds the ordered [TotalsStripEntry] list from [CardEditor.totals]. */
@Composable
private fun totalsEntries(card: ConfirmationCard): List<TotalsStripEntry> {
    val totals = CardEditor.totals(card)

    fun macro(value: Double) = "${value.roundToInt()}g"
    return listOf(
        TotalsStripEntry(
            label = stringResource(R.string.confirm_card_totals_kcal),
            value = totals.kcal.roundToInt().toString(),
            isZero = totals.kcal.roundToInt() == 0,
        ),
        TotalsStripEntry(
            label = stringResource(R.string.confirm_card_totals_protein),
            value = macro(totals.proteinG),
            isZero = totals.proteinG.roundToInt() == 0,
        ),
        TotalsStripEntry(
            label = stringResource(R.string.confirm_card_totals_carbs),
            value = macro(totals.carbsG),
            isZero = totals.carbsG.roundToInt() == 0,
        ),
        TotalsStripEntry(
            label = stringResource(R.string.confirm_card_totals_fat),
            value = macro(totals.fatG),
            isZero = totals.fatG.roundToInt() == 0,
        ),
        TotalsStripEntry(
            label = stringResource(R.string.confirm_card_totals_fiber),
            value = macro(totals.fiberG),
            isZero = totals.fiberG.roundToInt() == 0,
        ),
    )
}

@Composable
private fun ItemRows(
    card: ConfirmationCard,
    swapping: Boolean,
    busy: Boolean,
    callbacks: ConfirmCardCallbacks,
    onOpenCandidateSheet: (Int) -> Unit,
    onRemoved: (name: String, index: Int) -> Unit,
) {
    val groups = groupByDish(card.items)
    val visibleGroups = groups.filter { it.dish == null || it.indices.isNotEmpty() }

    // Mirrors the web's showBreak/showCombine gating exactly (see
    // ConfirmationCard.tsx): fewer than two dish groups AND (there's exactly
    // one dish, or some visible item is itself flagged composite) shows
    // "Break into ingredients"; any item at all carrying a sourceDish shows
    // "Log as single item".
    val dishGroups = groups.filter { it.dish != null }
    val soleDish = if (dishGroups.size == 1) dishGroups.first().dish else null
    val anyComposite = card.items.any { it.isComposite }
    val showBreak = dishGroups.size < 2 && (soleDish != null || anyComposite)
    val showCombine = card.items.any { it.sourceDish != null }

    Column {
        visibleGroups.forEachIndexed { groupIdx, group ->
            if (group.dish != null) {
                CompositeDishHeader(
                    dishName = FoodNameHumanizer.humanize(group.dish),
                    onBreakIntoIngredients = if (showBreak) callbacks::onDecompose else null,
                    onLogAsSingleItem = if (showCombine) callbacks::onCombine else null,
                    modifier = Modifier.padding(top = if (groupIdx == 0) 0.dp else 8.dp),
                )
            }
            group.indices.forEachIndexed { rowIdx, index ->
                ItemRow(
                    item = card.items[index],
                    card = card,
                    index = index,
                    swapping = swapping,
                    busy = busy,
                    callbacks = callbacks,
                    onOpenCandidateSheet = { onOpenCandidateSheet(index) },
                    onRemoved = onRemoved,
                )
                if (!(groupIdx == visibleGroups.lastIndex && rowIdx == group.indices.lastIndex)) {
                    InsetDivider()
                }
            }
        }
    }
}

@Composable
private fun ItemRow(
    item: CardItem,
    card: ConfirmationCard,
    index: Int,
    swapping: Boolean,
    busy: Boolean,
    callbacks: ConfirmCardCallbacks,
    onOpenCandidateSheet: () -> Unit,
    onRemoved: (name: String, index: Int) -> Unit,
) {
    val colors = MealsyTheme.colors
    val removeLabel = stringResource(R.string.confirm_card_remove_action, item.foodName)
    val swapLabel = stringResource(R.string.confirm_card_swap_action, item.foodName)
    val disabled = busy || swapping || item.pendingCandidate != null

    Column(
        modifier =
            Modifier
                .fillMaxWidth()
                .padding(vertical = 14.dp)
                .semantics {
                    customActions =
                        buildList {
                            add(
                                CustomAccessibilityAction(removeLabel) {
                                    onRemoved(item.foodName, index)
                                    true
                                },
                            )
                            add(
                                CustomAccessibilityAction(swapLabel) {
                                    onOpenCandidateSheet()
                                    true
                                },
                            )
                        }
                },
    ) {
        if (item.pendingCandidate != null || swapping) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
                TypingIndicator()
            }
            return@Column
        }

        Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            PastelIconCircle(
                icon = MealsyIcons.Bowl,
                tone = pastelToneFor(item).toTagTone(),
                size = 32.dp,
                contentDescription = null,
            )
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = FoodNameHumanizer.humanize(item.foodName),
                    style = MealsyType.body.copy(fontSize = 14.sp, fontWeight = FontWeight.Medium),
                    color = colors.ink,
                )
                Text(
                    text = item.foodName,
                    style = MealsyType.label.copy(fontSize = 12.sp),
                    color = colors.muted,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                ItemMetaLine(item = item, card = card, onOpenCandidateSheet = onOpenCandidateSheet)
            }
            RemoveButton(
                onClick = {
                    onRemoved(item.foodName, index)
                    callbacks.onRemoveItem(index)
                },
                enabled = !disabled,
            )
        }

        Row(
            modifier = Modifier.fillMaxWidth().padding(start = 42.dp, top = 6.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = stringResource(R.string.confirm_card_not_right_food),
                style =
                    MealsyType.label.copy(
                        fontSize = 12.sp,
                        textDecoration = TextDecoration.Underline,
                    ),
                color = colors.muted,
                modifier = Modifier.clickable(enabled = !disabled) { onOpenCandidateSheet() },
            )
            // Displayed grams must reflect the card's overall portion
            // multiplier, not just the item's own qty edit — otherwise a 2×
            // portion doubles kcal while the row still shows the unscaled
            // grams (#46). The Stepper edits/displays the scaled ("what
            // will actually be logged") weight; converting a user edit back
            // to targetQtyG divides out the portion again.
            val scaledQtyG = CardEditor.scaledQtyG(item, card.portion)
            Stepper(
                value = scaledQtyG.roundToInt(),
                onValueChange = { newScaled ->
                    val newTargetQtyG = if (card.portion != 0.0) newScaled / card.portion else newScaled.toDouble()
                    callbacks.onQtyChange(index, newTargetQtyG)
                },
                step = 5,
                min = 5,
                label =
                    stringResource(
                        R.string.confirm_card_stepper_label,
                        FoodNameHumanizer.humanize(item.foodName),
                    ),
            )
        }
    }
}

/**
 * The `<kcal> · <protein>g protein` meta line, plus the `estimated` pastel
 * tag and a muted (non-pastel, hairline-bordered) `check match` tag.
 *
 * `check match` deliberately does NOT reuse [TagChip]'s pastel tones — the
 * design calls for a muted, low-emphasis tag here, and introducing a fifth
 * pastel would violate the "pastels are for exactly these four tones" rule
 * in `android/CLAUDE.md`. It's rendered as a plain hairline pill instead.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ItemMetaLine(
    item: CardItem,
    card: ConfirmationCard,
    onOpenCandidateSheet: () -> Unit,
) {
    val colors = MealsyTheme.colors
    val factor = if (item.qtyG != 0.0) (item.targetQtyG / item.qtyG) * card.portion else 0.0
    val kcal = item.kcal * factor
    val protein = item.proteinG * factor

    FlowRow(
        verticalArrangement = Arrangement.spacedBy(4.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        modifier = Modifier.padding(top = 2.dp),
    ) {
        Text(
            text = "${kcal.roundToInt()} kcal · ${protein.roundToInt()}g protein",
            style = MealsyType.label.copy(fontSize = 12.sp),
            color = colors.muted,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        if (item.estimated) {
            TagChip(text = stringResource(R.string.confirm_card_estimated), tone = TagTone.Powder)
        }
        if ((item.confidence ?: 1.0) < 0.6) {
            CheckMatchTag(onClick = onOpenCandidateSheet)
        }
    }
}

/**
 * A clickable "check match" tag: a second entry point into the picker
 * sheet for low-confidence/estimated items, alongside "Not the right
 * food?" (spec 003, E1).
 */
@Composable
private fun CheckMatchTag(onClick: () -> Unit) {
    val colors = MealsyTheme.colors
    Surface(
        shape = MealsyShapes.pill,
        color = Color.Transparent,
        border = androidx.compose.foundation.BorderStroke(1.dp, colors.hairline),
        modifier = Modifier.clickable(onClick = onClick),
    ) {
        Text(
            text = stringResource(R.string.confirm_card_check_match),
            style = MealsyType.tinyTag.copy(fontSize = 11.sp),
            color = colors.muted,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(vertical = 2.dp, horizontal = 8.dp),
        )
    }
}

@Composable
private fun RemoveButton(
    onClick: () -> Unit,
    enabled: Boolean,
) {
    val colors = MealsyTheme.colors
    var pressed by remember { mutableStateOf(false) }
    val tint = if (pressed) colors.terracotta else colors.muted
    Box(
        modifier =
            Modifier
                .size(24.dp)
                .alpha(if (enabled) 1f else 0.35f)
                .clickable(enabled = enabled) { onClick() },
        contentAlignment = Alignment.Center,
    ) {
        Text(text = "×", style = MealsyType.body.copy(fontSize = 16.sp), color = tint)
    }
}

/**
 * A self-drawn variant of [InkToast] with an "Undo" affordance. [InkToast]
 * has no action slot, so rather than modifying `:core:ui` this reproduces
 * its ink-pill styling locally — see [ConfirmCardView]'s class doc.
 */
@Composable
private fun UndoToast(
    text: String,
    onUndo: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    Surface(shape = MealsyShapes.pill, color = colors.ink, modifier = modifier) {
        Row(
            modifier = Modifier.padding(vertical = 12.dp, horizontal = 18.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(text = text, style = MealsyType.badge, color = colors.canvas)
            Text(
                text = stringResource(R.string.confirm_card_undo),
                style = MealsyType.badge.copy(textDecoration = TextDecoration.Underline),
                color = colors.olive,
                modifier = Modifier.clickable { onUndo() },
            )
        }
    }
}

@Preview(name = "ConfirmCardView light", widthDp = 390)
@Composable
private fun ConfirmCardViewLightPreview() {
    MealsyTheme {
        Surface(color = MealsyTheme.colors.canvas) {
            ConfirmCardView(
                card = previewCard(),
                callbacks = previewCallbacks(),
                modifier = Modifier.padding(16.dp),
                timestamp = "07:39 PM",
            )
        }
    }
}

@Preview(
    name = "ConfirmCardView dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun ConfirmCardViewDarkPreview() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            ConfirmCardView(
                card = previewCard(),
                callbacks = previewCallbacks(),
                modifier = Modifier.padding(16.dp),
            )
        }
    }
}

private fun previewCard(): ConfirmationCard =
    ConfirmationCard(
        message = "",
        mealType = "lunch",
        portion = 1.0,
        items =
            listOf(
                CardItem(
                    foodName = "Chicken, broilers or fryers, breast, meat only, cooked, roasted",
                    qtyG = 150.0,
                    targetQtyG = 150.0,
                    kcal = 231.0,
                    proteinG = 43.0,
                    carbsG = 0.0,
                    fatG = 5.0,
                    fiberG = 0.0,
                    fdcId = 1L,
                    estimated = false,
                    candidates = listOf("Chicken breast", "Chicken thigh"),
                    confidence = 0.9,
                ),
                CardItem(
                    foodName = "Rice, white, long-grain, regular, cooked",
                    qtyG = 200.0,
                    targetQtyG = 200.0,
                    kcal = 260.0,
                    proteinG = 5.0,
                    carbsG = 56.0,
                    fatG = 0.4,
                    fiberG = 1.0,
                    fdcId = 2L,
                    estimated = true,
                    confidence = 0.4,
                ),
            ),
    )

private fun previewCallbacks(): ConfirmCardCallbacks =
    object : ConfirmCardCallbacks {
        override fun onMealTypeChange(mealType: String) = Unit

        override fun onPortionChange(portion: Double) = Unit

        override fun onQtyChange(
            index: Int,
            newQtyG: Double,
        ) = Unit

        override fun onRemoveItem(index: Int) = Unit

        override fun onUndoRemove() = Unit

        override fun onSwapCandidate(
            index: Int,
            newName: String,
        ) = Unit

        override fun onSwapItem(
            index: Int,
            newItem: app.mealsy.domain.CardItem,
            method: String,
            query: String?,
        ) = Unit

        override fun onUndoSwap() = Unit

        override fun onDescribeItemDifferently(
            index: Int,
            description: String,
        ) = Unit

        override fun onDecompose() = Unit

        override fun onCombine() = Unit

        override fun onConfirm() = Unit

        override fun onCancel() = Unit

        override fun onSaveAsMyMeal(name: String) = Unit
    }
