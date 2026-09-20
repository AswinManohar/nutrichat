package app.mealsy.android.design.components

import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Plain-JUnit coverage of [parseInlineMarkdown]. Deliberately does not pull
 * in Compose UI test infra — [parseInlineMarkdown] is a pure function so a
 * `ComposeContentTestRule` would be unnecessary overhead here.
 */
class MarkdownTextTest {
    @Test
    fun bold_isSemiBoldSpan() {
        val result = parseInlineMarkdown("This is **bold** text")
        assertEquals("This is bold text", result.text)
        val spans = result.spanStyles.filter { it.item.fontWeight == FontWeight.SemiBold }
        assertTrue(spans.any { it.start == 8 && it.end == 12 })
    }

    @Test
    fun italic_isItalicSpan() {
        val result = parseInlineMarkdown("This is *italic* text")
        assertEquals("This is italic text", result.text)
        val spans = result.spanStyles.filter { it.item.fontStyle == FontStyle.Italic }
        assertTrue(spans.any { it.start == 8 && it.end == 14 })
    }

    @Test
    fun underscoreVariants_alsoWork() {
        val bold = parseInlineMarkdown("__bold__")
        assertEquals("bold", bold.text)
        assertTrue(bold.spanStyles.any { it.item.fontWeight == FontWeight.SemiBold })

        val italic = parseInlineMarkdown("_italic_")
        assertEquals("italic", italic.text)
        assertTrue(italic.spanStyles.any { it.item.fontStyle == FontStyle.Italic })
    }

    @Test
    fun nestedItalicInsideBold_bothSpansApply() {
        val result = parseInlineMarkdown("**a _b_ c**")
        assertEquals("a b c", result.text)
        assertTrue(result.spanStyles.any { it.item.fontWeight == FontWeight.SemiBold })
        assertTrue(result.spanStyles.any { it.item.fontStyle == FontStyle.Italic })
    }

    @Test
    fun unclosedBoldMarker_rendersLiterally() {
        val result = parseInlineMarkdown("This is **not closed")
        assertEquals("This is **not closed", result.text)
        assertTrue(result.spanStyles.isEmpty())
    }

    @Test
    fun emptyString_producesEmptyResult() {
        val result = parseInlineMarkdown("")
        assertEquals("", result.text)
        assertTrue(result.spanStyles.isEmpty())
    }

    @Test
    fun literalAsteriskWithNoPair_rendersAsPlainCharacter() {
        val result = parseInlineMarkdown("5 * 3 = 15")
        assertEquals("5 * 3 = 15", result.text)
        assertTrue(result.spanStyles.isEmpty())
    }
}
