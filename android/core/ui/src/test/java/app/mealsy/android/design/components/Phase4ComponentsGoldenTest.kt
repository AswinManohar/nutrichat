package app.mealsy.android.design.components

import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.ScreenshotTestBase
import org.junit.Test

/**
 * Goldens for the Phase 4 confirm-card / coach-chat components: [TotalsStrip],
 * [CompositeDishHeader], [CandidatePickerSheetContent], and [MarkdownText].
 * Follows [ComponentsGoldenTest]'s pattern exactly — one light + one dark
 * capture per case, no animation.
 */
class Phase4ComponentsGoldenTest : ScreenshotTestBase() {
    // --- TotalsStrip: all-nonzero, and with carbs/fat/fiber zeroed --------

    private val allNonZero =
        listOf(
            TotalsStripEntry("kcal", "412", isZero = false),
            TotalsStripEntry("Protein", "28g", isZero = false),
            TotalsStripEntry("Carbs", "12g", isZero = false),
            TotalsStripEntry("Fat", "31g", isZero = false),
            TotalsStripEntry("Fiber", "4g", isZero = false),
        )

    private val someZero =
        listOf(
            TotalsStripEntry("kcal", "181", isZero = false),
            TotalsStripEntry("Protein", "37g", isZero = false),
            TotalsStripEntry("Carbs", "0g", isZero = true),
            TotalsStripEntry("Fat", "0g", isZero = true),
            TotalsStripEntry("Fiber", "0g", isZero = true),
        )

    @Test
    fun totalsStrip_allNonZero_light() = captureMealsy("TotalsStrip_allNonZero", false) { TotalsStrip(entries = allNonZero) }

    @Test
    fun totalsStrip_allNonZero_dark() = captureMealsy("TotalsStrip_allNonZero", true) { TotalsStrip(entries = allNonZero) }

    @Test
    fun totalsStrip_someZero_light() = captureMealsy("TotalsStrip_someZero", false) { TotalsStrip(entries = someZero) }

    @Test
    fun totalsStrip_someZero_dark() = captureMealsy("TotalsStrip_someZero", true) { TotalsStrip(entries = someZero) }

    // --- CompositeDishHeader: both actions present --------------------------

    @Test
    fun compositeDishHeader_bothActions_light() =
        captureMealsy("CompositeDishHeader_bothActions", false) {
            CompositeDishHeader(
                dishName = "Chicken caesar salad",
                onBreakIntoIngredients = {},
                onLogAsSingleItem = {},
            )
        }

    @Test
    fun compositeDishHeader_bothActions_dark() =
        captureMealsy("CompositeDishHeader_bothActions", true) {
            CompositeDishHeader(
                dishName = "Chicken caesar salad",
                onBreakIntoIngredients = {},
                onLogAsSingleItem = {},
            )
        }

    // --- CandidatePickerSheetContent: search field + results states (spec 003, T031) ---

    private fun pickerRow(
        name: String,
        fdcId: Long,
        isCurrent: Boolean = false,
    ) = PickerRow(fdcId = fdcId, name = name, kcal = 82.0, proteinG = 2.5, isCurrent = isCurrent)

    private val loadedResults =
        PickerResultsState.Loaded(
            listOf(
                pickerRow("Bread, white, commercially prepared, toasted", 172687, isCurrent = true),
                pickerRow("Melba toast", 111222),
                pickerRow("Anisette toast", 333444),
            ),
        )

    @Composable
    private fun pickerContent(
        resultsState: PickerResultsState,
        online: Boolean = true,
        query: String = "toast",
    ) {
        CandidatePickerSheetContent(
            currentName = "Shrimp toast",
            query = query,
            onQueryChange = {},
            online = online,
            resultsState = resultsState,
            onSelectResult = { _, _ -> },
            onRemove = {},
            onDescribeDifferently = {},
        )
    }

    @Test
    fun candidatePickerSheetContent_loaded_light() =
        captureMealsy("CandidatePickerSheetContent_loaded", false) { pickerContent(loadedResults) }

    @Test
    fun candidatePickerSheetContent_loaded_dark() =
        captureMealsy("CandidatePickerSheetContent_loaded", true) { pickerContent(loadedResults) }

    @Test
    fun candidatePickerSheetContent_loaded_font2x() =
        captureMealsy("CandidatePickerSheetContent_loaded", false, fontScale = 2.0f) { pickerContent(loadedResults) }

    @Test
    fun candidatePickerSheetContent_loading_light() =
        captureMealsy("CandidatePickerSheetContent_loading", false) { pickerContent(PickerResultsState.Loading) }

    @Test
    fun candidatePickerSheetContent_loading_dark() =
        captureMealsy("CandidatePickerSheetContent_loading", true) { pickerContent(PickerResultsState.Loading) }

    @Test
    fun candidatePickerSheetContent_empty_light() =
        captureMealsy("CandidatePickerSheetContent_empty", false) { pickerContent(PickerResultsState.Empty) }

    @Test
    fun candidatePickerSheetContent_empty_dark() =
        captureMealsy("CandidatePickerSheetContent_empty", true) { pickerContent(PickerResultsState.Empty) }

    @Test
    fun candidatePickerSheetContent_unavailable_light() =
        captureMealsy("CandidatePickerSheetContent_unavailable", false) { pickerContent(PickerResultsState.Unavailable) }

    @Test
    fun candidatePickerSheetContent_unavailable_dark() =
        captureMealsy("CandidatePickerSheetContent_unavailable", true) { pickerContent(PickerResultsState.Unavailable) }

    @Test
    fun candidatePickerSheetContent_offline_light() =
        captureMealsy("CandidatePickerSheetContent_offline", false) {
            pickerContent(PickerResultsState.Idle, online = false, query = "")
        }

    @Test
    fun candidatePickerSheetContent_offline_dark() =
        captureMealsy("CandidatePickerSheetContent_offline", true) {
            pickerContent(PickerResultsState.Idle, online = false, query = "")
        }

    // --- MarkdownText: paragraph + bold + 3-item bullet list ----------------

    private val markdownSample =
        "You're **close** to your protein goal today.\n\n" +
            "- Add a quick snack\n" +
            "- Try Greek yogurt\n" +
            "- Or a protein shake"

    @Test
    fun markdownText_light() =
        captureMealsy("MarkdownText_paragraphAndList", false) {
            MarkdownText(markdown = markdownSample, modifier = Modifier.padding(4.dp))
        }

    @Test
    fun markdownText_dark() =
        captureMealsy("MarkdownText_paragraphAndList", true) {
            MarkdownText(markdown = markdownSample, modifier = Modifier.padding(4.dp))
        }
}
