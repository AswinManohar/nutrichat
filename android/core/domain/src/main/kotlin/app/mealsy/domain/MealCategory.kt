package app.mealsy.domain

import java.time.Clock
import java.time.LocalTime

/**
 * Pre-selects a meal type from the local clock, matching the backend's
 * `meal_type` vocabulary (`breakfast` / `lunch` / `dinner` / `snack`).
 *
 * Boundaries mirror the web client's `defaultMealCategory`
 * (`frontend/src/components/chat/meal-categories.ts`), with its `brunch`
 * hour (11:00-11:59) folded into `lunch` since the Android client's
 * `meal_type` vocabulary has no `brunch`:
 * `[05:00, 11:00)` -> `breakfast`, `[11:00, 15:00)` -> `lunch`,
 * `[15:00, 17:00)` -> `snack`, `[17:00, 22:00)` -> `dinner`, otherwise
 * (`[22:00, 24:00)` and `[00:00, 05:00)`) -> `snack`.
 */
fun defaultMealCategory(now: LocalTime): String =
    when {
        now.isBefore(LocalTime.of(5, 0)) -> "snack"
        now.isBefore(LocalTime.of(11, 0)) -> "breakfast"
        now.isBefore(LocalTime.of(15, 0)) -> "lunch"
        now.isBefore(LocalTime.of(17, 0)) -> "snack"
        now.isBefore(LocalTime.of(22, 0)) -> "dinner"
        else -> "snack"
    }

/**
 * Convenience overload of [defaultMealCategory] that reads the current local
 * time from [clock] (defaulting to the device's real clock in its default
 * time zone).
 */
fun defaultMealCategory(clock: Clock = Clock.systemDefaultZone()): String = defaultMealCategory(LocalTime.now(clock))
