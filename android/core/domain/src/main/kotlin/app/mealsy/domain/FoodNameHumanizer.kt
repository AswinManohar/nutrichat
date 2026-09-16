package app.mealsy.domain

/**
 * Turns a USDA FoodData Central comma-form description into a short, human
 * title for a meal-detail row. The raw description is kept by the caller for
 * a secondary line, so this function only produces the title.
 *
 * ## Rules
 * 1. Split [raw] on commas and trim each segment.
 * 2. Segment 1 (index 0) is the noun head, e.g. "Chicken", "Egg", "Bread".
 * 3. Drop noise/qualifier segments that add nothing to a meal-detail title:
 *    anatomical-source or trim qualifiers (`broiler or fryers`, `meat only`,
 *    `meat and skin`, `skinless`, `boneless`), prep boilerplate
 *    (`commercially prepared`, `all types`, `NFS`, `NS as to form`,
 *    `prepared`, `without salt`, `with salt`, `enriched`, `unenriched`), the
 *    bare word `whole` (the USDA default state for many foods, e.g. "Egg,
 *    whole" — noise the same way `raw` is, see rule 4; the *hyphenated*
 *    compound `whole-wheat` is a different segment and is kept, see rule 5),
 *    anything starting with `includes`, anything in parentheses (brand
 *    parentheticals), and segments made only of uppercase/brand-looking
 *    tokens with no lowercase letters.
 * 4. Cooking-method segments (`raw, cooked, grilled, roasted, boiled, fried,
 *    baked, broiled, steamed, braised, scrambled, poached, toasted,
 *    sauteed/sautéed, microwaved, canned, dried, frozen`) are collected
 *    separately, not treated as ordinary descriptors. The **last** one
 *    present in source order becomes a leading adjective on the title (e.g.
 *    "Grilled chicken ..."), except `raw`, which is dropped — raw is the
 *    USDA default state and calling it out reads as noise on a meal-detail
 *    row ("Raw chicken breast" vs. just "Chicken breast").
 * 5. Remaining descriptor segments are split into two buckets by a small
 *    fixed list of "prefix" descriptors — hyphenated/compound modifiers and
 *    a few adjectives that read naturally before the noun (`whole-wheat`,
 *    `low-fat`, `nonfat`, `Greek`) — and everything else, which is a
 *    "suffix" part kept after the noun (this covers anatomical/cut words
 *    like `breast`, `thigh`, `wing`, `leg`, `loin`, `fillet`, and other
 *    plain adjectives like `plain`). Only the first prefix descriptor and
 *    first suffix part found are kept, to keep titles short; the rest are
 *    dropped. This is what makes "chicken breast" keep `breast` after the
 *    noun while "whole-wheat bread" puts `whole-wheat` before it, and why
 *    "Yogurt, Greek, plain, nonfat" becomes "Greek yogurt plain" — `Greek`
 *    fills the one prefix slot, `plain` fills the one suffix slot (first
 *    match wins), and the second candidate suffix `nonfat` is dropped.
 * 6. Assembly order: `[cooking method] [prefix descriptor] [noun] [suffix
 *    part]`, sentence-cased (first letter capitalised, rest of the string
 *    left as-is so words like "Greek" keep their capitalisation), single
 *    spaces, no trailing punctuation.
 * 7. Blank input returns the input trimmed — never throws, never returns
 *    empty for non-empty input (falls back to the trimmed noun head).
 * 8. A name with no commas passes through with only sentence-casing.
 *
 * Applying the function to its own output is a no-op: the output has no
 * commas, no parentheses and no noise words, so step 8 (pass-through) takes
 * over and only re-applies sentence casing, which is idempotent.
 */
object FoodNameHumanizer {

    private val COOKING_METHODS = setOf(
        "raw", "cooked", "grilled", "roasted", "boiled", "fried", "baked",
        "broiled", "steamed", "braised", "scrambled", "poached", "toasted",
        "sauteed", "sautéed", "microwaved", "canned", "dried", "frozen",
    )

    private val NOISE_SEGMENTS = setOf(
        "broiler or fryers", "meat only", "meat and skin", "skinless",
        "boneless", "commercially prepared", "all types", "nfs",
        "ns as to form", "prepared", "without salt", "with salt",
        "enriched", "unenriched", "whole",
    )

    private val PREFIX_DESCRIPTORS = setOf(
        "whole-wheat", "low-fat", "nonfat", "greek",
    )

    /** Returns a short, human-readable title for [raw]. See rules above. */
    fun humanize(raw: String): String {
        val trimmed = raw.trim()
        if (trimmed.isEmpty()) return trimmed
        if (!trimmed.contains(',')) return _sentenceCase(trimmed)

        val segments = trimmed.split(',').map { it.trim() }.filter { it.isNotEmpty() }
        if (segments.isEmpty()) return _sentenceCase(trimmed)

        // Lowercased: the noun head is only ever capitalised because it opens
        // the raw USDA sentence, not because it is a proper noun — lowercase
        // it so it reads naturally mid-title (e.g. "grilled chicken breast").
        // Suffix parts are ordinary descriptors and are lowercased the same
        // way. Prefix descriptors keep their original casing because that
        // bucket is where proper nouns like "Greek" live.
        val noun = segments.first().lowercase()
        var cookingMethod: String? = null
        var prefixDescriptor: String? = null
        var suffixPart: String? = null

        for (segment in segments.drop(1)) {
            val lower = segment.lowercase()
            if (lower in NOISE_SEGMENTS) continue
            if (lower.startsWith("includes")) continue
            if (segment.startsWith("(") && segment.endsWith(")")) continue
            if (segment.isNotEmpty() && segment.none { it.isLowerCase() }) continue

            if (lower in COOKING_METHODS) {
                if (lower != "raw") cookingMethod = lower
                continue
            }
            if (lower in PREFIX_DESCRIPTORS) {
                if (prefixDescriptor == null) prefixDescriptor = segment
                continue
            }
            if (suffixPart == null) suffixPart = lower
        }

        val parts = listOfNotNull(cookingMethod, prefixDescriptor, noun, suffixPart)
        return _sentenceCase(parts.joinToString(" "))
    }

    /** Capitalises the first letter of [text], leaving the rest untouched. */
    private fun _sentenceCase(text: String): String {
        if (text.isEmpty()) return text
        return text[0].uppercaseChar() + text.substring(1)
    }
}
