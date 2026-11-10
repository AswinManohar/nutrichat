package app.mealsy.android.ui.micronutrients

import app.mealsy.android.R

/** A reviewed food tip per charted nutrient; a key the server adds later falls back to the generic tip. */
internal fun microTipRes(key: String): Int? =
    when (key) {
        "potassium" -> R.string.micros_tip_potassium
        "calcium" -> R.string.micros_tip_calcium
        "magnesium" -> R.string.micros_tip_magnesium
        "phosphorus" -> R.string.micros_tip_phosphorus
        "vitamin_a" -> R.string.micros_tip_vitamin_a
        "vitamin_c" -> R.string.micros_tip_vitamin_c
        "vitamin_d" -> R.string.micros_tip_vitamin_d
        "vitamin_e" -> R.string.micros_tip_vitamin_e
        "vitamin_k" -> R.string.micros_tip_vitamin_k
        "vitamin_b12" -> R.string.micros_tip_vitamin_b12
        "folate" -> R.string.micros_tip_folate
        "iron" -> R.string.micros_tip_iron
        "zinc" -> R.string.micros_tip_zinc
        "selenium" -> R.string.micros_tip_selenium
        "iodine" -> R.string.micros_tip_iodine
        else -> null
    }
