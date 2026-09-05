package app.mealsy.android.ui.onboarding

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.domain.Goals
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import retrofit2.HttpException

/**
 * The backend imposes no numeric defaults of its own — `GoalCreate` in
 * `src/backend/api/goals.py` defaults `kcal_goal`/`protein_goal`/`fiber_goal`
 * to `null`, but its validator then *requires* all three whenever
 * `tracking_mode == "goals"`. These are this client's own sensible starting
 * point (not a backend contract) so "Skip for now" and the prefilled first
 * step always post a valid `GoalCreate` body.
 */
const val DEFAULT_TRACKING_MODE: String = "goals"
const val DEFAULT_KCAL_GOAL: Double = 2000.0
const val DEFAULT_PROTEIN_GOAL: Double = 100.0
const val DEFAULT_FIBER_GOAL: Double = 30.0

/**
 * Stepper floors. The backend's `GoalCreate`/`GoalUpdate` validators require
 * `gt=0` on all three fields whenever `tracking_mode == "goals"` — a bare
 * `coerceAtLeast(0.0)` lets a user step a goal down to exactly `0`, which
 * passes client-side but 422s on submit. Floors are set to each stepper's
 * own step size (never `0`, and never below a sane minimum) so decrementing
 * can't reach zero in the first place; [goalsSubmissionError] is a second,
 * independent guard against `0` reaching [OnboardingViewModel.submit] some
 * other way (e.g. a future text-entry path that bypasses the stepper).
 */
const val MIN_KCAL_GOAL: Double = 50.0
const val MIN_PROTEIN_GOAL: Double = 5.0
const val MIN_FIBER_GOAL: Double = 5.0

/** Preset dietary preference chips offered on step 3. Backend `dietary_prefs` imposes no fixed vocabulary. */
val DIETARY_PREF_OPTIONS: List<String> = listOf(
    "vegetarian", "vegan", "gluten_free", "dairy_free", "halal", "kosher",
)

data class OnboardingUiState(
    val step: Int = 0,
    val trackingMode: String = DEFAULT_TRACKING_MODE,
    val kcalGoal: Double = DEFAULT_KCAL_GOAL,
    val proteinGoal: Double = DEFAULT_PROTEIN_GOAL,
    val fiberGoal: Double = DEFAULT_FIBER_GOAL,
    val dietaryPrefs: Set<String> = emptySet(),
    val saving: Boolean = false,
    val error: String? = null,
    val done: Boolean = false,
)

private const val LAST_STEP = 2

/**
 * Mirrors the backend's `gt=0` requirement (`GoalCreate`/`GoalUpdate` in
 * `src/backend/api/goals.py`) client-side, with a specific message —
 * without this, an invalid value would only surface as the generic
 * "Could not save" text after a 422 round trip. A top-level function (rather
 * than a private method) so it's directly unit-testable independent of
 * [OnboardingViewModel]'s state.
 */
internal fun goalsSubmissionError(goals: Goals): String? {
    if (goals.trackingMode != "goals") return null
    val invalid = listOfNotNull(
        "Calories".takeIf { (goals.kcalGoal ?: 0.0) <= 0.0 },
        "Protein".takeIf { (goals.proteinGoal ?: 0.0) <= 0.0 },
        "Fiber".takeIf { (goals.fiberGoal ?: 0.0) <= 0.0 },
    )
    if (invalid.isEmpty()) return null
    return "${invalid.joinToString(", ")} goal must be greater than 0."
}

/**
 * Drives the 3-step onboarding pager (tracking mode -> numeric goals ->
 * dietary prefs) and posts the result via [GoalsRepository.create].
 *
 * "Skip for now" ([skip]) always posts [defaultGoals], ignoring whatever the
 * user may have already typed into a step they haven't confirmed — it's an
 * explicit "use the defaults" action, not "save whatever's on screen".
 */
@HiltViewModel
class OnboardingViewModel @Inject constructor(
    private val goalsRepository: GoalsRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(OnboardingUiState())
    val uiState: StateFlow<OnboardingUiState> = _uiState.asStateFlow()

    fun setTrackingMode(mode: String) {
        _uiState.update { it.copy(trackingMode = mode) }
    }

    fun setKcalGoal(value: Double) {
        _uiState.update { it.copy(kcalGoal = value.coerceAtLeast(MIN_KCAL_GOAL)) }
    }

    fun setProteinGoal(value: Double) {
        _uiState.update { it.copy(proteinGoal = value.coerceAtLeast(MIN_PROTEIN_GOAL)) }
    }

    fun setFiberGoal(value: Double) {
        _uiState.update { it.copy(fiberGoal = value.coerceAtLeast(MIN_FIBER_GOAL)) }
    }

    fun toggleDietaryPref(pref: String) {
        _uiState.update {
            val next = if (pref in it.dietaryPrefs) it.dietaryPrefs - pref else it.dietaryPrefs + pref
            it.copy(dietaryPrefs = next)
        }
    }

    fun nextStep() {
        _uiState.update { it.copy(step = (it.step + 1).coerceAtMost(LAST_STEP)) }
    }

    fun prevStep() {
        _uiState.update { it.copy(step = (it.step - 1).coerceAtLeast(0)) }
    }

    /** Saves the currently entered values (from all three steps). */
    fun save() {
        submit(currentGoals())
    }

    /** Saves the untouched backend defaults, regardless of anything already typed. */
    fun skip() {
        submit(defaultGoals())
    }

    /**
     * `internal` (rather than `private`) so tests can exercise the
     * validation path directly: [save] and [skip] only ever reach [submit]
     * with values the floor-clamped setters have already guaranteed are
     * `> 0` (see [MIN_KCAL_GOAL] etc.), so there's no way to drive an
     * invalid submit through the public API alone.
     */
    internal fun submit(goals: Goals) {
        val validationError = goalsSubmissionError(goals)
        if (validationError != null) {
            _uiState.update { it.copy(error = validationError) }
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(saving = true, error = null) }
            try {
                goalsRepository.create(goals)
                _uiState.update { it.copy(saving = false, done = true) }
            } catch (exc: HttpException) {
                if (exc.code() == 409) {
                    // Goals already exist for this user (e.g. a retried submit, or
                    // onboarding re-entered after a prior success) — proceed to
                    // chat rather than surfacing this as a failure.
                    _uiState.update { it.copy(saving = false, done = true) }
                } else {
                    _uiState.update {
                        it.copy(saving = false, error = "Could not save your goals. Try again.")
                    }
                }
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                _uiState.update {
                    it.copy(saving = false, error = "Could not save your goals. Try again.")
                }
            }
        }
    }

    private fun currentGoals(): Goals {
        val state = _uiState.value
        return Goals(
            trackingMode = state.trackingMode,
            kcalGoal = state.kcalGoal,
            proteinGoal = state.proteinGoal,
            fiberGoal = state.fiberGoal,
            dietaryPrefs = state.dietaryPrefs.associateWith { true },
        )
    }

    private fun defaultGoals(): Goals = Goals(
        trackingMode = DEFAULT_TRACKING_MODE,
        kcalGoal = DEFAULT_KCAL_GOAL,
        proteinGoal = DEFAULT_PROTEIN_GOAL,
        fiberGoal = DEFAULT_FIBER_GOAL,
        dietaryPrefs = emptyMap(),
    )
}
