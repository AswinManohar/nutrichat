package app.mealsy.android.ui.onboarding

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.data.auth.SessionManager
import app.mealsy.data.error.ErrorReporter
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.data.repo.ProfileStore
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
 * point (not a backend contract).
 *
 * These four names are legacy from the onboarding flow's earlier 3-step
 * numeric-goals model. They are no longer used by [OnboardingViewModel]
 * itself (see the six-state flow below) but [app.mealsy.android.ui.settings.SettingsViewModel]
 * still imports them for its own "edit goals" screen, so they stay declared
 * in this file/package rather than being deleted.
 */
const val DEFAULT_TRACKING_MODE: String = "goals"
const val DEFAULT_KCAL_GOAL: Double = 2000.0
const val DEFAULT_PROTEIN_GOAL: Double = 100.0
const val DEFAULT_FIBER_GOAL: Double = 30.0

/**
 * Stepper floors, same legacy status as the `DEFAULT_*` constants above —
 * kept only because [app.mealsy.android.ui.settings.SettingsViewModel]
 * still depends on them for its numeric goal steppers.
 */
const val MIN_KCAL_GOAL: Double = 50.0
const val MIN_PROTEIN_GOAL: Double = 5.0
const val MIN_FIBER_GOAL: Double = 5.0

/**
 * Preset dietary preference chips from the old 3-step flow. Legacy, same
 * status as the constants above — [DietaryPrefsStep] (still used by
 * [app.mealsy.android.ui.settings.SettingsScreen]) is the only remaining
 * reference. The new onboarding flow's own preferences live in [DietaryPref].
 */
val DIETARY_PREF_OPTIONS: List<String> = listOf(
    "vegetarian", "vegan", "gluten_free", "dairy_free", "halal", "kosher",
)

/**
 * Mirrors the backend's `gt=0` requirement (`GoalCreate`/`GoalUpdate` in
 * `src/backend/api/goals.py`) client-side, with a specific message. Legacy,
 * same status as the constants above — [app.mealsy.android.ui.settings.SettingsViewModel]
 * is this function's only remaining caller; the new onboarding flow never
 * lets a non-positive value reach [Goals] in the first place (the kcal
 * slider is clamped to `1400..3200`).
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
 * A goal focus chosen on onboarding step 2.
 *
 * [key] is what's written to Supabase user metadata (`goal_focus`, see
 * [SessionManager.updateProfileMetadata]). [defaultKcal] seeds the step-4
 * slider the moment the user leaves step 2 (see [OnboardingViewModel.next]).
 * [proteinShare] is `null` for [Learn] — that's this flow's "mindful" mode
 * (plan Assumption 3): no numeric targets are derived or posted at all.
 * [trackingMode] is the literal the backend's `GoalCreate.tracking_mode`
 * expects (`src/backend/api/goals.py`).
 */
enum class OnboardingGoal(
    val key: String,
    val defaultKcal: Int,
    val proteinShare: Double?,
    val trackingMode: String,
) {
    Lose("lose", 1800, 0.25, "goals"),
    Maintain("maintain", 2200, 0.20, "goals"),
    Build("build", 2600, 0.30, "goals"),
    Learn("learn", 2200, null, "mindful"),
}

/**
 * A dietary preference chip on step 3. [key] is the wire key written into
 * [Goals.dietaryPrefs]. Declaration order here is display order.
 */
enum class DietaryPref(val key: String) {
    Vegetarian("vegetarian"),
    Vegan("vegan"),
    Pescatarian("pescatarian"),
    NoDairy("dairy_free"),
    NoGluten("gluten_free"),
    LowSodium("low_sodium"),
    LowSugar("low_sugar"),
    NoNuts("no_nuts"),
}

/** Label for the primary button. Copy for each value lives in `strings.xml` — this is not text. */
enum class ContinueLabel { Continue, NothingToAvoid, Finish }

private const val MIN_KCAL_TARGET = 1400
private const val MAX_KCAL_TARGET = 3200
private const val KCAL_STEP = 50
private const val FALLBACK_KCAL_TARGET = 2200
private const val LAST_STEP = 5

private const val KEY_STEP = "onboarding_step"
private const val KEY_NAME = "onboarding_name"
private const val KEY_GOAL = "onboarding_goal"
private const val KEY_PREFS = "onboarding_prefs"
private const val KEY_KCAL = "onboarding_kcal"
private const val KEY_START_STEP = "startStep"

/**
 * UI state for the six-step onboarding flow: `0` Welcome, `1` Name, `2`
 * Goal, `3` Preferences, `4` Target, `5` Done.
 *
 * [step], [name], [goal], [prefs] and [kcalTarget] are the raw, persisted
 * fields (backed by [SavedStateHandle] — see [OnboardingViewModel]); every
 * other field is derived from them and recomputed on every mutation.
 */
