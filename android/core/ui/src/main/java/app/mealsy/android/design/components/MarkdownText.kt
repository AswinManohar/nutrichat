package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * A tiny inline Markdown renderer for coach chat replies, supporting only
 * the subset of Markdown the coaching model actually produces: paragraphs,
 * `**bold**`/`__bold__`, `*italic*`/`_italic_`, and simple unordered/ordered
 * lists. There is no dependency on a Markdown library — the whole thing is
 * a small hand-rolled parser, since the surface area we need is tiny and a
 * full CommonMark implementation would be a heavy dependency for it.
 *
 * @param markdown The raw Markdown source.
 * @param modifier The modifier applied to the outer column.
 * @param style The base text style; inline spans (bold/italic) are layered
 *   on top of this via [SpanStyle].
 * @param color The base text color.
 */
@Composable
fun MarkdownText(
    markdown: String,
    modifier: Modifier = Modifier,
    style: TextStyle = MealsyType.body,
    color: Color = MealsyTheme.colors.ink,
) {
    val blocks = remember(markdown) { parseBlocks(markdown) }
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        blocks.forEach { block ->
            when (block) {
                is MarkdownBlock.Paragraph -> {
                    Text(text = parseInlineMarkdown(block.text), style = style, color = color)
                }
                is MarkdownBlock.ListBlock -> {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        block.items.forEachIndexed { index, item ->
                            Row {
                                val marker = if (block.ordered) "${index + 1}." else "•"
                                Text(text = marker, style = style, color = color)
                                androidx.compose.foundation.layout.Spacer(Modifier.width(6.dp))
                                Text(
                                    text = parseInlineMarkdown(item),
                                    style = style,
                                    color = color,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

/** One parsed block of a Markdown document: a paragraph or a list. */
private sealed interface MarkdownBlock {
    data class Paragraph(val text: String) : MarkdownBlock
    data class ListBlock(val items: List<String>, val ordered: Boolean) : MarkdownBlock
}

/**
 * Splits [source] into paragraph and list blocks on blank lines, grouping
 * consecutive `- `/`* `/`1. ` lines into one [MarkdownBlock.ListBlock].
 */
private fun parseBlocks(source: String): List<MarkdownBlock> {
    val lines = source.replace("\r\n", "\n").split("\n")
    val blocks = mutableListOf<MarkdownBlock>()
    var paragraphLines = mutableListOf<String>()
    var listItems = mutableListOf<String>()
    var listOrdered = false

    fun flushParagraph() {
        if (paragraphLines.isNotEmpty()) {
            blocks.add(MarkdownBlock.Paragraph(paragraphLines.joinToString(" ").trim()))
            paragraphLines = mutableListOf()
        }
    }

    fun flushList() {
        if (listItems.isNotEmpty()) {
            blocks.add(MarkdownBlock.ListBlock(listItems.toList(), listOrdered))
            listItems = mutableListOf()
        }
    }

    val orderedPattern = Regex("""^\d+\.\s+(.*)$""")
    for (rawLine in lines) {
        val line = rawLine
        val trimmed = line.trim()
        when {
            trimmed.isEmpty() -> {
                flushParagraph()
                flushList()
            }
            trimmed.startsWith("- ") || trimmed.startsWith("* ") -> {
                flushParagraph()
                if (listItems.isNotEmpty() && listOrdered) flushList()
                listOrdered = false
                listItems.add(trimmed.substring(2).trim())
            }
            orderedPattern.matches(trimmed) -> {
                flushParagraph()
                if (listItems.isNotEmpty() && !listOrdered) flushList()
                listOrdered = true
                listItems.add(orderedPattern.matchEntire(trimmed)!!.groupValues[1].trim())
            }
            else -> {
                flushList()
                paragraphLines.add(trimmed)
            }
        }
    }
    flushParagraph()
    flushList()
    return blocks
}

/**
 * Parses `**bold**`/`__bold__` and `*italic*`/`_italic_` spans out of
 * [source] into an [AnnotatedString], leaving everything else — including
 * unmatched/unclosed markers — as literal text. Pulled out as a pure
 * function (no Compose types besides [AnnotatedString]) so it is unit
 * testable without a Compose runtime.
 *
 * Algorithm: scan left to right. At each `*`/`_` run, try to find a
 * matching closing run of the same character and length (1 or 2) later in
 * the string with non-empty content between. If found, emit a styled span
 * and skip past the closer; if not, emit the marker character(s) literally
 * and continue scanning from the next character. This guarantees malformed
 * markers degrade to plain text rather than dropping characters or
 * crashing.
 */
internal fun parseInlineMarkdown(source: String): AnnotatedString = buildAnnotatedString {
    var i = 0
    val n = source.length
    while (i < n) {
        val c = source[i]
        if (c == '*' || c == '_') {
            // Determine marker length (2 = bold, 1 = italic).
            val isDouble = i + 1 < n && source[i + 1] == c
            val markerLen = if (isDouble) 2 else 1
            val marker = source.substring(i, i + markerLen)
            val searchStart = i + markerLen
            val closeIndex = findClosingMarker(source, searchStart, marker)
            if (closeIndex != null && closeIndex > searchStart) {
                val inner = source.substring(searchStart, closeIndex)
                val spanStyle = if (isDouble) {
                    SpanStyle(fontWeight = FontWeight.SemiBold)
                } else {
                    SpanStyle(fontStyle = FontStyle.Italic)
                }
                withStyle(spanStyle) { append(parseInlineMarkdown(inner)) }
                i = closeIndex + markerLen
                continue
            }
            // No matching closer — emit the marker character(s) literally.
            append(marker)
            i += markerLen
            continue
        }
        append(c)
        i++
    }
}

/**
 * Finds the index of the next occurrence of [marker] in [source] at or
 * after [from], or null if there is none. Used by [parseInlineMarkdown] to
 * locate a span's closing marker.
 */
private fun findClosingMarker(source: String, from: Int, marker: String): Int? {
    val index = source.indexOf(marker, startIndex = from)
    return if (index == -1) null else index
}

@Preview(name = "MarkdownText light", widthDp = 390)
@Composable
private fun MarkdownTextLightPreview() {
    MealsyTheme {
        Surface(color = MealsyTheme.colors.canvas) {
            MarkdownText(
                markdown = "You're **close** to your protein goal today.\n\n" +
                    "- Add a *quick* snack\n- Try Greek yogurt\n- Or a protein shake",
                modifier = Modifier.padding(20.dp),
            )
        }
    }
}

@Preview(
    name = "MarkdownText dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun MarkdownTextDarkPreview() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            MarkdownText(
                markdown = "You're **close** to your protein goal today.",
                modifier = Modifier.padding(20.dp),
            )
        }
    }
}
