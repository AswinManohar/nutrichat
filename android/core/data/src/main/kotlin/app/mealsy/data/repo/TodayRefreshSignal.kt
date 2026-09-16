package app.mealsy.data.repo

import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/**
 * Process-wide "today's totals changed" fan-out.
 *
 * A meal can be logged from more than one place — chat's confirm-card flow,
 * a direct chat log, or a quick-log from My Meals — and any of those should
 * cause the Home dashboard (and any other today-derived screen) to refetch
 * `/meals/today`. Rather than each screen polling or each repository
 * reaching into Home's view model directly, callers that persist a meal
 * call [notifyLogged] and interested screens collect [events].
 *
 * Plain `@Singleton class` with an `@Inject constructor` — Hilt can provide
 * this without a binding module since there is no interface to bind it to.
 */
@Singleton
class TodayRefreshSignal @Inject constructor() {
    private val _events = MutableSharedFlow<Unit>(
        replay = 0,
        extraBufferCapacity = 1,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )

    /** Emits once per successful meal log; carries no payload, refetch is up to the collector. */
    val events: SharedFlow<Unit> = _events.asSharedFlow()

    /** Signals that a meal was logged, so today-derived screens should refetch. */
    fun notifyLogged() {
        _events.tryEmit(Unit)
    }
}
