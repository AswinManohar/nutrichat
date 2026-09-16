package app.mealsy.android.ui.mymeals

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
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
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.R
import app.mealsy.android.design.components.CircleIconButton
import app.mealsy.android.design.components.InkToast
import app.mealsy.android.design.components.MealsyButton
import app.mealsy.android.design.components.MealsyButtonStyle
import app.mealsy.android.design.components.SegmentedControl
import app.mealsy.android.design.components.Stepper
import app.mealsy.android.design.components.TotalsStrip
import app.mealsy.android.design.components.TotalsStripEntry
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.ui.common.ErrorState
import app.mealsy.android.ui.common.LoadingState
import app.mealsy.data.repo.MyMealsRepository
import app.mealsy.data.repo.SavedMealItem
import app.mealsy.data.repo.SavedMealOverride
import app.mealsy.domain.CardEditor
import app.mealsy.domain.CardItem
import app.mealsy.domain.ConfirmationCard
import app.mealsy.domain.FoodNameHumanizer
import app.mealsy.domain.Totals
import app.mealsy.domain.defaultMealCategory
import dagger.hilt.android.lifecycle.HiltViewModel
import java.io.IOException
import java.time.Clock
import javax.inject.Inject
import kotlin.math.roundToInt
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject

private val PORTION_OPTIONS = listOf(0.5, 1.0, 1.5, 2.0)
private val MEAL_TYPE_OPTIONS = listOf("breakfast", "lunch", "dinner", "snack")

/**
 * One customize-sheet ingredient row: its original stored [index] (stable
 * identity for the override payload — never renumbered when a sibling row
 * is removed), the [item] carrying its base/edited grams and macros, and
 * display names.
 *
 * @param humanizedName The row's primary line.
 * @param rawNameIfDifferent The raw stored name, shown muted on a second
 *   line only when it differs from [humanizedName].
 * @param removed Whether this row has been removed from this log-only
 *   (the saved meal itself is never mutated).
 */
data class CustomizeIngredient(
    val index: Int,
    val item: CardItem,
    val humanizedName: String,
    val rawNameIfDifferent: String?,
    val removed: Boolean = false,
) {
    /** The row's current gram weight, as an [Int] for [Stepper]. */
    val qtyG: Int get() = item.targetQtyG.roundToInt()
}

/**
 * Framework-free, pure-logic state for [CustomizeSheet]: per-ingredient gram
 * edits and removals, meal type and portion, and the totals/override payload
 * derived from them.
 *
 * Every mutator ([withMealType], [withPortion], [withQty], [withRemoved])
 * returns a new immutable instance rather than mutating in place, so this
 * class is directly unit-testable with no Compose or Android dependency
 * beyond the plain [CardItem]/[ConfirmationCard]/[CardEditor] domain types.
 */
data class CustomizeSheetState(
    val mealType: String,
    val portion: Double,
    val ingredients: List<CustomizeIngredient>,
) {
    companion object {
        fun initial(ingredients: List<CustomizeIngredient>, mealType: String): CustomizeSheetState =
            CustomizeSheetState(mealType = mealType, portion = 1.0, ingredients = ingredients)
    }

    /** Rows not removed from this log-only customization. */
    val keptIngredients: List<CustomizeIngredient> get() = ingredients.filterNot { it.removed }

    /**
     * Live totals over [keptIngredients] at their current [CustomizeIngredient.qtyG]
     * and [portion], computed via [CardEditor.totals] so this sheet's macro
     * math matches the confirm card's.
     */
    val totals: Totals
        get() = CardEditor.totals(
            ConfirmationCard(
                message = "",
                items = keptIngredients.map { it.item },
                mealType = mealType,
                portion = portion,
            ),
        )

    /**
     * The [SavedMealOverride] payload for [keptIngredients], keyed by each
     * row's original stored [CustomizeIngredient.index] — removed rows are
     * simply omitted, so remaining rows' indices are never renumbered.
     */
    val overridePayload: List<SavedMealOverride>
        get() = keptIngredients.map { SavedMealOverride(index = it.index, qtyG = it.qtyG.toDouble()) }

    fun withMealType(newMealType: String): CustomizeSheetState = copy(mealType = newMealType)

    fun withPortion(newPortion: Double): CustomizeSheetState = copy(portion = newPortion)

    /** Returns a copy with the row at stored [index]'s edited grams set to [qtyG]. */
    fun withQty(index: Int, qtyG: Int): CustomizeSheetState = copy(
        ingredients = ingredients.map {
            if (it.index == index) it.copy(item = it.item.copy(targetQtyG = qtyG.toDouble())) else it
        },
    )

    /** Returns a copy with the row at stored [index] marked removed (for this log only). */
    fun withRemoved(index: Int): CustomizeSheetState = copy(
        ingredients = ingredients.map { if (it.index == index) it.copy(removed = true) else it },
    )
}