data class OnboardingUiState(
    val step: Int,
    val startStep: Int,
    val name: String,
    val firstName: String,
    val goal: OnboardingGoal?,
    val prefs: Set<DietaryPref>,
    val kcalTarget: Int,
    val continueEnabled: Boolean,
    val continueLabel: ContinueLabel,
    val progress: Float,
    val isMindful: Boolean,
    val coachNotePrefs: List<DietaryPref>,
    val hasMorePrefs: Boolean,
    val saving: Boolean,
    val error: Boolean,
    val done: Boolean,
)

/**
 * Drives the six-step onboarding flow (welcome -> name -> goal ->
 * preferences -> target -> done) and, on leaving the target step, writes
 * the result to Supabase user metadata, the local [ProfileStore] cache, and
 * `POST /goals` via [GoalsRepository].
 *
 * All persisted fields ([OnboardingUiState.step], [OnboardingUiState.name],
 * [OnboardingUiState.goal], [OnboardingUiState.prefs],
 * [OnboardingUiState.kcalTarget]) are mirrored into [savedStateHandle] on
 * every mutation and restored from it in [loadInitialState], so the flow
 * survives process death. `startStep` is read once from the nav
 * arguments Hilt lands in [savedStateHandle] (`0` for a signed-out welcome,
 * `1` for a signed-in user with no goals yet) and used both as the initial
 * step and as [back]'s floor — a signed-in user entering at step 1 must
 * never see the welcome screen.
 */
