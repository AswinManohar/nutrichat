package app.mealsy.android.ui.mealdetail

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.android.design.components.TagTone
import app.mealsy.android.ui.common.ErrorKind
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.repo.ChatRepository
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.data.repo.LogOutcome
import app.mealsy.data.repo.LoggedMealItem
import app.mealsy.data.repo.MealsRepository
import app.mealsy.data.repo.MyMealsRepository
import app.mealsy.data.repo.SavedMealItem
import app.mealsy.data.repo.SavedMealOverride
import app.mealsy.domain.CardItem
import app.mealsy.domain.ConfirmationCard
import app.mealsy.domain.Goals
import app.mealsy.domain.defaultMealCategory
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import java.io.IOException
import java.time.Clock
import javax.inject.Inject
import kotlin.math.roundToInt

/** Which detail this screen is showing — a logged meal or a saved "My Meal". */
sealed interface MealDetailMode {
    data class Logged(val mealId: String) : MealDetailMode

    data class MyMeal(val id: String) : MealDetailMode
}

/** One ingredient row, normalized from either [LoggedMealItem] or [SavedMealItem]. */
internal data class UiIngredient(
    val foodName: String,
    val qtyG: Double,
    val kcal: Double,
    val proteinG: Double,
    val carbsG: Double,
    val fatG: Double,
    val fiberG: Double,
    val fdcId: Long,
    val estimated: Boolean,
    val extras: JsonObject,
)

private fun UiIngredient.source(): String? = extras["source"]?.jsonPrimitive?.contentOrNull

/** Which optional third tag to show, after the always-present kcal/protein tags. */
enum class MealDetailThirdTag { UsdaVerified, Estimated, None }

/** The status-pill variant for meal detail — mirrors [app.mealsy.android.ui.home.HomeKcalState]. */
sealed interface MealDetailStatus {
    data class FitsBudget(val kcalRemaining: Int) : MealDetailStatus

    data class OverBudget(val kcalOver: Int) : MealDetailStatus

    data object Logged : MealDetailStatus
}

/** Coach-note variant, kept as semantic data so the screen resolves copy from `strings.xml`. */
sealed interface MealDetailCoachNote {
    data class ProteinSource(val itemName: String, val alsoEstimated: Boolean) : MealDetailCoachNote

    data object EstimateOnly : MealDetailCoachNote

    data object None : MealDetailCoachNote
}

/** One ingredient row as rendered by the screen. */
data class MealDetailItemRow(
    val humanizedName: String,
    val rawName: String?,
    val qtyG: Int,
    val kcal: Int,
)

/** Rendering state for [MealDetailScreen]. */
sealed interface MealDetailUiState {
    data object Loading : MealDetailUiState

    data class Error(val kind: ErrorKind) : MealDetailUiState

    data class Loaded(
        val mode: MealDetailMode,
        val title: String,
        val mealType: String?,
        val timeLabel: String?,
        val heroTone: TagTone,
        val kcal: Int,
        val proteinG: Int,
        val thirdTag: MealDetailThirdTag,
        val status: MealDetailStatus,
        val items: List<MealDetailItemRow>,
        val coachNote: MealDetailCoachNote,
    ) : MealDetailUiState
}

/** State for the "log again" bottom sheet. */
data class LogAgainSheetState(
    val visible: Boolean = false,
    val mealType: String = "lunch",
    val portion: Double = 1.0,
    val submitting: Boolean = false,
    val error: String? = null,
)

/** One-shot navigation/feedback events the screen reacts to. */
sealed interface MealDetailEvent {
    data object Logged : MealDetailEvent

    data object Deleted : MealDetailEvent
}

/**
 * Drives the meal-detail screen for both a logged meal
 * ([MealDetailMode.Logged]) and a saved "My Meal" ([MealDetailMode.MyMeal]),
 * including the "log again" bottom sheet and (logged mode only) delete.
 *
 * The nav route carries either a `mealId` arg (`meal/{mealId}`) or an `id`
 * arg (`my-meal/{id}`) — whichever [SavedStateHandle] holds picks the mode.
 */
