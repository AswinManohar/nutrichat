package app.mealsy.android.ui.profile

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import app.mealsy.android.R
import app.mealsy.android.design.components.Eyebrow
import app.mealsy.android.design.components.FilterChipPill
import app.mealsy.android.design.components.MealsyButton
import app.mealsy.android.design.components.MealsyButtonStyle
import app.mealsy.android.design.components.MealsyDialog
import app.mealsy.android.design.components.PillInput
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.data.api.HardEntryDto
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive
import java.util.UUID

/** Entry types a patient can add or edit in the app (diet settings live in Settings). */
internal val EDITABLE_TYPES =
    listOf(
        CareType.Allergy,
        CareType.Diagnosis,
        CareType.Medication,
        CareType.PhysicalLimitation,
        CareType.NutrientLimit,
    )

/** Allergen groups the backend recognises (`AllergyValue.allergen_group`). */
private val ALLERGEN_LABELS =
    linkedMapOf(
        "peanut" to R.string.allergen_peanut,
        "tree_nut" to R.string.allergen_tree_nut,
        "milk" to R.string.allergen_milk,
        "egg" to R.string.allergen_egg,
        "fish" to R.string.allergen_fish,
        "shellfish" to R.string.allergen_shellfish,
        "soy" to R.string.allergen_soy,
        "wheat_gluten" to R.string.allergen_wheat_gluten,
        "sesame" to R.string.allergen_sesame,
    )
private const val OTHER = "other"

private val LIMITATION_LABELS =
    linkedMapOf(
        "chewing" to R.string.limitation_chewing,
        "swallowing" to R.string.limitation_swallowing,
        "grip" to R.string.limitation_grip,
        "standing_time" to R.string.limitation_standing_time,
    )

/** Nutrient to its label and the unit it is usually limited in. */
internal val NUTRIENTS =
    linkedMapOf(
        "sodium" to (R.string.nutrient_sodium to "mg"),
        "potassium" to (R.string.nutrient_potassium to "mg"),
        "phosphorus" to (R.string.nutrient_phosphorus to "mg"),
        "protein" to (R.string.nutrient_protein to "g"),
        "carbohydrate" to (R.string.nutrient_carbohydrate to "g"),
        "fluid" to (R.string.nutrient_fluid to "ml"),
    )
private val UNITS = listOf("mg", "g", "ml")
private val PERIODS = linkedMapOf("per_day" to R.string.limit_period_day, "per_meal" to R.string.limit_period_meal)

@StringRes
internal fun careTypeTitle(type: CareType): Int =
    when (type) {
        CareType.Allergy -> R.string.care_type_allergy
        CareType.Diagnosis -> R.string.care_type_diagnosis
        CareType.Medication -> R.string.care_type_medication
        CareType.PhysicalLimitation -> R.string.care_type_limitation
        CareType.NutrientLimit -> R.string.care_type_nutrient_limit
        CareType.DietSetting -> R.string.care_type_diet_setting
        CareType.FoodExclusion -> R.string.care_type_food_exclusion
    }

