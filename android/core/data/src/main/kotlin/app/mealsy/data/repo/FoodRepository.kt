package app.mealsy.data.repo

import app.mealsy.data.api.FoodSearchResultDto
import app.mealsy.data.api.MealsyApi
import app.mealsy.domain.CardItem
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withTimeout
import retrofit2.HttpException
import java.io.IOException
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Search timeout (contracts/android-picker-ui.md, A1): a slow `GET
 * /foods/search` must not hang the sheet — past this, [FoodRepository.search]
 * reports [FoodSearchOutcome.Error], which the picker renders as "Can't
 * search right now".
 */
private const val SEARCH_TIMEOUT_MS = 3_000L

/** One search result, preview-scaled to the item's current grams. */
data class FoodSearchHit(
    val fdcId: Long,
    val name: String,
    val dataType: String,
    val kcalPer100g: Double,
    val proteinGPer100g: Double,
    val kcal: Double,
    val proteinG: Double,
)

/** Outcome of a [FoodRepository.search] call, per `contracts/android-picker-ui.md`. */
sealed interface FoodSearchOutcome {
    data class Results(val hits: List<FoodSearchHit>) : FoodSearchOutcome

    data object Empty : FoodSearchOutcome

    /** The reference DB is unavailable server-side (503) — maps to "Can't search right now". */
    data object Unavailable : FoodSearchOutcome

    /** A network error (no connectivity, timeout) — also maps to "Can't search right now". */
    data object Error : FoodSearchOutcome
}

/**
 * Thin wrapper over `GET /foods/search` and `GET /foods/{fdc_id}` (spec 003),
 * following [MyMealsRepository]'s style.
 */
@Singleton
open class FoodRepository
    @Inject
    constructor(
        private val api: MealsyApi,
    ) {
        /**
         * Searches the reference food DB for [query], previewing macros at
         * [qtyG]. Returns [FoodSearchOutcome.Unavailable] on a 503 and
         * [FoodSearchOutcome.Error] on any other network/HTTP failure — both
         * render as "Can't search right now" in the picker, but are kept
         * distinct so tests can assert the right one is chosen.
         */
        open suspend fun search(
            query: String,
            qtyG: Double,
            limit: Int = 10,
        ): FoodSearchOutcome {
            return try {
                val response =
                    withTimeout(SEARCH_TIMEOUT_MS) {
                        api.searchFoods(q = query, qtyG = qtyG, limit = limit)
                    }
                val hits = response.results.map { it.toFoodSearchHit() }
                if (hits.isEmpty()) FoodSearchOutcome.Empty else FoodSearchOutcome.Results(hits)
            } catch (exc: TimeoutCancellationException) {
                FoodSearchOutcome.Error
            } catch (exc: HttpException) {
                if (exc.code() == 503) FoodSearchOutcome.Unavailable else FoodSearchOutcome.Error
            } catch (exc: IOException) {
                FoodSearchOutcome.Error
            }
        }

        /** Builds a ready-to-log [CardItem] for [fdcId] scaled to [qtyG]. */
        open suspend fun getFood(
            fdcId: Long,
            qtyG: Double,
        ): CardItem {
            val dto = api.getFood(fdcId = fdcId, qtyG = qtyG)
            return CardItem(
                foodName = dto.foodName,
                qtyG = dto.qtyG,
                targetQtyG = dto.targetQtyG ?: dto.qtyG,
                kcal = dto.kcal,
                proteinG = dto.proteinG,
                carbsG = dto.carbsG,
                fatG = dto.fatG,
                fiberG = dto.fiberG,
                fdcId = dto.fdcId,
                estimated = dto.estimated,
                extras = dto.extras,
                candidates = dto.candidates,
                source = dto.source,
                confidence = dto.confidence,
                sourceDish = dto.sourceDish,
                isComposite = dto.isComposite,
            )
        }
    }

private fun FoodSearchResultDto.toFoodSearchHit(): FoodSearchHit =
    FoodSearchHit(
        fdcId = fdcId,
        name = name,
        dataType = dataType,
        kcalPer100g = kcalPer100g,
        proteinGPer100g = proteinGPer100g,
        kcal = kcal,
        proteinG = proteinG,
    )