@HiltViewModel
class MealDetailViewModel
    @Inject
    constructor(
        savedStateHandle: SavedStateHandle,
        private val mealsRepository: MealsRepository,
        private val myMealsRepository: MyMealsRepository,
        private val chatRepository: ChatRepository,
        private val goalsRepository: GoalsRepository,
        private val api: MealsyApi,
        private val clock: Clock,
    ) : ViewModel() {
        val mode: MealDetailMode =
            savedStateHandle.get<String>("mealId")?.let { MealDetailMode.Logged(it) }
                ?: savedStateHandle.get<String>("id")?.let { MealDetailMode.MyMeal(it) }
                ?: error("MealDetailViewModel requires either a mealId or id nav arg")

        private val _uiState = MutableStateFlow<MealDetailUiState>(MealDetailUiState.Loading)
        val uiState: StateFlow<MealDetailUiState> = _uiState.asStateFlow()

        private val _sheetState = MutableStateFlow(LogAgainSheetState())
        val sheetState: StateFlow<LogAgainSheetState> = _sheetState.asStateFlow()

        private val _events = Channel<MealDetailEvent>(Channel.BUFFERED)
        val events = _events.receiveAsFlow()

        /** The raw items backing the current [MealDetailUiState.Loaded], kept for building a log-again payload. */
        private var loadedIngredients: List<UiIngredient> = emptyList()

        val readyJob = viewModelScope.launch { load() }

        private suspend fun load() {
            _uiState.value = MealDetailUiState.Loading
            try {
                when (val m = mode) {
                    is MealDetailMode.Logged -> loadLogged(m)
                    is MealDetailMode.MyMeal -> loadMyMeal(m)
                }
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: IOException) {
                _uiState.value = MealDetailUiState.Error(ErrorKind.Offline)
            } catch (exc: Exception) {
                _uiState.value = MealDetailUiState.Error(ErrorKind.LoadFailed)
            }
        }

        /** Re-runs [load] — used by the error state's retry button. */
        fun retry() {
            viewModelScope.launch { load() }
        }

        private suspend fun loadLogged(mode: MealDetailMode.Logged) {
            val (detail, goals, today) =
                coroutineScope {
                    val detailDeferred = async { mealsRepository.detail(mode.mealId) }
                    val goalsDeferred = async { goalsRepository.get() }
                    val todayDeferred = async { api.today() }
                    Triple(detailDeferred.await(), goalsDeferred.await(), todayDeferred.await())
                }
            val ingredients = detail.items.map { it.toUiIngredient() }
            loadedIngredients = ingredients
            _sheetState.value = LogAgainSheetState(mealType = defaultMealCategory(clock))

            val title =
                detail.meal.label?.takeIf { it.isNotBlank() }
                    ?.let { app.mealsy.domain.FoodNameHumanizer.humanize(it) }
                    ?: ingredients.firstOrNull()?.let { app.mealsy.domain.FoodNameHumanizer.humanize(it.foodName) }
                    ?: "Logged meal"

            _uiState.value =
                MealDetailUiState.Loaded(
                    mode = mode,
                    title = title,
                    mealType = detail.meal.mealType,
                    timeLabel = detail.meal.loggedAt,
                    heroTone = mealTypeTone(detail.meal.mealType),
                    kcal = detail.meal.kcal.roundToInt(),
                    proteinG = detail.meal.proteinG.roundToInt(),
                    thirdTag = thirdTagFor(ingredients),
                    status = statusFor(goals, today.kcal),
                    items = ingredients.map { it.toRow() },
                    coachNote = coachNoteFor(ingredients),
                )
        }

        private suspend fun loadMyMeal(mode: MealDetailMode.MyMeal) {
            val (detail, goals, today) =
                coroutineScope {
                    val detailDeferred = async { myMealsRepository.detail(mode.id) }
                    val goalsDeferred = async { goalsRepository.get() }
                    val todayDeferred = async { api.today() }
                    Triple(detailDeferred.await(), goalsDeferred.await(), todayDeferred.await())
                }
            val ingredients = detail.ingredients.map { it.toUiIngredient() }
            loadedIngredients = ingredients
            _sheetState.value = LogAgainSheetState(mealType = defaultMealCategory(clock))

            _uiState.value =
                MealDetailUiState.Loaded(
                    mode = mode,
                    title = app.mealsy.domain.FoodNameHumanizer.humanize(detail.meal.name),
                    mealType = null,
                    timeLabel = null,
                    // My-Meal mode has no meal type to derive a tone from — Powder is the
                    // stable pastel chosen for this hero, since it otherwise means
                    // "estimated"/informational rather than a specific meal-type slot.
                    heroTone = TagTone.Powder,
                    kcal = detail.meal.kcal.roundToInt(),
                    proteinG = detail.meal.proteinG.roundToInt(),
                    thirdTag = thirdTagFor(ingredients),
                    status = statusFor(goals, today.kcal),
                    items = ingredients.map { it.toRow() },
                    coachNote = coachNoteFor(ingredients),
                )
        }

        private fun statusFor(
            goals: Goals?,
            todayKcal: Double,
        ): MealDetailStatus {
            val kcalGoal = goals?.kcalGoal
            val mindful = goals == null || goals.trackingMode == "mindful" || kcalGoal == null
            if (mindful) return MealDetailStatus.Logged
            checkNotNull(kcalGoal)
            return if (todayKcal <= kcalGoal) {
                MealDetailStatus.FitsBudget((kcalGoal - todayKcal).roundToInt())
            } else {
                MealDetailStatus.OverBudget((todayKcal - kcalGoal).roundToInt())
            }
        }

        private fun thirdTagFor(items: List<UiIngredient>): MealDetailThirdTag =
            when {
                items.isNotEmpty() && items.all { it.source() == "USDA" && !it.estimated } ->
                    MealDetailThirdTag.UsdaVerified
                items.any { it.estimated } -> MealDetailThirdTag.Estimated
                else -> MealDetailThirdTag.None
            }

        private fun coachNoteFor(items: List<UiIngredient>): MealDetailCoachNote {
            val anyEstimated = items.any { it.estimated }
            val topProtein = items.filter { it.proteinG > 0 }.maxByOrNull { it.proteinG }
            return when {
                topProtein != null ->
                    MealDetailCoachNote.ProteinSource(
                        itemName = app.mealsy.domain.FoodNameHumanizer.humanize(topProtein.foodName),
                        alsoEstimated = anyEstimated,
                    )
                anyEstimated -> MealDetailCoachNote.EstimateOnly
                else -> MealDetailCoachNote.None
            }
        }

        // -- Log-again sheet ------------------------------------------------

        fun openSheet() {
            _sheetState.update { it.copy(visible = true, error = null) }
        }

        fun dismissSheet() {
            if (_sheetState.value.submitting) return
            _sheetState.update { it.copy(visible = false, error = null) }
        }

        fun selectSheetMealType(mealType: String) {
            _sheetState.update { it.copy(mealType = mealType) }
        }

        fun selectSheetPortion(portion: Double) {
            _sheetState.update { it.copy(portion = portion) }
        }

        /** Confirms the log-again sheet: logs via [chatRepository] or [myMealsRepository] depending on [mode]. */
        fun confirmSheet() {
            val sheet = _sheetState.value
            if (sheet.submitting) return
            _sheetState.update { it.copy(submitting = true, error = null) }
            viewModelScope.launch {
                try {
                    when (val m = mode) {
                        is MealDetailMode.Logged -> logAgainLogged(m, sheet)
                        is MealDetailMode.MyMeal -> logAgainMyMeal(m, sheet)
                    }
                    _sheetState.value = LogAgainSheetState(mealType = sheet.mealType, portion = sheet.portion)
                    _events.send(MealDetailEvent.Logged)
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: Exception) {
                    _sheetState.update { it.copy(submitting = false, error = "Couldn't log that. Try again.") }
                }
            }
        }

        private suspend fun logAgainLogged(
            mode: MealDetailMode.Logged,
            sheet: LogAgainSheetState,
        ) {
            val card =
                ConfirmationCard(
                    message = "",
                    items = loadedIngredients.map { it.toCardItem() },
                    mealType = sheet.mealType,
                    portion = sheet.portion,
                )
            when (chatRepository.confirmCard(card)) {
                is LogOutcome.Logged, LogOutcome.Queued -> Unit
            }
        }

        private suspend fun logAgainMyMeal(
            mode: MealDetailMode.MyMeal,
            sheet: LogAgainSheetState,
        ) {
            if (sheet.portion == 1.0) {
                myMealsRepository.quickLog(mode.id, sheet.mealType)
            } else {
                val overrides =
                    loadedIngredients.mapIndexed { index, ingredient ->
                        SavedMealOverride(index = index, qtyG = ingredient.qtyG)
                    }
                myMealsRepository.logCustomized(mode.id, sheet.mealType, overrides, sheet.portion)
            }
        }

        // -- Delete (logged mode only) --------------------------------------

        fun delete() {
            val m = mode as? MealDetailMode.Logged ?: return
            viewModelScope.launch {
                try {
                    mealsRepository.delete(m.mealId)
                    _events.send(MealDetailEvent.Deleted)
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: Exception) {
                    // Best-effort: leave the screen as-is; the user can retry from the button again.
                }
            }
        }
    }

