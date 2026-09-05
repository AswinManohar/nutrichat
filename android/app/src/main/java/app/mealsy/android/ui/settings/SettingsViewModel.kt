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
import app.mealsy.android.ui.onboarding.MIN_FIBER_GOAL
import app.mealsy.android.ui.onboarding.MIN_KCAL_GOAL
import app.mealsy.android.ui.onboarding.MIN_PROTEIN_GOAL
import app.mealsy.android.ui.onboarding.goalsSubmissionError
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.auth.SessionManager
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.domain.Goals
import dagger.hilt.android.lifecycle.HiltViewModel
import java.io.IOException
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
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
 * rationale as [goalsSubmissionError] in `OnboardingViewModel`.
 */
fun isDeleteConfirmed(typedText: String): Boolean = typedText == DELETE_CONFIRMATION_PHRASE

data class SettingsUiState(
    val goalsLoading: Boolean = true,
    val trackingMode: String = DEFAULT_TRACKING_MODE,
    val kcalGoal: Double = DEFAULT_KCAL_GOAL,
    val proteinGoal: Double = DEFAULT_PROTEIN_GOAL,
    val fiberGoal: Double = DEFAULT_FIBER_GOAL,
    val dietaryPrefs: Set<String> = emptySet(),
    val editingGoals: Boolean = false,
    val savingGoals: Boolean = false,
    val goalsError: String? = null,
    val reminderEnabled: Boolean = false,
    val versionName: String = "",
    val versionCode: Int = 0,
    val updateAvailable: Boolean = false,
    val deleteConfirmationText: String = "",
    val deletingAccount: Boolean = false,
    val deleteError: String? = null,
    val signedOut: Boolean = false,
)

/**
 * Drives [SettingsScreen]: goals edit (prefilled from [GoalsRepository.get],
 * saved via [GoalsRepository.update]), the daily-reminder toggle
 * ([PushRegistrar.ensureRegistered] / [PushRegistrar.unregisterCurrentDevice]),
 * the app-version nudge (`GET /meta/app`'s `latest_version_code`), sign out,
 * and account deletion.
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
    @AppVersionCode private val currentVersionCode: Int,
    @AppVersionName versionName: String,
) : ViewModel() {

    private val _uiState = MutableStateFlow(
        SettingsUiState(versionName = versionName, versionCode = currentVersionCode),
    )
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    init {
        loadGoals()
        loadReminderState()
        loadAppMeta()
    }

    private fun loadGoals() {
        viewModelScope.launch {
            _uiState.update { it.copy(goalsLoading = true, goalsError = null) }
            val goals = try {
                goalsRepository.get()
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                null
            }
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

    fun startEditingGoals() {
        _uiState.update { it.copy(editingGoals = true, goalsError = null) }
    }

    fun cancelEditingGoals() {
        _uiState.update { it.copy(editingGoals = false, goalsError = null) }
        loadGoals()
    }

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

    fun saveGoals() {
        val state = _uiState.value
        val goals = Goals(
            trackingMode = state.trackingMode,
            kcalGoal = state.kcalGoal,
            proteinGoal = state.proteinGoal,
            fiberGoal = state.fiberGoal,
            dietaryPrefs = state.dietaryPrefs.associateWith { true },
        )
        val validationError = goalsSubmissionError(goals)
        if (validationError != null) {
            _uiState.update { it.copy(goalsError = validationError) }
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(savingGoals = true, goalsError = null) }
            try {
                goalsRepository.update(goals)
                _uiState.update { it.copy(savingGoals = false, editingGoals = false) }
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                _uiState.update {
                    it.copy(savingGoals = false, goalsError = "Could not save your goals. Try again.")
                }
            }
        }
    }

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
}
