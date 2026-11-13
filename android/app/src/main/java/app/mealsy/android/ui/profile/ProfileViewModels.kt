package app.mealsy.android.ui.profile

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.data.api.HardEntryDto
import app.mealsy.data.api.ProfileMealsDto
import app.mealsy.data.api.SoftFactDto
import app.mealsy.data.repo.ProfileRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

/** Every hard entry, retired ones included, newest first (`GET /profile/history`). */
@HiltViewModel
class EntryHistoryViewModel
    @Inject
    constructor(
        private val repository: ProfileRepository,
    ) : ViewModel() {
        private val _state = MutableStateFlow<LoadState<List<HardEntryDto>>>(LoadState.Loading)
        val state: StateFlow<LoadState<List<HardEntryDto>>> = _state.asStateFlow()

        /** Exposed so tests can join the initial load. */
        val readyJob: Job = load()

        fun load(): Job {
            _state.value = LoadState.Loading
            return viewModelScope.launch { _state.value = loadState { repository.history() } }
        }
    }

/** The last 21 days of recommendations and logged meal labels (`GET /profile/meals`). */
@HiltViewModel
class MealHistoryViewModel
    @Inject
    constructor(
        private val repository: ProfileRepository,
    ) : ViewModel() {
        private val _state = MutableStateFlow<LoadState<ProfileMealsDto>>(LoadState.Loading)
        val state: StateFlow<LoadState<ProfileMealsDto>> = _state.asStateFlow()

        val readyJob: Job = load()

        fun load(): Job {
            _state.value = LoadState.Loading
            return viewModelScope.launch { _state.value = loadState { repository.meals() } }
        }
    }

/** The soft preferences Mealsy remembers, with edit and delete. */
@HiltViewModel
class PreferencesViewModel
    @Inject
    constructor(
        private val repository: ProfileRepository,
    ) : ViewModel() {
        private val _state = MutableStateFlow<LoadState<List<SoftFactDto>>>(LoadState.Loading)
        val state: StateFlow<LoadState<List<SoftFactDto>>> = _state.asStateFlow()

        private val _save = MutableStateFlow(CareSaveState())
        val save: StateFlow<CareSaveState> = _save.asStateFlow()

        val readyJob: Job = load()

        fun load(): Job {
            if (_state.value !is LoadState.Loaded) _state.value = LoadState.Loading
            return viewModelScope.launch { _state.value = loadState { repository.profile().soft } }
        }

        /** Saves new [text] and [kind] for [id]; [onDone] runs on success. */
        fun edit(
            id: String,
            text: String,
            kind: String,
            onDone: () -> Unit,
        ) = mutate(onDone) { repository.editSoftFact(id, text, kind) }

        /** Deletes [id] after the patient confirmed; the server remembers not to re-learn it. */
        fun delete(
            id: String,
            onDone: () -> Unit,
        ) = mutate(onDone) { repository.deleteSoftFact(id) }

        fun clearSaveError() {
            _save.value = CareSaveState()
        }

        private fun mutate(
            onDone: () -> Unit,
            call: suspend () -> Unit,
        ): Job? {
            if (_save.value.saving) return null
            _save.value = CareSaveState(saving = true)
            return viewModelScope.launch {
                try {
                    call()
                    _save.value = CareSaveState()
                    onDone()
                    load().join()
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: Exception) {
                    _save.value = CareSaveState(failed = true)
                }
            }
        }
    }

/** State of the "Export my data" action. */
enum class ExportState { Idle, Preparing, Failed }

/** Fetches the full JSON export (`GET /profile/export`) for the share sheet. */
@HiltViewModel
class ProfileExportViewModel
    @Inject
    constructor(
        private val repository: ProfileRepository,
    ) : ViewModel() {
        private val _state = MutableStateFlow(ExportState.Idle)
        val state: StateFlow<ExportState> = _state.asStateFlow()

        /** Loads the export and hands the JSON text to [onReady]. */
        fun export(onReady: (String) -> Unit): Job? {
            if (_state.value == ExportState.Preparing) return null
            _state.value = ExportState.Preparing
            return viewModelScope.launch {
                try {
                    val json = repository.export()
                    _state.value = ExportState.Idle
                    onReady(json)
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: Exception) {
                    _state.value = ExportState.Failed
                }
            }
        }
    }
