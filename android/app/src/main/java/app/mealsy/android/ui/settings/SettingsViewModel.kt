package app.mealsy.android.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.android.di.AppVersionCode
import app.mealsy.android.di.AppVersionName
import app.mealsy.android.push.DeviceTokenStore
import app.mealsy.android.push.PushRegistrar
import app.mealsy.android.ui.onboarding.DEFAULT_FIBER_GOAL
import app.mealsy.android.ui.onboarding.DEFAULT_KCAL_GOAL
import app.mealsy.android.ui.onboarding.DEFAULT_PROTEIN_GOAL
import app.mealsy.android.ui.onboarding.DEFAULT_TRACKING_MODE
import app.mealsy.android.ui.onboarding.OnboardingGoal
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.auth.SessionManager
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.data.repo.ProfileStore
import app.mealsy.domain.Goals
import dagger.hilt.android.lifecycle.HiltViewModel
import java.io.IOException
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import retrofit2.HttpException

/** The exact phrase the user must type to enable account deletion. */
const val DELETE_CONFIRMATION_PHRASE: String = "DELETE"

/**
 * Top-level (not a private method) so it's directly unit-testable, same
 * rationale as onboarding's own top-level validators.
 */
fun isDeleteConfirmed(typedText: String): Boolean = typedText == DELETE_CONFIRMATION_PHRASE

/**
 * How long a numeric goal / dietary-pref edit waits, with no further edits,
 * before it is sent as a `PUT /goals` — collapses rapid stepper taps or chip
 * toggles into a single request. Exposed as a constant (rather than a magic
 * number inline) so tests can `advanceTimeBy` past it deterministically.
 */
const val GOALS_SAVE_DEBOUNCE_MS: Long = 700

data class SettingsUiState(
    val goalsLoading: Boolean = true,
    val firstName: String = "",
    val goalFocus: String = OnboardingGoal.Maintain.key,
    val trackingMode: String = DEFAULT_TRACKING_MODE,
    val kcalGoal: Double = DEFAULT_KCAL_GOAL,
    val proteinGoal: Double = DEFAULT_PROTEIN_GOAL,
    val fiberGoal: Double = DEFAULT_FIBER_GOAL,
    val dietaryPrefs: Set<String> = emptySet(),
    val editingName: Boolean = false,
    val nameDraft: String = "",
    val showGoalSheet: Boolean = false,
    /** Non-null while the "use this goal's default kcal target" prompt is showing. */
    val kcalPromptGoal: OnboardingGoal? = null,
    val reminderEnabled: Boolean = false,
    val versionName: String = "",
    val versionCode: Int = 0,
    val updateAvailable: Boolean = false,
    val deleteConfirmationText: String = "",
    val deletingAccount: Boolean = false,
    val deleteError: String? = null,
    val signedOut: Boolean = false,
    /** Bumped on every successful debounced/immediate goals save — the screen
     *  keys an [app.mealsy.android.design.components.InkToast] "Saved" pulse off it. */
    val savedTick: Int = 0,
)

/**
 * Drives [SettingsScreen]: the always-live inline goals editor (no more
 * modal "editing goals" flow — every [Stepper]/[MealsyToggle]/
 * [FilterChipPill] edit auto-saves, numeric/dietary edits debounced by
 * [GOALS_SAVE_DEBOUNCE_MS]), profile name and goal-focus edits (written to
 * both [ProfileStore] and Supabase user metadata via
 * [SessionManager.updateProfileMetadata]), the daily-reminder toggle
 * ([PushRegistrar]), the app-version nudge, sign out, and account deletion.
 *
 * Account deletion ordering matters: [MealsyApi.deleteAccount] kills the
 * Supabase auth user server-side (cascading their device rows too), so it
 * must run *before* [SessionManager.signOut] — calling signOut first would
 * clear the local session and make the DELETE request 401. Signing out
 * afterwards is still safe even though its own best-effort device-deletion
 * hook will now 401 (the row is already gone server-side) — SessionManager
 * swallows that hook's failures and still clears local state.
 */
