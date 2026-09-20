package app.mealsy.android.design.components

import androidx.compose.foundation.layout.padding
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

    // --- CandidatePickerSheetContent: 4 candidates, one current ------------

    private val candidates =
        listOf(
            "Vinaigrette dressing",
            "Balsamic vinaigrette",
            "Italian dressing",
            "Red wine vinaigrette",
        )

    @Test
    fun candidatePickerSheetContent_light() =
        captureMealsy("CandidatePickerSheetContent", false) {
            CandidatePickerSheetContent(
                currentName = "Vinaigrette dressing",
                candidates = candidates,
                onSelect = {},
            )
        }

    @Test
    fun candidatePickerSheetContent_dark() =
        captureMealsy("CandidatePickerSheetContent", true) {
            CandidatePickerSheetContent(
                currentName = "Vinaigrette dressing",
                candidates = candidates,
                onSelect = {},
            )
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
