package app.mealsy.android.ui.onboarding

import kotlinx.coroutines.flow.MutableStateFlow
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Tells the nav graph that a signed-out user's onboarding answers are held
 * in the current [OnboardingViewModel] and must not be thrown away (#31).
 *
 * When a session appears, `AppNav` normally replaces the back stack with a
 * fresh `onboarding?startStep=1` entry, which is a new ViewModel with an empty
 * SavedStateHandle. While [hold] is true it instead returns to the existing
 * onboarding entry, so the answers survive the sign-in round trip (including
 * the detour through the login screen for a magic link).
 */
@Singleton
class OnboardingAccountGate
    @Inject
    constructor() {
        val hold: MutableStateFlow<Boolean> = MutableStateFlow(false)
    }
