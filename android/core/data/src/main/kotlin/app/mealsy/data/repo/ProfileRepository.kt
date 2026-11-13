package app.mealsy.data.repo

import app.mealsy.data.api.EntryRequest
import app.mealsy.data.api.HardEntryDto
import app.mealsy.data.api.LimitsTodayDto
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.ProfileDto
import app.mealsy.data.api.ProfileMealsDto
import app.mealsy.data.api.RetireRequest
import app.mealsy.data.api.SoftFactDto
import app.mealsy.data.api.SoftFactPatch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import retrofit2.HttpException
import javax.inject.Inject

/**
 * The server could not load the patient profile (HTTP 503). [message] is the
 * server's own user-facing text (`safety.profile_unavailable_text`), shown as is.
 */
class ProfileUnavailableException(message: String) : Exception(message)

/** The window of the Meal history screen. */
const val MEAL_HISTORY_DAYS = 21

/**
 * Thin wrapper over `/profile` (`src/backend/api/profile.py`). Reads map a 503 to
 * [ProfileUnavailableException]; other [HttpException]s and [java.io.IOException]s
 * propagate for callers to classify, as with the other repositories.
 */
class ProfileRepository
    @Inject
    constructor(
        private val api: MealsyApi,
    ) {
        suspend fun profile(): ProfileDto = unavailableAware { api.profile() }

        suspend fun history(): List<HardEntryDto> = unavailableAware { api.profileHistory() }

        suspend fun limitsToday(): LimitsTodayDto = unavailableAware { api.limitsToday() }

        /**
         * Adds an entry, or edits [replacesId] when given. Reuse the same
         * [clientRequestId] when retrying a failed submit so the server de-duplicates.
         */
        suspend fun saveEntry(
            type: String,
            value: JsonObject,
            label: String?,
            clientRequestId: String,
            replacesId: String? = null,
        ): HardEntryDto = api.addProfileEntry(EntryRequest(type, value, label, clientRequestId, replacesId))

        suspend fun confirm(id: String): HardEntryDto = api.confirmProfileEntry(id)

        suspend fun deny(id: String): HardEntryDto = api.denyProfileEntry(id)

        /** Retires a confirmed entry; the caller has already asked the patient to confirm. */
        suspend fun retire(
            id: String,
            clientRequestId: String,
        ): HardEntryDto = api.retireProfileEntry(id, RetireRequest(confirm = true, clientRequestId = clientRequestId))

        suspend fun editSoftFact(
            id: String,
            text: String,
            kind: String,
        ): SoftFactDto = api.patchSoftFact(id, SoftFactPatch(text = text, kind = kind))

        suspend fun deleteSoftFact(id: String) = api.deleteSoftFact(id)

        suspend fun meals(days: Int = MEAL_HISTORY_DAYS): ProfileMealsDto = unavailableAware { api.profileMeals(days) }

        /** The full JSON export as text, for the share sheet. */
        suspend fun export(): String = withContext(Dispatchers.IO) { api.profileExport().use { it.string() } }

        private suspend fun <T> unavailableAware(call: suspend () -> T): T =
            try {
                call()
            } catch (exc: HttpException) {
                if (exc.code() != 503) throw exc
                val detail =
                    runCatching {
                        Json.parseToJsonElement(exc.response()?.errorBody()?.string().orEmpty())
                            .jsonObject["detail"]?.jsonPrimitive?.contentOrNull
                    }.getOrNull()
                throw ProfileUnavailableException(detail.orEmpty())
            }
    }
