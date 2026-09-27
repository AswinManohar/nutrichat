package app.mealsy.android.ui.onboarding

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/**
 * Covers [buildCoachNoteText] (step-4 coach note) for every [DietaryPref]
 * value plus the no-prefs default and the `_more` variant (#30 — the note
 * used to say the opposite of what the user picked, e.g. "I'll steer
 * around vegetarian").
 */
class OnboardingCoachNoteCopyTest {
    // Mirrors R.string.onboarding_target_coach_note_prefs /
    // _prefs_more / _default in app/src/main/res/values/strings.xml.
    private val defaultText = "I’ll suggest a mix of whole foods and keep portions realistic."
    private val template = "Noted — I’ll keep suggestions %1\$s."
    private val templateMore = "Noted — I’ll keep suggestions %1\$s and more."

    private fun labelFor(pref: DietaryPref): String =
        when (pref) {
            DietaryPref.Vegetarian -> "Vegetarian"
            DietaryPref.Vegan -> "Vegan"
            DietaryPref.Pescatarian -> "Pescatarian"
            DietaryPref.NoDairy -> "No dairy"
            DietaryPref.NoGluten -> "No gluten"
            DietaryPref.LowSodium -> "Low sodium"
            DietaryPref.LowSugar -> "Low sugar"
            DietaryPref.NoNuts -> "No nuts"
        }

    @Test
    fun noPrefs_usesDefaultText() {
        val result =
            buildCoachNoteText(
                prefLabels = emptyList(),
                hasMorePrefs = false,
                defaultText = defaultText,
                prefsTemplate = template,
                prefsMoreTemplate = templateMore,
            )
        assertEquals(defaultText, result)
    }

    @Test
    fun everyDietaryPref_readsAsKeepingTheChosenPreference() {
        for (pref in DietaryPref.entries) {
            val result =
                buildCoachNoteText(
                    prefLabels = listOf(labelFor(pref)),
                    hasMorePrefs = false,
                    defaultText = defaultText,
                    prefsTemplate = template,
                    prefsMoreTemplate = templateMore,
                )
            val expected = "Noted — I’ll keep suggestions ${labelFor(pref).lowercase()}."
            assertEquals("copy for $pref", expected, result)
            // Regression guard for #30: must never read as avoiding the
            // chosen preference.
            assertFalse("copy for $pref must not say 'steer around'", result.contains("steer around"))
        }
    }

    @Test
    fun twoPrefs_joinsWithAnd() {
        val result =
            buildCoachNoteText(
                prefLabels = listOf(labelFor(DietaryPref.Vegetarian), labelFor(DietaryPref.NoNuts)),
                hasMorePrefs = false,
                defaultText = defaultText,
                prefsTemplate = template,
                prefsMoreTemplate = templateMore,
            )
        assertEquals("Noted — I’ll keep suggestions vegetarian and no nuts.", result)
    }

    @Test
    fun moreThanTwoPrefs_usesMoreVariant() {
        val result =
            buildCoachNoteText(
                prefLabels = listOf(labelFor(DietaryPref.Vegetarian), labelFor(DietaryPref.NoNuts)),
                hasMorePrefs = true,
                defaultText = defaultText,
                prefsTemplate = template,
                prefsMoreTemplate = templateMore,
            )
        assertEquals("Noted — I’ll keep suggestions vegetarian and no nuts and more.", result)
    }
}
