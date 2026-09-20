package app.mealsy.domain

/**
 * Turns a USDA FoodData Central comma-form description into a short, human
 * title for a meal-detail row. The raw description is kept by the caller for
 * a secondary line, so this function only produces the title.
 *
 * ## Rules
 * 1. Split [raw] on commas and trim each segment.
 * 2. Segment 1 (index 0) is the noun head, e.g. "Chicken", "Egg", "Bread".
 *    It is lowercased — it is only capitalised because it opens the raw USDA
 *    sentence, not because it is a proper noun.
 * 3. Drop noise/qualifier segments that add nothing to a meal-detail title:
 *    anatomical-source or trim qualifiers (`broiler or fryers`/`broilers or
 *    fryers`, `meat only`,
 *    `meat and skin`, `skinless`, `boneless`, `flesh and skin` — the "both"
 *    case is the default state for produce/meat and reads as noise, the same
 *    way `raw` does; the *contrastive* single-sided `with skin` / `without
 *    skin` are informative and are kept, see rule 5), prep boilerplate
 *    (`commercially prepared`, `all types`, `NFS`, `NS as to form`,
 *    `prepared`, `without salt`, `with salt`, `enriched`, `unenriched`),
 *    size/grade filler (`regular`, `long-grain`, `large`, `medium`, `small`,
 *    `salad or cooking`, `plain`), any segment containing `%` or `/`
 *    (percentages and ratios, e.g. "80% lean meat / 20% fat"), anything
 *    starting with `includes`, anything in parentheses (brand
 *    parentheticals), and segments made only of uppercase/brand-looking
 *    tokens with no lowercase letters. The bare word `whole` is dropped only
 *    when a cooking method is also present (`Egg, whole, cooked, scrambled`
 *    → the egg's whole-ness is redundant once you say "scrambled"); with no
 *    cooking method it is a real descriptor and is kept (`Milk, whole, ...`
 *    → "Whole milk"). The *hyphenated* compound `whole-wheat` is never
 *    affected by this — it is a different segment and always survives.
 * 4. Cooking-method segments (`raw, cooked, grilled, roasted, boiled, fried,
 *    baked, broiled, steamed, braised, scrambled, poached, toasted,
 *    sauteed/sautéed, microwaved, canned, dried, frozen`) are collected
 *    separately, not treated as ordinary descriptors, and never compete for
 *    the prefix/suffix slots below. The **last** one present in source order
 *    becomes a leading adjective on the title (e.g. "Grilled chicken ..."),
 *    except `raw`, which is dropped — raw is the USDA default state and
 *    calling it out reads as noise on a meal-detail row ("Raw chicken
 *    breast" vs. just "Chicken breast").
 * 5. Every remaining descriptor defaults to a **prefix** adjective (before
 *    the noun) — this is how English food names normally read: "white
 *    rice", "olive oil", "cheddar cheese", "ground beef", "russet potatoes",
 *    "Atlantic salmon". Only a small closed set of anatomical/part words
 *    goes in the **suffix** slot instead (after the noun): `breast, thigh,
 *    wing, leg, drumstick, loin, tenderloin, fillet, filet, shank, rib,
 *    ribs, flesh, skin, with skin, without skin, kernels, florets` — this is
 *    what keeps "chicken breast" and "apples with skin" reading naturally.
 *    Only the *first* descriptor found for each slot is kept, to keep
 *    titles short and to prefer the most specific one over generic
 *    grade/qualifier words that survived rule 3; later candidates for an
 *    already-filled slot are dropped.
 * 6. Casing: a descriptor segment whose first letter is uppercase in the raw
 *    string is a proper noun (`Greek`, `Atlantic`) and is kept verbatim,
 *    wherever it lands (prefix or suffix); every other kept segment is
 *    lowercased. The final assembled title is then sentence-cased — only
 *    its very first letter is capitalised — so a mid-string proper noun
 *    like "Atlantic" is never re-lowercased.
 * 7. Assembly order: `[cooking method] [prefix descriptor] [noun] [suffix
 *    part]`, single spaces, no trailing punctuation.
 * 8. Blank input returns the input trimmed — never throws, never returns
 *    empty for non-empty input (falls back to the trimmed noun head).
 * 9. A name with no commas passes through with only sentence-casing.
 *
 * Applying the function to its own output is a no-op: the output has no
 * commas, no parentheses and no noise words, so rule 9 (pass-through) takes
 * over and only re-applies sentence casing, which is idempotent.
 */
object FoodNameHumanizer {

    private val COOKING_METHODS = setOf(
        "raw", "cooked", "grilled", "roasted", "boiled", "fried", "baked",
        "broiled", "steamed", "braised", "scrambled", "poached", "toasted",
        "sauteed", "sautéed", "microwaved", "canned", "dried", "frozen",
    )

    // Includes both the singular and plural USDA forms of "broiler or
    // fryers" ("broiler or fryers" vs. "broilers or fryers") since FDC
    // descriptions use either depending on the source dataset.
    private val NOISE_SEGMENTS = setOf(
        "broiler or fryers", "broilers or fryers", "meat only", "meat and skin",
        "skinless", "boneless", "flesh and skin", "commercially prepared",
        "all types", "nfs", "ns as to form", "prepared", "without salt",
        "with salt", "enriched", "unenriched", "regular", "long-grain",
        "large", "medium", "small", "salad or cooking", "plain",
    )

    private val SUFFIX_PARTS = setOf(
        "breast", "thigh", "wing", "leg", "drumstick", "loin", "tenderloin",
        "fillet", "filet", "shank", "rib", "ribs", "flesh", "skin",
        "with skin", "without skin", "kernels", "florets",
    )

    /** Returns a short, human-readable title for [raw]. See rules above. */
    fun humanize(raw: String): String {
        val trimmed = raw.trim()
        if (trimmed.isEmpty()) return trimmed
        if (!trimmed.contains(',')) return _sentenceCase(trimmed)

        val segments = trimmed.split(',').map { it.trim() }.filter { it.isNotEmpty() }
        if (segments.isEmpty()) return _sentenceCase(trimmed)

        val noun = segments.first().lowercase()
        val descriptors = segments.drop(1)

        // Pass 1: find the leading cooking-method adjective (last non-raw
        // one wins), so pass 2 can decide whether bare "whole" is noise.
        var cookingMethod: String? = null
        for (segment in descriptors) {
            val lower = segment.lowercase()
            if (lower in COOKING_METHODS && lower != "raw") cookingMethod = lower
        }

        // Pass 2: assign the prefix/suffix slots.
        var prefixDescriptor: String? = null
        var suffixPart: String? = null
        for (segment in descriptors) {
            val lower = segment.lowercase()
            if (lower in COOKING_METHODS) continue // handled in pass 1
            if (lower == "whole" && cookingMethod != null) continue
            if (lower in NOISE_SEGMENTS) continue
            if (lower.contains('%') || lower.contains('/')) continue
            if (lower.startsWith("includes")) continue
            if (segment.startsWith("(") && segment.endsWith(")")) continue
            if (segment.isNotEmpty() && segment.none { it.isLowerCase() }) continue

            val cased = if (segment.firstOrNull()?.isUpperCase() == true) segment else lower
            if (lower in SUFFIX_PARTS) {
                if (suffixPart == null) suffixPart = cased
            } else {
                if (prefixDescriptor == null) prefixDescriptor = cased
            }
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