@HiltViewModel
class OnboardingViewModel @Inject constructor(
    private val savedStateHandle: SavedStateHandle,
    private val sessionManager: SessionManager,
    private val profileStore: ProfileStore,
    private val goalsRepository: GoalsRepository,
    private val errorReporter: ErrorReporter = ErrorReporter {},
) : ViewModel() {

    private val _uiState = MutableStateFlow(loadInitialState())
    val uiState: StateFlow<OnboardingUiState> = _uiState.asStateFlow()

    private fun loadInitialState(): OnboardingUiState {
        val startStep = savedStateHandle.get<Int>(KEY_START_STEP) ?: 0
        val step = savedStateHandle.get<Int>(KEY_STEP) ?: startStep
        val name = savedStateHandle.get<String>(KEY_NAME) ?: ""
        val goalKey = savedStateHandle.get<String>(KEY_GOAL)
        val goal = OnboardingGoal.entries.find { it.key == goalKey }
        val prefKeys = savedStateHandle.get<ArrayList<String>>(KEY_PREFS) ?: arrayListOf()
        val prefs = prefKeys.mapNotNull { key -> DietaryPref.entries.find { it.key == key } }.toSet()
        val kcalTarget = savedStateHandle.get<Int>(KEY_KCAL) ?: (goal?.defaultKcal ?: FALLBACK_KCAL_TARGET)
        return recompute(
            OnboardingUiState(
                step = step,
                startStep = startStep,
                name = name,
                firstName = "",
                goal = goal,
                prefs = prefs,
                kcalTarget = kcalTarget,
                continueEnabled = false,
                continueLabel = ContinueLabel.Continue,
                progress = 0f,
                isMindful = false,
                coachNotePrefs = emptyList(),
                hasMorePrefs = false,
                saving = false,
                error = false,
                done = false,
            ),
        )
    }

    /** Recomputes every derived field of [base] from its raw fields. */
    private fun recompute(base: OnboardingUiState): OnboardingUiState {
        val continueEnabled = when (base.step) {
            1 -> base.name.isNotBlank()
            2 -> base.goal != null
            else -> true
        }
        val continueLabel = when (base.step) {
            4 -> ContinueLabel.Finish
            3 -> if (base.prefs.isEmpty()) ContinueLabel.NothingToAvoid else ContinueLabel.Continue
            else -> ContinueLabel.Continue
        }
        val orderedSelected = DietaryPref.entries.filter { it in base.prefs }
        return base.copy(
            firstName = firstNameOf(base.name),
            continueEnabled = continueEnabled,
            continueLabel = continueLabel,
            progress = base.step / 4f,
            isMindful = base.goal == OnboardingGoal.Learn,
            coachNotePrefs = orderedSelected.take(2),
            hasMorePrefs = orderedSelected.size > 2,
        )
    }

    private fun firstNameOf(name: String): String = name.trim().substringBefore(' ')

    fun setName(value: String) {
        savedStateHandle[KEY_NAME] = value
        _uiState.update { recompute(it.copy(name = value)) }
    }

    fun selectGoal(goal: OnboardingGoal) {
        savedStateHandle[KEY_GOAL] = goal.key
        _uiState.update { recompute(it.copy(goal = goal)) }
    }

    fun togglePref(pref: DietaryPref) {
        val next = _uiState.value.prefs.let { if (pref in it) it - pref else it + pref }
        savedStateHandle[KEY_PREFS] = ArrayList(next.map { it.key })
        _uiState.update { recompute(it.copy(prefs = next)) }
    }

    fun setKcalTarget(value: Int) {
        val quantized = (Math.round(value / KCAL_STEP.toDouble()).toInt() * KCAL_STEP)
            .coerceIn(MIN_KCAL_TARGET, MAX_KCAL_TARGET)
        savedStateHandle[KEY_KCAL] = quantized
        _uiState.update { recompute(it.copy(kcalTarget = quantized)) }
    }

    /**
     * Advances to the next step. Leaving step 2 with a goal chosen applies
     * that goal's [OnboardingGoal.defaultKcal] to the step-4 slider — going
     * back to step 2, picking a different goal and leaving again
     * re-applies the new default (this always runs on step 2 -> 3, never
     * only once). Leaving step 4 moves to the done step and starts the
     * finish side effects (step 5 renders while [OnboardingUiState.saving]
     * is true).
     */
    fun next() {
        val current = _uiState.value
        if (!current.continueEnabled) return
        when (current.step) {
            2 -> {
                val goal = current.goal ?: return
                val nextStep = 3
                savedStateHandle[KEY_STEP] = nextStep
                savedStateHandle[KEY_KCAL] = goal.defaultKcal
                _uiState.update { recompute(it.copy(step = nextStep, kcalTarget = goal.defaultKcal)) }
            }
            4 -> {
                val nextStep = 5
                savedStateHandle[KEY_STEP] = nextStep
                _uiState.update { recompute(it.copy(step = nextStep)) }
                startFinish()
            }
            else -> {
                val nextStep = (current.step + 1).coerceAtMost(LAST_STEP)
                savedStateHandle[KEY_STEP] = nextStep
                _uiState.update { recompute(it.copy(step = nextStep)) }
            }
        }
    }

    /** Moves back one step, clamped at [OnboardingUiState.startStep]. */
    fun back() {
        val current = _uiState.value
        val prevStep = (current.step - 1).coerceAtLeast(current.startStep)
        savedStateHandle[KEY_STEP] = prevStep
        _uiState.update { recompute(it.copy(step = prevStep)) }
    }

    /** Re-runs the finish sequence after [OnboardingUiState.error]. */
    fun retry() {
        startFinish()
    }

    private fun startFinish() {
        viewModelScope.launch { runFinish() }
    }

    /**
     * 1. Best-effort write to Supabase user metadata.
     * 2. Best-effort write to the local [ProfileStore] cache.
     * 3. `POST /goals` via [GoalsRepository.create] — a 409 (goals already
     *    exist for this user, e.g. a retried finish) is treated as success.
     *
     * Any other failure from step 3 sets [OnboardingUiState.error]; [retry]
     * re-runs this whole sequence, including the best-effort steps.
     */
    private suspend fun runFinish() {
        _uiState.update { recompute(it.copy(saving = true, error = false)) }
        val state = _uiState.value
        val goal = state.goal
        if (goal == null) {
            // Shouldn't happen — next() only reaches step 4 -> 5 once a
            // goal has been chosen (step 2's gating). Defensive guard in
            // case a corrupted SavedStateHandle restore reaches finish
            // with no goal at all.
            _uiState.update { recompute(it.copy(saving = false, error = true)) }
            return
        }
        val firstName = state.firstName
        try {
            if (firstName.isNotBlank()) {
                try {
                    sessionManager.updateProfileMetadata(firstName, goal.key)
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: Exception) {
                    errorReporter.record(exc)
                }
                try {
                    profileStore.set(firstName, goal.key)
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: Exception) {
                    errorReporter.record(exc)
                }
            }
            val goals = buildGoals(goal, state.prefs, state.kcalTarget)
            try {
                goalsRepository.create(goals)
            } catch (exc: HttpException) {
                if (exc.code() != 409) throw exc
                // Goals already exist for this user (e.g. a retried
                // finish) — proceed as if this call had succeeded.
            }
            _uiState.update { recompute(it.copy(saving = false, done = true)) }
        } catch (exc: CancellationException) {
            throw exc
        } catch (exc: Exception) {
            _uiState.update { recompute(it.copy(saving = false, error = true)) }
        }
    }

    private fun buildGoals(goal: OnboardingGoal, prefs: Set<DietaryPref>, kcalTarget: Int): Goals {
        val proteinShare = goal.proteinShare
        val kcalGoal: Double?
        val proteinGoal: Double?
        val fiberGoal: Double?
        if (proteinShare == null) {
            kcalGoal = null
            proteinGoal = null
            fiberGoal = null
        } else {
            kcalGoal = kcalTarget.toDouble()
            proteinGoal = Math.round(kcalTarget * proteinShare / 4.0).toDouble()
            fiberGoal = Math.round(14.0 * kcalTarget / 1000.0).toDouble()
        }
        return Goals(
            trackingMode = goal.trackingMode,
            kcalGoal = kcalGoal,
            proteinGoal = proteinGoal,
            fiberGoal = fiberGoal,
            dietaryPrefs = prefs.associate { it.key to true },
        )
    }
}
