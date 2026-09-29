package app.mealsy.android.ui.onboarding

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.Modifier
import app.mealsy.android.ui.AppScreenshotTestBase
import org.junit.Test

/**
 * Goldens for the six designed onboarding states, light and dark.
 * [OnboardingContent] is rendered directly with hand-built
 * [OnboardingUiState] values and `animate = false` for deterministic
 * frames — no progress-bar animation, no Olli bob.
 */
class OnboardingScreenGoldenTest : AppScreenshotTestBase() {
    private fun state(
        step: Int,
        startStep: Int = 0,
        name: String = "",
        goal: OnboardingGoal? = null,
        prefs: Set<DietaryPref> = emptySet(),
        kcalTarget: Int = 2200,
        saving: Boolean = false,
        error: Boolean = false,
    ): OnboardingUiState {
        val firstName = name.trim().substringBefore(' ')
        val orderedSelected = DietaryPref.entries.filter { it in prefs }
        val continueEnabled =
            when (step) {
                1 -> name.isNotBlank()
                2 -> goal != null
                else -> true
            }
        val continueLabel =
            when (step) {
                4 -> ContinueLabel.Finish
                3 -> if (prefs.isEmpty()) ContinueLabel.NothingToAvoid else ContinueLabel.Continue
                else -> ContinueLabel.Continue
            }
        return OnboardingUiState(
            step = step,
            startStep = startStep,
            name = name,
            firstName = firstName,
            goal = goal,
            prefs = prefs,
            kcalTarget = kcalTarget,
            continueEnabled = continueEnabled,
            continueLabel = continueLabel,
            progress = step / 4f,
            isMindful = goal == OnboardingGoal.Learn,
            coachNotePrefs = orderedSelected.take(2),
            hasMorePrefs = orderedSelected.size > 2,
            saving = saving,
            error = error,
            done = false,
        )
    }

    @androidx.compose.runtime.Composable
    private fun render(state: OnboardingUiState) {
        OnboardingContent(
            state = state,
            onName = {},
            onSelectGoal = {},
            onTogglePref = {},
            onKcalTarget = {},
            onNext = {},
            onBack = {},
            onRetry = {},
            onNavigateToLogin = {},
            modifier = Modifier.fillMaxSize(),
            animate = false,
        )
    }

    // --- Step 6: Save your plan (signed-out account step, #31) ------------

    @Test
    fun step6Account_light() =
        captureMealsy("Onboarding_step6Account", false) {
            render(state(step = ACCOUNT_STEP, name = "Alex", goal = OnboardingGoal.Maintain))
        }

    @Test
    fun step6Account_dark() =
        captureMealsy("Onboarding_step6Account", true) {
            render(state(step = ACCOUNT_STEP, name = "Alex", goal = OnboardingGoal.Maintain))
        }

    @Test
    fun step6Account_light_fontScale200() =
        captureMealsy("Onboarding_step6Account", false, 2.0f) {
            render(state(step = ACCOUNT_STEP, name = "Alex", goal = OnboardingGoal.Maintain))
        }

    // --- Step 0: Welcome -----------------------------------------------

    @Test
    fun step0Welcome_light() = captureMealsy("Onboarding_step0Welcome", false) { render(state(step = 0)) }

    @Test
    fun step0Welcome_dark() = captureMealsy("Onboarding_step0Welcome", true) { render(state(step = 0)) }

    @Test
    fun step0Welcome_light_fontScale130() = captureMealsy("Onboarding_step0Welcome", false, 1.3f) { render(state(step = 0)) }

    @Test
    fun step0Welcome_light_fontScale200() = captureMealsy("Onboarding_step0Welcome", false, 2.0f) { render(state(step = 0)) }

    // --- Step 1: Name (empty, Continue disabled) ------------------------

    @Test
    fun step1Name_light() = captureMealsy("Onboarding_step1Name", false) { render(state(step = 1)) }

    @Test
    fun step1Name_dark() = captureMealsy("Onboarding_step1Name", true) { render(state(step = 1)) }

    // --- Step 2: Goal (Maintain selected) --------------------------------

    @Test
    fun step2Goal_light() =
        captureMealsy("Onboarding_step2Goal", false) {
            render(state(step = 2, name = "Alex", goal = OnboardingGoal.Maintain))
        }

    @Test
    fun step2Goal_dark() =
        captureMealsy("Onboarding_step2Goal", true) {
            render(state(step = 2, name = "Alex", goal = OnboardingGoal.Maintain))
        }

    // A long, hyphenated, near-cap-length name at 2x font — regression
    // coverage for #46 (heading "?" must never strand on its own line).
    @Test
    fun step2Goal_light_longHyphenatedName_fontScale200() =
        captureMealsy("Onboarding_step2Goal_longName", false, 2.0f) {
            render(state(step = 2, name = "Anne-Marie-Louise", goal = OnboardingGoal.Maintain))
        }

    // --- Step 3: Preferences (two selected) -------------------------------

    @Test
    fun step3Prefs_light() =
        captureMealsy("Onboarding_step3Prefs", false) {
            render(state(step = 3, goal = OnboardingGoal.Maintain, prefs = setOf(DietaryPref.Vegetarian, DietaryPref.NoNuts)))
        }

    @Test
    fun step3Prefs_dark() =
        captureMealsy("Onboarding_step3Prefs", true) {
            render(state(step = 3, goal = OnboardingGoal.Maintain, prefs = setOf(DietaryPref.Vegetarian, DietaryPref.NoNuts)))
        }

    // --- Step 4: Target (Maintain, 2200) ----------------------------------

    @Test
    fun step4Target_light() =
        captureMealsy("Onboarding_step4Target", false) {
            render(state(step = 4, goal = OnboardingGoal.Maintain, kcalTarget = 2200))
        }

    @Test
    fun step4Target_dark() =
        captureMealsy("Onboarding_step4Target", true) {
            render(state(step = 4, goal = OnboardingGoal.Maintain, kcalTarget = 2200))
        }

    // --- Step 4: Target, mindful variant -----------------------------------

    @Test
    fun step4TargetMindful_light() =
        captureMealsy("Onboarding_step4TargetMindful", false) {
            render(state(step = 4, goal = OnboardingGoal.Learn, kcalTarget = 2200))
        }

    @Test
    fun step4TargetMindful_dark() =
        captureMealsy("Onboarding_step4TargetMindful", true) {
            render(state(step = 4, goal = OnboardingGoal.Learn, kcalTarget = 2200))
        }

    // --- Step 5: Done ------------------------------------------------------

    @Test
    fun step5Done_light() =
        captureMealsy("Onboarding_step5Done", false) {
            render(state(step = 5, name = "Alex", goal = OnboardingGoal.Maintain, kcalTarget = 2200))
        }

    @Test
    fun step5Done_dark() =
        captureMealsy("Onboarding_step5Done", true) {
            render(state(step = 5, name = "Alex", goal = OnboardingGoal.Maintain, kcalTarget = 2200))
        }
}
