package app.mealsy.domain

/**
 * A user's nutrition tracking configuration, mirroring the backend's
 * `GoalResponse` (`src/backend/api/goals.py`).
 *
 * `trackingMode` is `"goals"` or `"mindful"` (backend `Literal`). When it is
 * `"goals"`, the backend requires [kcalGoal], [proteinGoal] and [fiberGoal]
 * to be non-null (`GoalCreate`/`GoalUpdate` validators) — the client must
 * supply all three whenever it posts `trackingMode == "goals"`.
 *
 * [dietaryPrefs] mirrors the backend's free-form `dietary_prefs: dict` as a
 * name -> selected map (e.g. `{"vegetarian": true}`) rather than a typed
 * enum, since the backend imposes no fixed vocabulary on it.
 *
 * [firstMealTime] and [streakDays] are read-only, backend-computed fields —
 * never sent back on create/update (see `GoalCreate`/`GoalUpdate`, which
 * don't accept `streak_days`, and only optionally accept `first_meal_time`).
 */
data class Goals(
    val trackingMode: String,
    val kcalGoal: Double?,
    val proteinGoal: Double?,
    val fiberGoal: Double?,
    val dietaryPrefs: Map<String, Boolean> = emptyMap(),
    val firstMealTime: String? = null,
    val streakDays: Int = 0,
)