private fun SavedMealItem.toCustomizeIngredient(index: Int): CustomizeIngredient {
    val humanized = FoodNameHumanizer.humanize(foodName)
    return CustomizeIngredient(
        index = index,
        item = CardItem(
            foodName = foodName,
            qtyG = qtyG,
            targetQtyG = qtyG,
            kcal = kcal,
            proteinG = proteinG,
            carbsG = carbsG,
            fatG = fatG,
            fiberG = fiberG,
            fdcId = fdcId,
            estimated = estimated,
            extras = extras,
        ),
        humanizedName = humanized,
        rawNameIfDifferent = foodName.takeIf { it != humanized },
    )
}

/** Rendering state for [CustomizeSheet]. */
private sealed interface CustomizeUiState {
    data object Loading : CustomizeUiState
    data class Error(val message: String) : CustomizeUiState
    data class Loaded(val state: CustomizeSheetState, val submitting: Boolean) : CustomizeUiState
}

/**
 * Drives [CustomizeSheet]: loads the saved meal's current ingredients fresh
 * (independent of whatever `MealDetailViewModel` already has loaded, so this
 * sheet works standalone), holds the pure [CustomizeSheetState], and submits
 * `logCustomized` on confirm.
 *
 * Scoped to the same `my-meal/{id}` back-stack entry as `MealDetailScreen`
 * (via [hiltViewModel]'s default `NavBackStackEntry` scoping), so it reads
 * the same `id` nav arg from [SavedStateHandle].
 */
@HiltViewModel
class CustomizeSheetViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val myMealsRepository: MyMealsRepository,
    private val clock: Clock,
) : ViewModel() {

    private val mealId: String = checkNotNull(savedStateHandle.get<String>("id")) {
        "CustomizeSheetViewModel requires an \"id\" nav arg"
    }

    private val _uiState = MutableStateFlow<CustomizeUiState>(CustomizeUiState.Loading)
    val uiState: StateFlow<CustomizeUiState> = _uiState.asStateFlow()

    private val _logged = Channel<Unit>(Channel.BUFFERED)
    val logged = _logged.receiveAsFlow()

    init {
        load()
    }

    private fun load() {
        viewModelScope.launch {
            _uiState.value = CustomizeUiState.Loading
            try {
                val detail = myMealsRepository.detail(mealId)
                val ingredients = detail.ingredients.mapIndexed { index, item -> item.toCustomizeIngredient(index) }
                val initial = CustomizeSheetState.initial(ingredients, defaultMealCategory(clock))
                _uiState.value = CustomizeUiState.Loaded(initial, submitting = false)
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: IOException) {
                _uiState.value = CustomizeUiState.Error("Couldn't reach Mealsy. Check your connection.")
            } catch (exc: Exception) {
                _uiState.value = CustomizeUiState.Error("Couldn't load this meal.")
            }
        }
    }

    /** Re-runs [load] — used by the error state's retry button. */
    fun retry() = load()

    fun update(transform: (CustomizeSheetState) -> CustomizeSheetState) {
        val current = _uiState.value
        if (current is CustomizeUiState.Loaded && !current.submitting) {
            _uiState.value = current.copy(state = transform(current.state))
        }
    }

    fun submit() {
        val current = _uiState.value as? CustomizeUiState.Loaded ?: return
        if (current.submitting) return
        _uiState.value = current.copy(submitting = true)
        viewModelScope.launch {
            try {
                myMealsRepository.logCustomized(
                    id = mealId,
                    mealType = current.state.mealType,
                    overrides = current.state.overridePayload,
                    portion = current.state.portion,
                )
                _logged.send(Unit)
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                _uiState.value = current.copy(submitting = false)
            }
        }
    }
}

