"""Pure food-name matching primitives shared by the USDA read and build paths.

Extracted from ``usda.py`` so the offline importer
(``backend.scripts.build_usda_db``) can reuse the exact scoring and
nutrient-resolution rules without importing aiohttp, pydantic-ai or
SQLAlchemy. Everything here is dependency-free and side-effect free.

Keeping these in one place is load-bearing: the bundled SQLite database is
built with the same energy-resolution rules the API path used, and matched
with the same tokenizer that produced today's ``match_confidence`` values, so
scores stay comparable across the cutover.
"""

from __future__ import annotations

import re

# Grammatical fillers dropped before matching so they don't count as
# required query words (e.g. "rice with chicken" -> {rice, chicken}).
_MATCH_STOPWORDS = frozenset(
    {"and", "or", "with", "the", "a", "an", "of", "in", "on", "to"}
)

_MACRO_MAP = {
    "Energy": "kcal",
    "Protein": "protein_g",
    "Carbohydrate, by difference": "carbs_g",
    "Total lipid (fat)": "fat_g",
    "Fiber, total dietary": "fiber_g",
    "Total Sugars": "sugar_g",
    "Fatty acids, total saturated": "sat_fat_g",
}

# Foundation entries often report energy only under Atwater names (in kcal),
# with no plain "Energy" row — check these in order.
_ENERGY_KEYS = (
    "Energy",
    "Energy (Atwater General Factors)",
    "Energy (Atwater Specific Factors)",
)


def _singularize(token: str) -> str:
    """Crude, symmetric singularizer so plurals match (eggs->egg).

    Applied to both query and description tokens, so even rough rules are
    safe for matching — both sides normalize identically. Handles the
    common English plural endings; leaves short tokens alone.
    """
    if len(token) <= 3:
        return token
    if token.endswith("ies"):
        return token[:-3] + "y"
    if token.endswith(("ses", "shes", "ches", "xes")):
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokenize(text_value: str) -> set[str]:
    """Lowercase, strip punctuation, drop stopwords, singularize."""
    raw = re.sub(r"[^\w\s]", " ", text_value.lower()).split()
    return {_singularize(t) for t in raw if t not in _MATCH_STOPWORDS}


# Everyday preparation nouns that are not FDC head nouns: in FDC they are a
# modifier on a different head ("Bread, ..., toasted"), so left as-is they
# retrieve whatever entry happens to contain the word verbatim -- "toast"
# alone returns "Shrimp toast" (a dim-sum dish) rather than toasted bread
# (issue #38). Rewriting the query text to the FDC form fixes retrieval and
# ranking together: the FDC head noun becomes a query token, so head purity
# and confidence favor it over an unrelated dish that merely contains the
# same word.
_PREPARATION_SYNONYMS: dict[str, str] = {
    "toast": "bread, toasted",
    "toasts": "bread, toasted",
    "fries": "potatoes, french fried",
    "oats": "oats, rolled",
}

# Compound dishes where the synonym word IS the correct FDC head noun, so
# rewriting it would replace a real dish with an unrelated one. Any of these
# words appearing anywhere in the query suppresses the rewrite for that
# synonym.
_SYNONYM_EXCEPTIONS: dict[str, frozenset[str]] = {
    "toast": frozenset({"french", "melba", "zwieback", "anisette", "cinnamon"}),
    # "french fries" is already the FDC phrase ("Potatoes, french fried");
    # rewriting it duplicates "french" and drifts off the correct match.
    "fries": frozenset({"french"}),
}


# A generic berry phrase ("mixed berries", "assorted fresh berries", bare
# "berry") names the FDC generic entry "Berries, NFS". Left as-is, "mixed
# berries" retrieves "Snack, Mixed Berry Bar" (2400 kcal per 100 g in the
# issue #5 report) because the bar's "Mixed Berry" phrase covers every query
# word, and bare "berry" retrieves a berry beverage. Whole-query match only:
# "mixed berry yogurt" must keep its own head noun.
_GENERIC_BERRY_QUERY = re.compile(
    r"\s*(?:(?:mixed|assorted|fresh|summer)\s+)*berr(?:y|ies)\s*", re.IGNORECASE
)


def _normalize_preparation(food_name: str) -> str:
    """Rewrite preparation nouns that are not FDC head nouns to their FDC form.

    Applied to the query text itself, upstream of tokenizing, search and
    ranking, so the rewrite benefits retrieval and every ranking signal
    alike, not just a post-hoc tie-break. Matches are whole-word only (a
    substring like "toast" inside another word is never touched), and each
    synonym has an exception list for compound dishes where the word is
    itself the right FDC head noun (see ``_SYNONYM_EXCEPTIONS``).

    Args:
        food_name: User-facing free-text food name.

    Returns:
        ``food_name`` with any matching bare preparation nouns replaced by
        their FDC head-noun phrase, unchanged if none apply.
    """
    if _GENERIC_BERRY_QUERY.fullmatch(food_name):
        return "berries"
    lowered = food_name.lower()
    for word, replacement in _PREPARATION_SYNONYMS.items():
        if not re.search(rf"\b{re.escape(word)}\b", lowered):
            continue
        if any(exc in lowered for exc in _SYNONYM_EXCEPTIONS.get(word, ())):
            continue
        food_name = re.sub(
            rf"\b{re.escape(word)}\b", replacement, food_name, flags=re.IGNORECASE
        )
    return food_name