@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val goalsRepository: GoalsRepository,
    private val sessionManager: SessionManager,
    private val api: MealsyApi,
    private val pushRegistrar: PushRegistrar,
    private val tokenStore: DeviceTokenStore,
    private val profileStore: ProfileStore,
    @AppVersionCode private val currentVersionCode: Int,
    @AppVersionName versionName: String,
) : ViewModel() {

    private val _uiState = MutableStateFlow(
        SettingsUiState(versionName = versionName, versionCode = currentVersionCode),
    )
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    /** The last goals fetched/saved while in `goals` mode — restored when the tracking toggle is switched back on. */
    private var lastKnownGoals: Goals? = null

    /** Cancelled and relaunched on every numeric/dietary edit — see [scheduleDebouncedSave]. */
    private var saveJob: Job? = null

    init {
        loadGoals()
        loadReminderState()
        loadAppMeta()
        loadProfile()
    }

    private fun loadProfile() {
        viewModelScope.launch {
            val profile = try {
                profileStore.get()
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                null
            }
            if (profile != null) {
                _uiState.update {
                    it.copy(
                        firstName = profile.firstName ?: it.firstName,
                        goalFocus = profile.goalFocus ?: it.goalFocus,
                    )
                }
            }
        }
    }

    private fun loadGoals() {
        viewModelScope.launch {
            _uiState.update { it.copy(goalsLoading = true) }
            val goals = try {
                goalsRepository.get()
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                null
            }
            if (goals != null && goals.trackingMode == "goals") lastKnownGoals = goals
            _uiState.update {
                if (goals != null) {
                    it.copy(
                        goalsLoading = false,
                        trackingMode = goals.trackingMode,
                        kcalGoal = goals.kcalGoal ?: DEFAULT_KCAL_GOAL,
                        proteinGoal = goals.proteinGoal ?: DEFAULT_PROTEIN_GOAL,
                        fiberGoal = goals.fiberGoal ?: DEFAULT_FIBER_GOAL,
                        dietaryPrefs = goals.dietaryPrefs.filterValues { v -> v }.keys,
                    )
                } else {
                    it.copy(goalsLoading = false)
                }
            }
        }
    }

    private fun loadReminderState() {
        viewModelScope.launch {
            val enabled = try {
                !tokenStore.isRemindersDisabled() && tokenStore.getLastSentToken() != null
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                false
            }
            _uiState.update { it.copy(reminderEnabled = enabled) }
        }
    }

    private fun loadAppMeta() {
        viewModelScope.launch {
            try {
                val meta = api.appMeta()
                _uiState.update {
                    it.copy(
                        versionCode = currentVersionCode,
                        updateAvailable = currentVersionCode < meta.latestVersionCode,
                    )
                }
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                _uiState.update { it.copy(versionCode = currentVersionCode) }
            }
        }
    }

    // --- Profile: name -----------------------------------------------------

    fun startEditingName() {
        _uiState.update { it.copy(editingName = true, nameDraft = it.firstName) }
    }

    fun setNameDraft(value: String) {
        _uiState.update { it.copy(nameDraft = value) }
    }

    fun cancelEditingName() {
        _uiState.update { it.copy(editingName = false) }
    }

    /** Writes the trimmed [SettingsUiState.nameDraft] to [ProfileStore] and Supabase user metadata. */
    fun saveName() {
        val name = _uiState.value.nameDraft.trim()
        if (name.isBlank()) {
            cancelEditingName()
            return
        }
        _uiState.update { it.copy(firstName = name, editingName = false) }
        viewModelScope.launch {
            val goalFocus = _uiState.value.goalFocus
            try {
                profileStore.set(name, null)
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                // Best-effort local cache write, same convention as onboarding's finish step.
            }
            try {
                sessionManager.updateProfileMetadata(name, goalFocus)
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                // Best-effort — the local cache above still reflects the edit.
            }
        }
    }

    // --- Profile: goal focus -------------------------------------------------

    fun openGoalSheet() {
        _uiState.update { it.copy(showGoalSheet = true) }
    }

    fun dismissGoalSheet() {
        _uiState.update { it.copy(showGoalSheet = false) }
    }

    /**
     * Writes the new goal focus to [ProfileStore] and Supabase user
     * metadata. When tracking mode is `goals`, also surfaces the
     * "use this goal's default kcal target" prompt
     * ([SettingsUiState.kcalPromptGoal]) — [useGoalDefaultKcal] or
     * [keepCurrentKcalTarget] resolves it.
     */
    fun selectGoalFocus(goal: OnboardingGoal) {
        _uiState.update { it.copy(goalFocus = goal.key, showGoalSheet = false) }
        viewModelScope.launch {
            val firstName = _uiState.value.firstName
            try {
                profileStore.set(null, goal.key)
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                // Best-effort, matching saveName's convention.
            }
            try {
                sessionManager.updateProfileMetadata(firstName, goal.key)
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                // Best-effort.
            }
        }
        if (_uiState.value.trackingMode == "goals") {
            _uiState.update { it.copy(kcalPromptGoal = goal) }
        }
    }

    fun keepCurrentKcalTarget() {
        _uiState.update { it.copy(kcalPromptGoal = null) }
    }

    fun useGoalDefaultKcal() {
        val goal = _uiState.value.kcalPromptGoal ?: return
        _uiState.update { it.copy(kcalPromptGoal = null) }
        setKcalGoal(goal.defaultKcal.toDouble())
    }

    // --- Targets: tracking mode + numeric goals -----------------------------

    /**
     * Turning tracking **on** restores [lastKnownGoals] (or the 2000/100/30
     * defaults when there is none) and saves immediately. Turning it **off**
     * nulls the goals via a `tracking_mode = "mindful"` `PUT /goals`,
     * immediately as well — neither transition waits for
     * [GOALS_SAVE_DEBOUNCE_MS].
     */
    fun setTrackingEnabled(enabled: Boolean) {
        if (enabled) {
            val restored = lastKnownGoals
            _uiState.update {
                it.copy(
                    trackingMode = "goals",
                    kcalGoal = restored?.kcalGoal ?: DEFAULT_KCAL_GOAL,
                    proteinGoal = restored?.proteinGoal ?: DEFAULT_PROTEIN_GOAL,
                    fiberGoal = restored?.fiberGoal ?: DEFAULT_FIBER_GOAL,
                )
            }
            saveJob?.cancel()
            viewModelScope.launch { performSave() }
        } else {
            _uiState.update { it.copy(trackingMode = "mindful") }
            saveJob?.cancel()
            viewModelScope.launch { performSave(nulled = true) }
        }
    }

    fun setKcalGoal(value: Double) {
        _uiState.update { it.copy(kcalGoal = value.coerceAtLeast(MIN_KCAL_GOAL)) }
        scheduleDebouncedSave()
    }

    fun setProteinGoal(value: Double) {
        _uiState.update { it.copy(proteinGoal = value.coerceAtLeast(MIN_PROTEIN_GOAL)) }
        scheduleDebouncedSave()
    }

    fun setFiberGoal(value: Double) {
        _uiState.update { it.copy(fiberGoal = value.coerceAtLeast(MIN_FIBER_GOAL)) }
        scheduleDebouncedSave()
    }

    fun toggleDietaryPref(pref: String) {
        _uiState.update {
            val next = if (pref in it.dietaryPrefs) it.dietaryPrefs - pref else it.dietaryPrefs + pref
            it.copy(dietaryPrefs = next)
        }
        scheduleDebouncedSave()
    }

    private fun scheduleDebouncedSave() {
        saveJob?.cancel()
        saveJob = viewModelScope.launch {
            delay(GOALS_SAVE_DEBOUNCE_MS)
            performSave()
        }
    }

    private suspend fun performSave(nulled: Boolean = false) {
        val state = _uiState.value
        val goals = if (nulled) {
            Goals(
                trackingMode = "mindful",
                kcalGoal = null,
                proteinGoal = null,
                fiberGoal = null,
                dietaryPrefs = state.dietaryPrefs.associateWith { true },
            )
        } else {
            Goals(
                trackingMode = state.trackingMode,
                kcalGoal = state.kcalGoal,
                proteinGoal = state.proteinGoal,
                fiberGoal = state.fiberGoal,
                dietaryPrefs = state.dietaryPrefs.associateWith { true },
            )
        }
        try {
            goalsRepository.update(goals)
            if (goals.trackingMode == "goals") lastKnownGoals = goals
            _uiState.update { it.copy(savedTick = it.savedTick + 1) }
        } catch (exc: CancellationException) {
            throw exc
        } catch (exc: Exception) {
            // Best-effort — the next edit (or app reopen) retries via loadGoals().
        }
    }

    // --- Reminders -----------------------------------------------------------

    /**
     * Toggle-off both unregisters the current device and sets the
     * "reminders disabled" flag ([DeviceTokenStore.setRemindersDisabled])
     * so that `AppNavViewModel`'s unconditional post-sign-in
     * [PushRegistrar.ensureRegistered] call can't silently undo it. Toggle-on
     * clears the flag first (so [PushRegistrar.ensureRegistered] doesn't
     * immediately no-op) and then registers.
     */
    fun setReminderEnabled(enabled: Boolean) {
        viewModelScope.launch {
            _uiState.update { it.copy(reminderEnabled = enabled) }
            try {
                if (enabled) {
                    tokenStore.setRemindersDisabled(false)
                    pushRegistrar.ensureRegistered()
                } else {
                    pushRegistrar.unregisterCurrentDevice()
                    tokenStore.setRemindersDisabled(true)
                }
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                // Best-effort, matching PushRegistrar's own contract — reflect
                // the requested state either way; the next toggle/app-open retries.
            }
        }
    }

    // --- Account ---------------------------------------------------------------

    fun setDeleteConfirmationText(text: String) {
        _uiState.update { it.copy(deleteConfirmationText = text, deleteError = null) }
    }

    /** True once the user has typed [DELETE_CONFIRMATION_PHRASE] exactly. */
    fun isDeleteConfirmedNow(): Boolean = isDeleteConfirmed(_uiState.value.deleteConfirmationText)

    fun deleteAccount() {
        if (!isDeleteConfirmedNow()) return

        viewModelScope.launch {
            _uiState.update { it.copy(deletingAccount = true, deleteError = null) }
            try {
                api.deleteAccount()
                sessionManager.signOut()
                _uiState.update { it.copy(deletingAccount = false, signedOut = true) }
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: IOException) {
                _uiState.update {
                    it.copy(
                        deletingAccount = false,
                        deleteError = "Couldn't reach Mealsy. Check your connection and try again.",
                    )
                }
            } catch (exc: HttpException) {
                _uiState.update {
                    it.copy(deletingAccount = false, deleteError = "Could not delete your account. Try again.")
                }
            } catch (exc: Exception) {
                _uiState.update {
                    it.copy(deletingAccount = false, deleteError = "Could not delete your account. Try again.")
                }
            }
        }
    }

    fun signOut() {
        viewModelScope.launch {
            sessionManager.signOut()
            _uiState.update { it.copy(signedOut = true) }
        }
    }

    private companion object {
        /** Stepper floors for the Targets section — distinct from onboarding's own clamps. */
        const val MIN_KCAL_GOAL: Double = 1000.0
        const val MIN_PROTEIN_GOAL: Double = 20.0
        const val MIN_FIBER_GOAL: Double = 5.0
    }
}