private fun LoggedMealItem.toUiIngredient(): UiIngredient =
    UiIngredient(
        foodName = foodName,
        qtyG = qtyG,
        kcal = kcal,
        proteinG = proteinG,
        carbsG = carbsG,
        fatG = fatG,
        fiberG = fiberG,
        fdcId = fdcId,
        estimated = estimated,
        extras = extras,
    )

private fun SavedMealItem.toUiIngredient(): UiIngredient =
    UiIngredient(
        foodName = foodName,
        qtyG = qtyG,
        kcal = kcal,
        proteinG = proteinG,
        carbsG = carbsG,
        fatG = fatG,
        fiberG = fiberG,
        fdcId = fdcId,
        estimated = estimated,
        extras = extras,
    )

private fun UiIngredient.toRow(): MealDetailItemRow {
    val humanized = app.mealsy.domain.FoodNameHumanizer.humanize(foodName)
    return MealDetailItemRow(
        humanizedName = humanized,
        rawName = foodName.takeIf { it != humanized },
        qtyG = qtyG.roundToInt(),
        kcal = kcal.roundToInt(),
    )
}

private fun UiIngredient.toCardItem(): CardItem =
    CardItem(
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
    )

private fun mealTypeTone(mealType: String): TagTone =
    when (mealType) {
        "breakfast" -> TagTone.Butter
        "lunch" -> TagTone.Leaf
        "dinner" -> TagTone.Pink
        else -> TagTone.Powder
    }