def _confidence(query: str, description: str) -> float:
    """Match confidence as query-word coverage by the FDC description.

    Returns the fraction of the user's food words that appear in the FDC
    description (after singularizing and dropping filler words). Coverage,
    not Jaccard: FDC descriptions are verbose ("Rice, white, long-grain,
    regular, raw, enriched") and Jaccard's union denominator wrongly tanks
    correct matches. Coverage asks the right question — "is the food the
    user named actually in this description?" — so "white rice" and "banana"
    score 1.0, while "chicken biryani" vs "Chicken spread" scores 0.5
    (only "chicken" matched) and falls below the floor.
    """
    a = _tokenize(query)
    b = _tokenize(description)
    if not a or not b:
        return 0.5
    return round(len(a & b) / len(a), 3)


def _head_purity(query: str, description: str) -> float:
    """Fraction of the description's head segment covered by the query.

    FDC descriptions are ``HeadNoun, modifier, modifier`` — e.g. "Rice,
    white, cooked, glutinous". Plain query-word coverage over the *whole*
    description ties many candidates at 1.0, and cheap tie-breaks on that
    tie pick the wrong food: "prefer the shortest description" selects
    "Beans and white rice" for the query "white rice", and plain bm25
    selects "Rice flour, white, unenriched". Head purity asks "is the query
    naming this entry's *primary* food?" -- "Rice, white, ..." has head
    {rice} (purity 1.0), "Rice flour, white, ..." has head {rice, flour}
    (0.5), and "Beans and white rice" has head {bean, white, rice} (0.67) --
    so ranking on head purity after coverage sends the right entry to the
    top.

    Args:
        query: The user's free-text food name.
        description: An FDC food description.

    Returns:
        Fraction of the description's head-segment tokens covered by the
        query's tokens, 0.0 if the head segment tokenizes to nothing.
    """
    head = description.split(",", 1)[0]
    query_tokens = _tokenize(query)
    head_tokens = _tokenize(head)
    if not head_tokens:
        return 0.0
    return round(len(query_tokens & head_tokens) / len(head_tokens), 3)


def _description_coverage(query: str, description: str) -> float:
    """Fraction of the description's tokens covered by the query.

    A secondary tie-break behind head purity: among candidates whose head
    noun matches equally well, prefer the description whose modifiers are
    also most fully explained by the query, rather than one with extra
    unexplained modifiers.

    Args:
        query: The user's free-text food name.
        description: An FDC food description.

    Returns:
        Fraction of the description's tokens covered by the query's
        tokens, 0.0 if the description tokenizes to nothing.
    """
    query_tokens = _tokenize(query)
    desc_tokens = _tokenize(description)
    if not desc_tokens:
        return 0.0
    return round(len(query_tokens & desc_tokens) / len(desc_tokens), 3)


def _energy_kcal(raw: dict[str, tuple[float, str]]) -> float:
    """First non-zero energy value across the known FDC energy names."""
    for key in _ENERGY_KEYS:
        if key in raw and raw[key][0] > 0:
            return raw[key][0]
    return 0.0


# FDC's own markers for "the unspecified / base form of this food". "NFS"
# ("Not Further Specified") is an FNDDS convention meaning exactly what a
# bare query noun means; "raw" is the unprepared base form for produce.
_GENERIC_MODIFIERS = frozenset({"nfs", "raw"})

# FDC's *other* generic convention, and about as common as NFS (255 rows vs
# 251): "NS as to <dimension>" -- Not Specified as to cut, form, fat content,
# type of milk. Unlike NFS it is a free-text phrase rather than a token, so it
# needs a prefix test: "Lamb, NS as to cut", "Corn, NS as to form".
_NOT_SPECIFIED_PREFIX = "ns as to "


def _generic_rank(description: str) -> float:
    """1.0 if every modifier after the head is a generic marker, else 0.0.

    A tie-break for queries that name a food without specifying which kind
    of it. "cheese" leaves "Cheese, NFS" and "Cheese, fontina" tied on
    confidence, head purity and description coverage alike -- both have head
    {cheese} and one modifier -- so the ordering fell through to bm25 and
    then fdc_id, i.e. to an arbitrary choice that picked fontina. FDC marks
    the generic entry itself, so prefer it rather than guessing.

    Deliberately narrow: it only separates candidates the existing three
    scores have already tied, and only when a candidate's modifiers are
    *entirely* generic, so "Cheese, cheddar" is never promoted over a more
    specific match the query actually asked for. That strictness means
    "Corn, NS as to form, cooked" does not qualify -- "cooked" is a real
    modifier -- while "Lamb, NS as to cut" does.

    Caveat, measured rather than assumed: the "NS as to" arm is currently
    almost unreachable. Ranking consults this function only after
    ``_description_coverage`` ties, and the marker's own words inflate a
    row's token count enough to lose there first -- "Lamb, NS as to cut"
    scores 0.25 against "Lamb, chop" at 0.50, so it is eliminated one step
    before generic rank is read. Recognising the marker changed 0 of 198
    eval answers. Collapsing the phrase to a single token in ``_tokenize``
    does make it reachable, but that is a change to the shared tokenizer
    feeding all three earlier scores and must be judged on its own.

    Args:
        description: An FDC food description.

    Returns:
        1.0 if the description has at least one modifier and all of them are
        generic markers, 0.0 otherwise.
    """
    modifiers = [p.strip().lower() for p in description.split(",")[1:]]
    if not modifiers:
        return 0.0
    return (
        1.0
        if all(
            m in _GENERIC_MODIFIERS or m.startswith(_NOT_SPECIFIED_PREFIX)
            for m in modifiers
        )
        else 0.0
    )