/**
 * The "Edit portions" customizer: meal-type selector, a per-ingredient list
 * with gram steppers and remove buttons (this log only — the saved meal
 * itself is untouched), a live totals strip, a portion multiplier, and a
 * primary "Log meal" action.
 *
 * @param onDismissRequest Invoked when the sheet is dismissed without
 *   logging (tap outside, back gesture).
 * @param onLogged Invoked once the customized log succeeds — the caller
 *   shows the [InkToast] "Logged" and pops back.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CustomizeSheet(
    onDismissRequest: () -> Unit,
    onLogged: () -> Unit,
    viewModel: CustomizeSheetViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()

    LaunchedEffect(viewModel) {
        viewModel.logged.collect { onLogged() }
    }

    val sheetState = rememberModalBottomSheetState()
    ModalBottomSheet(
        onDismissRequest = onDismissRequest,
        sheetState = sheetState,
        containerColor = MealsyTheme.colors.surface,
        shape = RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp),
    ) {
        when (val state = uiState) {
            CustomizeUiState.Loading ->
                LoadingState(stringResource(R.string.customize_sheet_loading), modifier = Modifier.height(240.dp))
            is CustomizeUiState.Error ->
                ErrorState(state.message, onRetry = viewModel::retry, modifier = Modifier.height(240.dp))
            is CustomizeUiState.Loaded -> CustomizeSheetContent(
                state = state.state,
                submitting = state.submitting,
                onMealTypeSelect = { viewModel.update { s -> s.withMealType(it) } },
                onPortionSelect = { viewModel.update { s -> s.withPortion(it) } },
                onQtyChange = { index, qty -> viewModel.update { s -> s.withQty(index, qty) } },
                onRemove = { index -> viewModel.update { s -> s.withRemoved(index) } },
                onConfirm = viewModel::submit,
            )
        }
    }
}

@Composable
internal fun CustomizeSheetContent(
    state: CustomizeSheetState,
    submitting: Boolean,
    onMealTypeSelect: (String) -> Unit,
    onPortionSelect: (Double) -> Unit,
    onQtyChange: (Int, Int) -> Unit,
    onRemove: (Int) -> Unit,
    onConfirm: () -> Unit,
) {
    val colors = MealsyTheme.colors
    val mealTypeLabels = mapOf(
        "breakfast" to stringResource(app.mealsy.android.R.string.home_meal_breakfast),
        "lunch" to stringResource(app.mealsy.android.R.string.home_meal_lunch),
        "dinner" to stringResource(app.mealsy.android.R.string.home_meal_dinner),
        "snack" to stringResource(app.mealsy.android.R.string.home_meal_snack),
    )
    val portionLabels = mapOf(
        0.5 to stringResource(R.string.customize_sheet_portion_half),
        1.0 to stringResource(R.string.customize_sheet_portion_one),
        1.5 to stringResource(R.string.customize_sheet_portion_one_half),
        2.0 to stringResource(R.string.customize_sheet_portion_two),
    )
    val totals = state.totals

    Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp)) {
        Text(text = stringResource(R.string.customize_sheet_log_as), style = MealsyType.label, color = colors.muted)
        Spacer(modifier = Modifier.height(8.dp))
        SegmentedControl(
            options = MEAL_TYPE_OPTIONS,
            selected = state.mealType,
            onSelect = onMealTypeSelect,
            label = { mealTypeLabels.getValue(it) },
        )

        Spacer(modifier = Modifier.height(18.dp))

        state.ingredients.filterNot { it.removed }.forEach { ingredient ->
            IngredientRow(
                ingredient = ingredient,
                onQtyChange = { qty -> onQtyChange(ingredient.index, qty) },
                onRemove = { onRemove(ingredient.index) },
            )
            Spacer(modifier = Modifier.height(10.dp))
        }

        Spacer(modifier = Modifier.height(4.dp))

        TotalsStrip(
            entries = listOf(
                TotalsStripEntry("kcal", totals.kcal.roundToInt().toString(), totals.kcal == 0.0),
                TotalsStripEntry("Protein", "${totals.proteinG.roundToInt()}g", totals.proteinG == 0.0),
                TotalsStripEntry("Carbs", "${totals.carbsG.roundToInt()}g", totals.carbsG == 0.0),
                TotalsStripEntry("Fat", "${totals.fatG.roundToInt()}g", totals.fatG == 0.0),
                TotalsStripEntry("Fiber", "${totals.fiberG.roundToInt()}g", totals.fiberG == 0.0),
            ),
            modifier = Modifier.fillMaxWidth(),
        )

        Spacer(modifier = Modifier.height(18.dp))

        Text(text = stringResource(R.string.customize_sheet_portion), style = MealsyType.label, color = colors.muted)
        Spacer(modifier = Modifier.height(8.dp))
        SegmentedControl(
            options = PORTION_OPTIONS,
            selected = state.portion,
            onSelect = onPortionSelect,
            label = { portionLabels.getValue(it) },
        )

        Spacer(modifier = Modifier.height(20.dp))

        MealsyButton(
            text = stringResource(R.string.customize_sheet_confirm),
            onClick = onConfirm,
            enabled = !submitting && state.keptIngredients.isNotEmpty(),
            style = MealsyButtonStyle.Primary,
            modifier = Modifier.fillMaxWidth(),
        )

        Spacer(modifier = Modifier.height(24.dp))
    }
}

@Composable
private fun IngredientRow(ingredient: CustomizeIngredient, onQtyChange: (Int) -> Unit, onRemove: () -> Unit) {
    val colors = MealsyTheme.colors
    val removeDescription = stringResource(R.string.customize_sheet_remove_ingredient, ingredient.humanizedName)
    val stepperDescription = stringResource(R.string.customize_sheet_stepper_description, ingredient.qtyG)

    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(text = ingredient.humanizedName, style = MealsyType.body, color = colors.ink)
            if (ingredient.rawNameIfDifferent != null) {
                Text(text = ingredient.rawNameIfDifferent, style = MealsyType.label, color = colors.muted)
            }
        }
        Stepper(
            value = ingredient.qtyG,
            onValueChange = onQtyChange,
            modifier = Modifier.semantics { contentDescription = stepperDescription },
        )
        CircleIconButton(
            icon = MealsyIcons.Close,
            contentDescription = removeDescription,
            onClick = onRemove,
            size = 28.dp,
        )
    }
}
