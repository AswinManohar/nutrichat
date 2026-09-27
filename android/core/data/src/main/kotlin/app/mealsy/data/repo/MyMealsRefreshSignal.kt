package app.mealsy.data.repo

import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Process-wide "the saved-meals list changed" fan-out — mirrors
 * [TodayRefreshSignal] but for `/my-meals` membership rather than today's
 * totals.
 *
 * A meal can be saved to My Meals from more than one place — the My Meals
 * screen isn't the only one that calls `POST /my-meals` — the chat confirm
 * card's "Add to My Meals" action does too, via
 * [app.mealsy.android.ui.chat.ChatSessionStore.onSaveAsMyMeal]. Android's
 * back-stack keeps the My Meals tab's `ViewModel` (and its last-loaded list)
 * alive across tab switches, so a save from chat would otherwise never be
 * reflected until the process restarts (#41). Rather than the chat store
 * reaching into the My Meals `ViewModel` directly, [MyMealsRepository]
 * calls [notifyChanged] after a successful save, and `MyMealsViewModel`
 * collects [events] to refetch. Deletes don't emit here — see
 * [MyMealsRepository.delete]'s doc comment.
 *
 * Plain `@Singleton class` with an `@Inject constructor` — Hilt can provide
 * this without a binding module since there is no interface to bind it to.
 */
@Singleton
class MyMealsRefreshSignal
    @Inject
    constructor() {
        private val _events =
            MutableSharedFlow<Unit>(
                replay = 0,
                extraBufferCapacity = 1,
                onBufferOverflow = BufferOverflow.DROP_OLDEST,
            )

        /** Emits once per successful save/delete; carries no payload, refetch is up to the collector. */
        val events: SharedFlow<Unit> = _events.asSharedFlow()

        /** Signals that the saved-meals list changed, so My Meals should refetch. */
        fun notifyChanged() {
            _events.tryEmit(Unit)
        }
    }
