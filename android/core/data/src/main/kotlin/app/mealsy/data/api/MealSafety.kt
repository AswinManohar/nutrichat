package app.mealsy.data.api

import app.mealsy.domain.CardWarning
import kotlinx.serialization.json.Json
import retrofit2.HttpException

private val errorJson = Json { ignoreUnknownKeys = true }

/**
 * The warnings of a 409 `meal_needs_ack` from a meal save (spec 013 FR-044),
 * or null for any other HTTP error.
 */
fun HttpException.mealNeedsAckWarnings(): List<CardWarning>? {
    if (code() != 409) return null
    val body = response()?.errorBody()?.string() ?: return null
    val error = runCatching { errorJson.decodeFromString(MealNeedsAckError.serializer(), body) }.getOrNull()
    return error?.detail?.takeIf { it.code == "meal_needs_ack" }?.safety?.toWarnings()
}

/**
 * Nothing was saved: the meal hits an allergy or medication interaction and
 * the request did not say "Log anyway". Show [warnings] and offer it.
 */
class MealNeedsAckException(val warnings: List<CardWarning>) : Exception("meal needs Log anyway")
