package app.mealsy.domain

/**
 * The four pastel accent tones used for icon chips and tiny metadata tags
 * (see `CLAUDE.md`'s "Pastels" cross-cutting rule — never fills/backgrounds).
 *
 * [Pink] is not produced by [pastelToneFor]; it is reserved for other
 * surfaces that classify items on axes this function doesn't consider.
 */
enum class PastelTone { Leaf, Butter, Powder, Pink }

/**
 * Classifies [item] into a [PastelTone] for its icon chip / tag color.
 *
 * Rules, evaluated in this order (this ordering is the binding resolution of
 * an ambiguity in the design plan — estimated items are always [PastelTone.Powder]
 * regardless of macro shares, checked before the fat/protein splits):
 * 1. [CardItem.estimated] → [PastelTone.Powder].
 * 2. Fat's share of calories ≥ 0.4 → [PastelTone.Butter].
 * 3. Protein's share of calories ≥ 0.3 → [PastelTone.Leaf].
 * 4. Otherwise → [PastelTone.Leaf].
 *
 * Calorie shares are computed against [CardItem.kcal] (4 kcal/g protein and
 * carbs, 9 kcal/g fat) when `kcal > 0`; otherwise the macro-derived total
 * (`4*protein + 4*carbs + 9*fat`) is used as the denominator. When both are
 * `0`, this returns [PastelTone.Leaf] rather than dividing by zero.
 */
fun pastelToneFor(item: CardItem): PastelTone {
    if (item.estimated) return PastelTone.Powder

    val macroKcal = 4.0 * item.proteinG + 4.0 * item.carbsG + 9.0 * item.fatG
    val denominator = if (item.kcal > 0.0) item.kcal else macroKcal
    if (denominator <= 0.0) return PastelTone.Leaf

    val fatShare = (9.0 * item.fatG) / denominator
    if (fatShare >= 0.4) return PastelTone.Butter

    val proteinShare = (4.0 * item.proteinG) / denominator
    if (proteinShare >= 0.3) return PastelTone.Leaf

    return PastelTone.Leaf
}
