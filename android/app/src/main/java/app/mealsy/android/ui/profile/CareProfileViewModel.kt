package app.mealsy.android.ui.profile

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.android.ui.common.ErrorKind
import app.mealsy.data.api.CareTeamMemberDto
import app.mealsy.data.api.HardEntryDto
import app.mealsy.data.api.LimitsTodayDto
import app.mealsy.data.repo.ProfileRepository
import app.mealsy.data.repo.ProfileUnavailableException
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import java.io.IOException
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import javax.inject.Inject

/** The kinds of hard entry, in display order, with their wire `type`. */
enum class CareType(val wire: String) {
    Allergy("allergy"),
    Diagnosis("diagnosis"),
    Medication("medication"),
    PhysicalLimitation("physical_limitation"),
    NutrientLimit("nutrient_limit"),
    DietSetting("diet_setting"),
    FoodExclusion("food_exclusion"),
}

/** What the Care profile screens render once loaded. */
data class CareProfileData(
    val entries: List<HardEntryDto>,
    val careTeam: List<CareTeamMemberDto> = emptyList(),
    val limits: LimitsTodayDto? = null,
    val updatedOn: LocalDate? = null,
) {
    fun of(type: CareType): List<HardEntryDto> = entries.filter { it.type == type.wire }
}

/** Rendering state for the Care profile card and screen. */
sealed interface CareProfileUiState {
    data object Loading : CareProfileUiState

    /** [message] is the server's text for a 503, otherwise null and [kind] picks the copy. */
    data class Error(val kind: ErrorKind, val message: String? = null) : CareProfileUiState

    data class Loaded(val data: CareProfileData) : CareProfileUiState
}

/** State of an add, edit or retire in flight. */
data class CareSaveState(val saving: Boolean = false, val failed: Boolean = false)

/**
 * Loads the patient profile and today's limit progress, and applies add, edit and
 * retire. Scoped to the Profile tab's back stack entry so the tab's card and the
 * Care profile screen share one instance and stay in step.
 */
@HiltViewModel
class CareProfileViewModel
    @Inject
    constructor(
        private val repository: ProfileRepository,
    ) : ViewModel() {
        private val _uiState = MutableStateFlow<CareProfileUiState>(CareProfileUiState.Loading)
        val uiState: StateFlow<CareProfileUiState> = _uiState.asStateFlow()

        private val _save = MutableStateFlow(CareSaveState())
        val save: StateFlow<CareSaveState> = _save.asStateFlow()

        /** Exposed so tests can join the initial load. */
        val readyJob: Job = load()

        /** (Re)loads the profile; limits are optional, so their failure only hides the banner and bars. */
        fun load(): Job {
            if (_uiState.value !is CareProfileUiState.Loaded) _uiState.value = CareProfileUiState.Loading
            return viewModelScope.launch {
                try {
                    val (profile, limits) =
                        coroutineScope {
                            val limits = async { runCatching { repository.limitsToday() }.getOrNull() }
                            repository.profile() to limits.await()
                        }
                    _uiState.value =
                        CareProfileUiState.Loaded(
                            CareProfileData(
                                entries = profile.hard,
                                careTeam = profile.careTeam,
                                limits = limits,
                                updatedOn = latestChange(profile.hard),
                            ),
                        )
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: ProfileUnavailableException) {
                    _uiState.value = CareProfileUiState.Error(ErrorKind.LoadFailed, exc.message?.ifBlank { null })
                } catch (exc: IOException) {
                    _uiState.value = CareProfileUiState.Error(ErrorKind.Offline)
                } catch (exc: Exception) {
                    _uiState.value = CareProfileUiState.Error(ErrorKind.LoadFailed)
                }
            }
        }

        /**
         * Adds an entry, or edits [replacesId]. [clientRequestId] stays the same across retries of
         * one sheet so the server de-duplicates. [onDone] runs on success.
         */
        fun saveEntry(
            type: CareType,
            value: JsonObject,
            replacesId: String?,
            clientRequestId: String,
            onDone: () -> Unit,
        ) = mutate(onDone) { repository.saveEntry(type.wire, value, null, clientRequestId, replacesId) }

        /** Retires [id] after the patient confirmed in the dialog. */
        fun retire(
            id: String,
            clientRequestId: String,
            onDone: () -> Unit,
        ) = mutate(onDone) { repository.retire(id, clientRequestId) }

        /** Clears a shown save failure when the sheet is dismissed. */
        fun clearSaveError() {
            _save.value = CareSaveState()
        }

        private fun mutate(
            onDone: () -> Unit,
            call: suspend () -> Unit,
        ) {
            if (_save.value.saving) return
            _save.value = CareSaveState(saving = true)
            viewModelScope.launch {
                try {
                    call()
                    _save.value = CareSaveState()
                    onDone()
                    load()
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: Exception) {
                    _save.value = CareSaveState(failed = true)
                }
            }
        }
    }

/** The most recent created or confirmed date among live entries, in the device time zone. */
internal fun latestChange(entries: List<HardEntryDto>): LocalDate? =
    entries
        .flatMap { listOfNotNull(it.createdAt, it.confirmedAt) }
        .mapNotNull { runCatching { OffsetDateTime.parse(it) }.getOrNull() }
        .maxOrNull()
        ?.atZoneSameInstant(ZoneId.systemDefault())
        ?.toLocalDate()
