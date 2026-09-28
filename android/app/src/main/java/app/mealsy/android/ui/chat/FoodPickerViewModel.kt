package app.mealsy.android.ui.chat

import app.mealsy.android.util.ConnectivityObserver
import app.mealsy.data.repo.FoodRepository
import app.mealsy.data.repo.FoodSearchHit
import app.mealsy.data.repo.FoodSearchOutcome
import app.mealsy.domain.CandidateDetail
import app.mealsy.domain.CardItem
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.mapLatest
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

/** How long to wait after the user stops typing before searching (contracts/android-picker-ui.md). */
private const val SEARCH_DEBOUNCE_MS = 250L

/** Minimum trimmed query length that triggers a search. */
private const val MIN_QUERY_LENGTH = 2

/** The `GET /foods/search` preview `limit`. */
private const val SEARCH_LIMIT = 10

/** The picker's search-results section state. */
sealed interface SearchState {
    data object Idle : SearchState

    data object Loading : SearchState

    data class Loaded(val hits: List<FoodSearchHit>) : SearchState

    data object Empty : SearchState

    /** Covers both a 503 and a network/timeout failure — contract's "Can't search right now". */
    data object Unavailable : SearchState
}

/** One-shot events the host (ConfirmCardView) reacts to. */
sealed interface FoodPickerEvent {
    data class SwapReady(val item: CardItem, val method: String, val query: String?) : FoodPickerEvent

    data object SwapFailed : FoodPickerEvent
}

/**
 * Drives the "Not the right food?" picker sheet for one confirm-card item
 * (spec 003, T028): debounced search, offline gating, and resolving a
 * chosen suggestion/result into a ready-to-swap [CardItem] via
 * [FoodRepository.getFood].
 *
 * Not a `@HiltViewModel` — it is scoped to one open sheet (one item), not a
 * nav-graph entry, so it is created per-open via [Factory] and given an
 * external [CoroutineScope] the caller owns (mirrors how [ChatSessionStore]
 * is app-scoped rather than `viewModelScope`-scoped, just narrower here).
 *
 * @param currentFdcId The item's currently matched fdc id, used to mark the
 *   current match among suggestions/results (US2) and to no-op a tap on it.
 * @param initialQuery The search field's initial value — the item's
 *   [CardItem.inputPhrase] if set, else its [CardItem.foodName].
 * @param previewQtyG What the user currently sees on the card —
 *   `targetQtyG × portion` — used only to preview search/suggestion rows'
 *   kcal and protein (contracts/android-picker-ui.md, U2).
 * @param baseQtyG The item's existing **base** `qtyG` (never the edited
 *   `targetQtyG`). Sent as `GET /foods/{fdc_id}?qty_g=` on [select] so the
 *   picked item's own `targetQtyG`/portion keep governing the display —
 *   passing the edited/target quantity here would double-scale (U2).
 * @param candidateDetails The item's [CardItem.candidateDetails], scaled by
 *   [suggestions] to [previewQtyG] for the sheet's Suggestions section
 *   (spec 003, US2). Empty when the backend sent none.
 */
