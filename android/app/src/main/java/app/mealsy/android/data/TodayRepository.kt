package app.mealsy.android.data

import app.mealsy.android.di.ApplicationScope
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TodayResponse
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.domain.Goals
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import javax.inject.Inject
import javax.inject.Singleton

/** `GET /meals/today` and `GET /goals`, fetched together for [app.mealsy.android.ui.home.HomeScreen]. */
data class TodaySnapshot(val today: TodayResponse, val goals: Goals?)

/**
 * Fetches [TodaySnapshot] (today's totals + the active goal) with in-flight
 * request coalescing, so concurrent callers share one network round trip
 * instead of each firing their own `GET /goals` + `GET /meals/today`.
 *
 * #49 item 4: `HomeScreen`'s `DisposableEffect` synthesizes an `ON_RESUME`
 * event the instant it's registered (the lifecycle is already `RESUMED` when
 * `HomeScreen` first composes), which used to fire a second, fully redundant
 * load a few milliseconds after [app.mealsy.android.ui.home.HomeViewModel]'s
 * own `init { load() }` — measured on the wire as two back-to-back
 * `/goals + /meals/today` pairs. Routing both calls through this
 * `@Singleton` means the second one joins the first's still-in-flight
 * [Deferred] rather than starting a new request.
 *
 * This is deliberately *not* a persistent cache: once a fetch completes,
 * [inFlight] is cleared, so a later distinct call (pull-to-refresh, or a
 * [app.mealsy.data.repo.TodayRefreshSignal] event after logging a meal)
 * always gets fresh data rather than serving something stale forever.
 *
 * Uses [ApplicationScope] (like
 * [app.mealsy.android.ui.chat.ChatSessionStore]) rather than any one
 * caller's `viewModelScope`, so an in-flight fetch isn't cancelled just
 * because the `ViewModel` that started it is torn down before it joins.
 */
@Singleton
class TodayRepository
    @Inject
    constructor(
        private val api: MealsyApi,
        private val goalsRepository: GoalsRepository,
        @ApplicationScope private val scope: CoroutineScope,
    ) {
        private val mutex = Mutex()
        private var inFlight: Deferred<TodaySnapshot>? = null

        private val _state = MutableStateFlow<TodaySnapshot?>(null)

        /** The most recently completed fetch's result, or null before the first one lands. */
        val state: StateFlow<TodaySnapshot?> = _state.asStateFlow()

        /**
         * Returns the latest [TodaySnapshot], fetching fresh data. A call that
         * overlaps an already-running fetch joins it instead of starting a
         * second one — see the class doc.
         */
        suspend fun get(): TodaySnapshot {
            val deferred =
                mutex.withLock {
                    inFlight ?: scope.async { fetch() }.also { started ->
                        inFlight = started
                        started.invokeOnCompletion {
                            // Only this fetch's own completion should clear the slot — a
                            // later, distinct fetch may already be `inFlight` by the time
                            // this callback runs.
                            if (inFlight === started) inFlight = null
                        }
                    }
                }
            val result = deferred.await()
            _state.value = result
            return result
        }

        private suspend fun fetch(): TodaySnapshot =
            coroutineScope {
                val todayDeferred = async { api.today() }
                val goalsDeferred = async { goalsRepository.get() }
                TodaySnapshot(todayDeferred.await(), goalsDeferred.await())
            }
    }