/** The editable form fields for every type; only those of [type] are used. */
internal data class EntryDraft(
    val type: CareType = CareType.Allergy,
    val allergen: String = "peanut",
    val custom: String = "",
    val text: String = "",
    val limitation: String = "chewing",
    val minutes: String = "",
    val nutrient: String = "sodium",
    val amount: String = "",
    val minAmount: String = "",
    val unit: String = "mg",
    val period: String = "per_day",
) {
    /** The value body for `POST /profile/entries`, or null while the draft is invalid. */
    fun toValue(): JsonObject? =
        when (type) {
            CareType.Allergy ->
                if (allergen == OTHER) {
                    custom.trim().takeIf { it.isNotEmpty() }?.let {
                        JsonObject(mapOf("custom_terms" to JsonArray(listOf(JsonPrimitive(it)))))
                    }
                } else {
                    JsonObject(mapOf("allergen_group" to JsonPrimitive(allergen)))
                }
            CareType.Diagnosis -> text.trim().takeIf { it.isNotEmpty() }?.let { JsonObject(mapOf("condition" to JsonPrimitive(it))) }
            CareType.Medication -> text.trim().takeIf { it.isNotEmpty() }?.let { JsonObject(mapOf("name" to JsonPrimitive(it))) }
            CareType.PhysicalLimitation -> limitationValue()
            CareType.NutrientLimit -> limitValue()
            CareType.DietSetting, CareType.FoodExclusion -> null
        }

    /** True when the minimum is filled in but not below the amount. */
    val rangeInvalid: Boolean
        get() {
            val max = amount.toDoubleOrNull()
            val min = minAmount.toDoubleOrNull()
            return type == CareType.NutrientLimit && max != null && min != null && min >= max
        }

    private fun limitationValue(): JsonObject? {
        val mins = minutes.trim()
        val parsed = mins.toIntOrNull()
        if (limitation != "standing_time" || mins.isEmpty()) return JsonObject(mapOf("kind" to JsonPrimitive(limitation)))
        if (parsed == null || parsed <= 0) return null
        return JsonObject(mapOf("kind" to JsonPrimitive(limitation), "max_active_minutes" to JsonPrimitive(parsed)))
    }

    private fun limitValue(): JsonObject? {
        val max = amount.toDoubleOrNull()?.takeIf { it > 0 } ?: return null
        val min =
            minAmount.trim().takeIf { it.isNotEmpty() }?.let {
                    raw ->
                raw.toDoubleOrNull()?.takeIf { it >= 0 && it < max } ?: return null
            }
        val fields =
            mutableMapOf<String, kotlinx.serialization.json.JsonElement>(
                "nutrient" to JsonPrimitive(nutrient),
                "amount" to JsonPrimitive(max),
                "unit" to JsonPrimitive(unit),
                "period" to JsonPrimitive(period),
            )
        if (min != null) fields["min_amount"] = JsonPrimitive(min)
        return JsonObject(fields)
    }

    companion object {
        /** A draft pre-filled from an existing [entry] (null for types the sheet cannot edit). */
        fun from(entry: HardEntryDto): EntryDraft? {
            val type = CareType.entries.firstOrNull { it.wire == entry.type } ?: return null
            val v = entry.value

            fun str(key: String) = v[key]?.jsonPrimitive?.contentOrNull.orEmpty()
            val unit = str("unit").ifEmpty { "mg" }
            return when (type) {
                CareType.Allergy -> {
                    val group = str("allergen_group")
                    val custom = (v["custom_terms"] as? JsonArray)?.firstOrNull()?.jsonPrimitive?.contentOrNull.orEmpty()
                    EntryDraft(type, allergen = group.ifEmpty { OTHER }, custom = custom)
                }
                CareType.Diagnosis -> EntryDraft(type, text = str("condition"))
                CareType.Medication -> EntryDraft(type, text = str("name"))
                CareType.PhysicalLimitation ->
                    EntryDraft(
                        type,
                        limitation =
                            str("kind").ifEmpty {
                                "chewing"
                            },
                        minutes = v["max_active_minutes"]?.jsonPrimitive?.intOrNull?.toString().orEmpty(),
                    )
                CareType.NutrientLimit ->
                    EntryDraft(
                        type,
                        nutrient = str("nutrient").ifEmpty { "sodium" },
                        amount = v["amount"]?.jsonPrimitive?.doubleOrNull?.let(::plain).orEmpty(),
                        minAmount = v["min_amount"]?.jsonPrimitive?.doubleOrNull?.let(::plain).orEmpty(),
                        unit = unit,
                        period = str("period").ifEmpty { "per_day" },
                    )
                CareType.DietSetting, CareType.FoodExclusion -> null
            }
        }

        private fun plain(d: Double): String = if (d % 1.0 == 0.0) d.toLong().toString() else d.toString()
    }
}

/**
 * Bottom sheet to add a profile entry, or edit/retire [entry] when given. Saving an edit sends
 * the old entry's id as `replaces_id`; retiring asks for confirmation first. One
 * `client_request_id` per sheet lets a retry after a failure be de-duplicated by the server.
 *
 * @param entry The entry being edited, or null to add a new one.
 * @param save Whether a request is in flight or has failed.
 * @param onSave Called with the type and value to send, and the request id.
 * @param onRetire Called after the retire confirmation, with the request id.
 * @param onDismiss Called when the sheet is closed without saving.
 */
@OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3Api::class)
@Composable
fun EntryEditorSheet(
    entry: HardEntryDto?,
    save: CareSaveState,
    onSave: (CareType, JsonObject, String) -> Unit,
    onRetire: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val colors = MealsyTheme.colors
    var draft by remember { mutableStateOf(entry?.let { EntryDraft.from(it) } ?: EntryDraft()) }
    var confirmRetire by remember { mutableStateOf(false) }
    val requestId = remember { UUID.randomUUID().toString() }
    val value = draft.toValue()

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = colors.surface,
        shape = RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp),
    ) {
        Column(
            modifier = Modifier.verticalScroll(rememberScrollState()).navigationBarsPadding().padding(horizontal = 20.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = stringResource(if (entry == null) R.string.entry_sheet_add_title else R.string.entry_sheet_edit_title),
                style = MealsyType.section,
                color = colors.ink,
            )
            if (entry == null) {
                Eyebrow(text = stringResource(R.string.entry_field_type))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    EDITABLE_TYPES.forEach { t ->
                        FilterChipPill(stringResource(careTypeTitle(t)), draft.type == t, { draft = EntryDraft(type = t) })
                    }
                }
            }
            when (draft.type) {
                CareType.Allergy -> {
                    Choices(R.string.entry_field_allergen, ALLERGEN_LABELS + (OTHER to R.string.allergen_other), draft.allergen) {
                        draft = draft.copy(allergen = it)
                    }
                    if (draft.allergen == OTHER) {
                        TextField(R.string.entry_field_custom_allergen, draft.custom) { draft = draft.copy(custom = it) }
                    }
                }
                CareType.Diagnosis -> TextField(R.string.entry_field_condition, draft.text) { draft = draft.copy(text = it) }
                CareType.Medication -> TextField(R.string.entry_field_medication, draft.text) { draft = draft.copy(text = it) }
                CareType.PhysicalLimitation -> {
                    Choices(R.string.entry_field_limitation, LIMITATION_LABELS, draft.limitation) { draft = draft.copy(limitation = it) }
                    if (draft.limitation == "standing_time") {
                        TextField(R.string.entry_field_max_minutes, draft.minutes, KeyboardType.Number) { draft = draft.copy(minutes = it) }
                    }
                }
                CareType.NutrientLimit -> {
                    Choices(R.string.entry_field_nutrient, NUTRIENTS.mapValues { it.value.first }, draft.nutrient) { key ->
                        draft = draft.copy(nutrient = key, unit = NUTRIENTS.getValue(key).second)
                    }
                    TextField(R.string.entry_field_amount, draft.amount, KeyboardType.Decimal) { draft = draft.copy(amount = it) }
                    TextField(R.string.entry_field_min_amount, draft.minAmount, KeyboardType.Decimal) { draft = draft.copy(minAmount = it) }
                    if (draft.rangeInvalid) {
                        Text(stringResource(R.string.entry_error_range), style = MealsyType.label, color = colors.terracottaOutlineText)
                    }
                    Eyebrow(text = stringResource(R.string.entry_field_unit))
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        UNITS.forEach { u -> FilterChipPill(u, draft.unit == u, { draft = draft.copy(unit = u) }) }
                    }
                    Choices(R.string.entry_field_period, PERIODS, draft.period) { draft = draft.copy(period = it) }
                }
                CareType.DietSetting, CareType.FoodExclusion -> Unit
            }
            if (save.failed) {
                Text(stringResource(R.string.entry_error_save), style = MealsyType.label, color = colors.terracottaOutlineText)
            }
            MealsyButton(
                text = stringResource(R.string.entry_save),
                onClick = { value?.let { onSave(draft.type, it, requestId) } },
                modifier = Modifier.fillMaxWidth(),
                enabled = value != null && !save.saving,
            )
            if (entry != null) {
                MealsyButton(
                    text = stringResource(R.string.entry_retire),
                    onClick = { confirmRetire = true },
                    modifier = Modifier.fillMaxWidth(),
                    style = MealsyButtonStyle.Destructive,
                    enabled = !save.saving,
                )
            }
        }
    }

    if (confirmRetire && entry != null) {
        MealsyDialog(
            onDismissRequest = { confirmRetire = false },
            title = stringResource(R.string.entry_retire_title),
            body = stringResource(R.string.entry_retire_body, entry.label),
            buttons = {
                MealsyButton(
                    text = stringResource(R.string.entry_retire_confirm),
                    onClick = {
                        confirmRetire = false
                        onRetire(requestId)
                    },
                    style = MealsyButtonStyle.Destructive,
                )
                MealsyButton(
                    text = stringResource(R.string.settings_cancel),
                    onClick = { confirmRetire = false },
                    style = MealsyButtonStyle.Secondary,
                )
            },
        )
    }
}

/** A labelled single-choice chip group over [options] (wire value to label). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Choices(
    @StringRes title: Int,
    options: Map<String, Int>,
    selected: String,
    onSelect: (String) -> Unit,
) {
    Eyebrow(text = stringResource(title))
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        options.forEach { (key, label) -> FilterChipPill(stringResource(label), selected == key, { onSelect(key) }) }
    }
}

@Composable
private fun TextField(
    @StringRes label: Int,
    value: String,
    keyboard: KeyboardType = KeyboardType.Text,
    onChange: (String) -> Unit,
) {
    Eyebrow(text = stringResource(label))
    PillInput(
        value = value,
        onValueChange = onChange,
        modifier = Modifier.fillMaxWidth(),
        keyboardOptions = KeyboardOptions(keyboardType = keyboard),
    )
}