@OptIn(ExperimentalCoroutinesApi::class, FlowPreview::class)
class FoodPickerViewModel(
    private val repository: FoodRepository,
    connectivityObserver: ConnectivityObserver,
    private val scope: CoroutineScope,
    val currentFdcId: Long,
    initialQuery: String,
    private val previewQtyG: Double,
    private val baseQtyG: Double,
    candidateDetails: List<CandidateDetail> = emptyList(),
) {
    private val _query = MutableStateFlow(initialQuery)
    val query: StateFlow<String> = _query.asStateFlow()

    /**
     * [candidateDetails] previewed at [previewQtyG] — what the user
     * currently sees on the card, matching the Results section's scaling
     * (contracts/android-picker-ui.md "Suggestions"). Empty hides the
     * sheet's Suggestions section entirely.
     */
    val suggestions: List<FoodSearchHit> =
        candidateDetails.map { detail ->
            val scale = previewQtyG / 100.0
            FoodSearchHit(
                fdcId = detail.fdcId,
                name = detail.name,
                dataType = detail.dataType,
                kcalPer100g = detail.kcalPer100g,
                proteinGPer100g = detail.proteinGPer100g,
                kcal = detail.kcalPer100g * scale,
                proteinG = detail.proteinGPer100g * scale,
            )
        }

    val isOnline: StateFlow<Boolean> =
        connectivityObserver.isOnline.stateIn(scope, SharingStarted.Eagerly, true)

    private val _searchState = MutableStateFlow<SearchState>(SearchState.Idle)
    val searchState: StateFlow<SearchState> = _searchState.asStateFlow()

    private val _selecting = MutableStateFlow(false)
    val selecting: StateFlow<Boolean> = _selecting.asStateFlow()

    private val events = Channel<FoodPickerEvent>(Channel.BUFFERED)
    val eventsFlow: Flow<FoodPickerEvent> = events.receiveAsFlow()

    init {
        combine(_query.debounce(SEARCH_DEBOUNCE_MS).distinctUntilChanged(), isOnline) { q, online ->
            q to online
        }
            .mapLatest { (q, online) -> runSearch(q, online) }
            .onEach { _searchState.value = it }
            .launchIn(scope)
    }

    /** Updates the search field's value; the debounced search flow above reacts to it. */
    fun onQueryChange(newQuery: String) {
        _query.value = newQuery
    }

    private suspend fun runSearch(
        q: String,
        online: Boolean,
    ): SearchState {
        val trimmed = q.trim()
        if (!online) return SearchState.Idle
        if (trimmed.length < MIN_QUERY_LENGTH) return SearchState.Idle
        _searchState.value = SearchState.Loading
        return when (val outcome = repository.search(trimmed, previewQtyG, SEARCH_LIMIT)) {
            is FoodSearchOutcome.Results -> SearchState.Loaded(outcome.hits)
            FoodSearchOutcome.Empty -> SearchState.Empty
            FoodSearchOutcome.Unavailable, FoodSearchOutcome.Error -> SearchState.Unavailable
        }
    }

    /**
     * Resolves [fdcId] into a ready-to-log item and emits [FoodPickerEvent.SwapReady],
     * or [FoodPickerEvent.SwapFailed] if the lookup fails. A no-op (no event
     * emitted, [selecting] never flips) when [fdcId] is already [currentFdcId] —
     * the host closes the sheet itself for that case (contract: "Tap the
     * current match: No-op, closes the sheet, no toast").
     */
    fun select(
        fdcId: Long,
        method: String,
        query: String? = null,
    ) {
        if (fdcId == currentFdcId) return
        scope.launch {
            _selecting.value = true
            try {
                val item = repository.getFood(fdcId, baseQtyG)
                events.send(FoodPickerEvent.SwapReady(item, method, query))
            } catch (exc: Exception) {
                if (exc is kotlinx.coroutines.CancellationException) throw exc
                events.send(FoodPickerEvent.SwapFailed)
            } finally {
                _selecting.value = false
            }
        }
    }

    /** Hilt-injected factory: builds one [FoodPickerViewModel] per opened sheet. */
    class Factory
        @Inject
        constructor(
            private val repository: FoodRepository,
            private val connectivityObserver: ConnectivityObserver,
        ) {
            fun create(
                scope: CoroutineScope,
                currentFdcId: Long,
                initialQuery: String,
                previewQtyG: Double,
                baseQtyG: Double,
                candidateDetails: List<CandidateDetail> = emptyList(),
            ): FoodPickerViewModel =
                FoodPickerViewModel(
                    repository = repository,
                    connectivityObserver = connectivityObserver,
                    scope = scope,
                    currentFdcId = currentFdcId,
                    initialQuery = initialQuery,
                    previewQtyG = previewQtyG,
                    baseQtyG = baseQtyG,
                    candidateDetails = candidateDetails,
                )
        }
}

/**
 * Exposes [FoodPickerViewModel.Factory] to plain `@Composable`s that aren't
 * themselves a `hiltViewModel()` — [ConfirmCardView] opens the picker sheet
 * from deep inside a message list, not from a nav-graph entry point, so it
 * reaches Hilt via [EntryPointAccessors.fromApplication] instead of normal
 * constructor injection.
 */
@EntryPoint
@InstallIn(SingletonComponent::class)
interface FoodPickerEntryPoint {
    fun foodPickerViewModelFactory(): FoodPickerViewModel.Factory
}

/** Convenience accessor for [FoodPickerEntryPoint] from a [android.content.Context]. */
fun foodPickerViewModelFactory(context: android.content.Context): FoodPickerViewModel.Factory =
    EntryPointAccessors.fromApplication(context, FoodPickerEntryPoint::class.java).foodPickerViewModelFactory()
