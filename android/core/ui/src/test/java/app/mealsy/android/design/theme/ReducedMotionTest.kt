package app.mealsy.android.design.theme

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Plain JVM coverage for [isReducedMotion]; no Robolectric needed. */
class ReducedMotionTest {

    @Test
    fun bothScalesNormal_isNotReduced() {
        assertFalse(isReducedMotion(animatorScale = 1f, transitionScale = 1f))
    }

    @Test
    fun animatorScaleZero_isReduced() {
        assertTrue(isReducedMotion(animatorScale = 0f, transitionScale = 1f))
    }

    @Test
    fun transitionScaleZero_isReduced() {
        assertTrue(isReducedMotion(animatorScale = 1f, transitionScale = 0f))
    }

    @Test
    fun bothScalesZero_isReduced() {
        assertTrue(isReducedMotion(animatorScale = 0f, transitionScale = 0f))
    }
}
