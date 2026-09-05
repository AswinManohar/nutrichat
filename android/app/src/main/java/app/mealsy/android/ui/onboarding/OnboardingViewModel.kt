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
        _uiState.update { it.copy(kcalGoal = value.coerceAtLeast(0.0)) }
    }

    fun setProteinGoal(value: Double) {
        _uiState.update { it.copy(proteinGoal = value.coerceAtLeast(0.0)) }
    }

    fun setFiberGoal(value: Double) {
        _uiState.update { it.copy(fiberGoal = value.coerceAtLeast(0.0)) }
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

    private fun submit(goals: Goals) {
        viewModelScope.launch {
            _uiState.update { it.copy(saving = true, error = null) }
            try {
                goalsRepository.create(goals)
                _uiState.update { it.copy(saving = false, done = true) }
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
