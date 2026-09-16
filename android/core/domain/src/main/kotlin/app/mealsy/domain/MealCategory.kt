package app.mealsy.domain

import java.time.Clock
import java.time.LocalTime

/**
 * Pre-selects a meal type from the local clock, matching the backend's
 * `meal_type` vocabulary (`breakfast` / `lunch` / `dinner` / `snack`).
 *
 * Boundaries: before 10:30 -> `breakfast`, before 15:00 -> `lunch`, before
 * 20:00 -> `dinner`, otherwise `snack`. This intentionally diverges from the
 * web client's `defaultMealCategory` (`frontend/src/components/chat/meal-categories.ts`),
 * which also has a `brunch` bucket — the Android client's `meal_type`
 * vocabulary has no `brunch`, so this is the binding rule for Android per
 * the T1 build brief.
 */
fun defaultMealCategory(now: LocalTime): String = when {
    now.isBefore(LocalTime.of(10, 30)) -> "breakfast"
    now.isBefore(LocalTime.of(15, 0)) -> "lunch"
    now.isBefore(LocalTime.of(20, 0)) -> "dinner"
    else -> "snack"
}

/**
 * Convenience overload of [defaultMealCategory] that reads the current local
 * time from [clock] (defaulting to the device's real clock in its default
 * time zone).
 */
fun defaultMealCategory(clock: Clock = Clock.systemDefaultZone()): String =
    defaultMealCategory(LocalTime.now(clock))
