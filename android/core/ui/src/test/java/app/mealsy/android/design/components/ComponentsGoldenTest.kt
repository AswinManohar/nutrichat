package app.mealsy.android.design.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.ScreenshotTestBase
import org.junit.Test

/**
 * Goldens for every T3/T4 `design/components/` composable, light and dark.
 * `animate`/similar flags are pinned false throughout for determinism.
 */
class ComponentsGoldenTest : ScreenshotTestBase() {

    // --- MealsyButton: 4 styles x (enabled, disabled) ---------------------

    @Composable
    private fun ButtonRow(enabled: Boolean) {
        Column {
            MealsyButtonStyle.entries.forEach { style ->
                MealsyButton(
                    text = style.name,
                    onClick = {},
                    style = style,
                    enabled = enabled,
                    modifier = Modifier.padding(vertical = 4.dp),
                )
            }
        }
    }

    @Test
    fun mealsyButton_enabled_light() =
        captureMealsy("MealsyButton_enabled", false) { ButtonRow(enabled = true) }

    @Test
    fun mealsyButton_enabled_dark() =
        captureMealsy("MealsyButton_enabled", true) { ButtonRow(enabled = true) }

    @Test
    fun mealsyButton_disabled_light() =
        captureMealsy("MealsyButton_disabled", false) { ButtonRow(enabled = false) }

    @Test
    fun mealsyButton_disabled_dark() =
        captureMealsy("MealsyButton_disabled", true) { ButtonRow(enabled = false) }

    // --- PillInput: empty + filled -----------------------------------------

    @Test
    fun pillInput_empty_light() = captureMealsy("PillInput_empty", false) {
        PillInput(value = "", onValueChange = {}, placeholder = "Log a meal...")
    }

    @Test
    fun pillInput_empty_dark() = captureMealsy("PillInput_empty", true) {
        PillInput(value = "", onValueChange = {}, placeholder = "Log a meal...")
    }

    @Test
    fun pillInput_filled_light() = captureMealsy("PillInput_filled", false) {
        PillInput(value = "Grilled chicken and rice", onValueChange = {})
    }

    @Test
    fun pillInput_filled_dark() = captureMealsy("PillInput_filled", true) {
        PillInput(value = "Grilled chicken and rice", onValueChange = {})
    }

    // --- SegmentedControl: middle selection ---------------------------------

    @Test
    fun segmentedControl_light() = captureMealsy("SegmentedControl_midSelection", false) {
        SegmentedControl(
            options = listOf("Day", "Week", "Month"),
            selected = "Week",
            onSelect = {},
            label = { it },
        )
    }

    @Test
    fun segmentedControl_dark() = captureMealsy("SegmentedControl_midSelection", true) {
        SegmentedControl(
            options = listOf("Day", "Week", "Month"),
            selected = "Week",
            onSelect = {},
            label = { it },
        )
    }

    // --- Stepper: mid value and at min ---------------------------------------

    @Test
    fun stepper_mid_light() = captureMealsy("Stepper_mid", false) {
        Stepper(value = 150, onValueChange = {})
    }

    @Test
    fun stepper_mid_dark() = captureMealsy("Stepper_mid", true) {
        Stepper(value = 150, onValueChange = {})
    }

    @Test
    fun stepper_min_light() = captureMealsy("Stepper_min", false) {
        Stepper(value = 5, onValueChange = {}, min = 5)
    }

    @Test
    fun stepper_min_dark() = captureMealsy("Stepper_min", true) {
        Stepper(value = 5, onValueChange = {}, min = 5)
    }

    // --- TagChip: all four tones -----------------------------------------

    @Composable
    private fun TagChipRow() {
        Row {
            TagTone.entries.forEach { tone ->
                TagChip(text = tone.name, tone = tone, modifier = Modifier.padding(4.dp))
            }
        }
    }

    @Test
    fun tagChip_light() = captureMealsy("TagChip_allTones", false) { TagChipRow() }

    @Test
    fun tagChip_dark() = captureMealsy("TagChip_allTones", true) { TagChipRow() }

    // --- PastelIconCircle: all four tones, icon and initial variants -------

    @Composable
    private fun PastelIconCircleIconRow() {
        Row {
            TagTone.entries.forEach { tone ->
                PastelIconCircle(
                    icon = app.mealsy.android.design.icons.MealsyIcons.BowlBars,
                    tone = tone,
                    modifier = Modifier.padding(4.dp),
                )
            }
        }
    }

    @Composable
    private fun PastelIconCircleInitialRow() {
        Row {
            TagTone.entries.forEachIndexed { i, tone ->
                PastelIconCircle(initial = ('A' + i), tone = tone, modifier = Modifier.padding(4.dp))
            }
        }
    }

    @Test
    fun pastelIconCircle_icon_light() = captureMealsy("PastelIconCircle_icon", false) { PastelIconCircleIconRow() }

    @Test
    fun pastelIconCircle_icon_dark() = captureMealsy("PastelIconCircle_icon", true) { PastelIconCircleIconRow() }

    @Test
    fun pastelIconCircle_initial_light() = captureMealsy("PastelIconCircle_initial", false) { PastelIconCircleInitialRow() }

    @Test
    fun pastelIconCircle_initial_dark() = captureMealsy("PastelIconCircle_initial", true) { PastelIconCircleInitialRow() }

    // --- ListRow inside ListContainer: badge + "not yet", 16dp insets -------

    @Composable
    private fun ListRowsInContainer() {
        ListContainer {
            ListRow(
                label = "Breakfast",
                onClick = {},
                leading = { PastelIconCircle(initial = 'B', tone = TagTone.Butter) },
                badgeCount = 3,
            )
            ListRow(
                label = "Dinner",
                onClick = {},
                leading = { PastelIconCircle(initial = 'D', tone = TagTone.Pink) },
                trailingText = "not yet",
            )
            ListRow(
                label = "Lunch",
                onClick = {},
                leading = { PastelIconCircle(initial = 'L', tone = TagTone.Leaf) },
                badgeCount = 1,
            )
        }
    }

    @Test
    fun listRow_inContainer_light() = captureMealsy("ListRow_inContainer", false) { ListRowsInContainer() }

    @Test
    fun listRow_inContainer_dark() = captureMealsy("ListRow_inContainer", true) { ListRowsInContainer() }

    // --- MetricCard: 3-up row -----------------------------------------------

    @Composable
    private fun MetricCardRow() {
        Row {
            MetricCard(label = "Calories", value = "1,340", modifier = Modifier.padding(4.dp))
            MetricCard(label = "Protein", value = "82g", modifier = Modifier.padding(4.dp))
            MetricCard(label = "Carbs", value = "140g", modifier = Modifier.padding(4.dp))
        }
    }

    @Test
    fun metricCard_light() = captureMealsy("MetricCard_threeUp", false) { MetricCardRow() }

    @Test
    fun metricCard_dark() = captureMealsy("MetricCard_threeUp", true) { MetricCardRow() }

    // --- CoachNote -----------------------------------------------------------

    @Test
    fun coachNote_light() = captureMealsy("CoachNote", false) {
        CoachNote(text = "Great job hitting your protein goal today!")
    }

    @Test
    fun coachNote_dark() = captureMealsy("CoachNote", true) {
        CoachNote(text = "Great job hitting your protein goal today!")
    }

    // --- Eyebrow ---------------------------------------------------------

    @Test
    fun eyebrow_light() = captureMealsy("Eyebrow", false) { Eyebrow(text = "Today") }

    @Test
    fun eyebrow_dark() = captureMealsy("Eyebrow", true) { Eyebrow(text = "Today") }

    // --- MealsyToggle: on + off ----------------------------------------------

    @Test
    fun mealsyToggle_on_light() = captureMealsy("MealsyToggle_on", false) {
        MealsyToggle(checked = true, onCheckedChange = {})
    }

    @Test
    fun mealsyToggle_on_dark() = captureMealsy("MealsyToggle_on", true) {
        MealsyToggle(checked = true, onCheckedChange = {})
    }

    @Test
    fun mealsyToggle_off_light() = captureMealsy("MealsyToggle_off", false) {
        MealsyToggle(checked = false, onCheckedChange = {})
    }

    @Test
    fun mealsyToggle_off_dark() = captureMealsy("MealsyToggle_off", true) {
        MealsyToggle(checked = false, onCheckedChange = {})
    }

    // --- InkToast --------------------------------------------------------

    @Test
    fun inkToast_light() = captureMealsy("InkToast", false) {
        InkToast(text = "Meal logged", visible = true)
    }

    @Test
    fun inkToast_dark() = captureMealsy("InkToast", true) {
        InkToast(text = "Meal logged", visible = true)
    }

    // --- SelectableCard: selected + unselected -------------------------------

    @Test
    fun selectableCard_selected_light() = captureMealsy("SelectableCard_selected", false) {
        SelectableCard(
            title = "Lose weight",
            subtitle = "Gradual, sustainable pace",
            selected = true,
            onClick = {},
            leading = { PastelIconCircle(initial = 'L', tone = TagTone.Butter) },
        )
    }

    @Test
    fun selectableCard_selected_dark() = captureMealsy("SelectableCard_selected", true) {
        SelectableCard(
            title = "Lose weight",
            subtitle = "Gradual, sustainable pace",
            selected = true,
            onClick = {},
            leading = { PastelIconCircle(initial = 'L', tone = TagTone.Butter) },
        )
    }

    @Test
    fun selectableCard_unselected_light() = captureMealsy("SelectableCard_unselected", false) {
        SelectableCard(
            title = "Maintain",
            subtitle = "Stay at current weight",
            selected = false,
            onClick = {},
            leading = { PastelIconCircle(initial = 'M', tone = TagTone.Leaf) },
        )
    }

    @Test
    fun selectableCard_unselected_dark() = captureMealsy("SelectableCard_unselected", true) {
        SelectableCard(
            title = "Maintain",
            subtitle = "Stay at current weight",
            selected = false,
            onClick = {},
            leading = { PastelIconCircle(initial = 'M', tone = TagTone.Leaf) },
        )
    }

    // --- FilterChipPill: on + off ---------------------------------------------

    @Test
    fun filterChipPill_on_light() = captureMealsy("FilterChipPill_on", false) {
        FilterChipPill(text = "Breakfast", selected = true, onClick = {})
    }

    @Test
    fun filterChipPill_on_dark() = captureMealsy("FilterChipPill_on", true) {
        FilterChipPill(text = "Breakfast", selected = true, onClick = {})
    }

    @Test
    fun filterChipPill_off_light() = captureMealsy("FilterChipPill_off", false) {
        FilterChipPill(text = "Breakfast", selected = false, onClick = {})
    }

    @Test
    fun filterChipPill_off_dark() = captureMealsy("FilterChipPill_off", true) {
        FilterChipPill(text = "Breakfast", selected = false, onClick = {})
    }

    // --- CircleIconButton --------------------------------------------------

    @Test
    fun circleIconButton_light() = captureMealsy("CircleIconButton", false) {
        CircleIconButton(
            icon = app.mealsy.android.design.icons.MealsyIcons.Gear,
            contentDescription = "Settings",
            onClick = {},
        )
    }

    @Test
    fun circleIconButton_dark() = captureMealsy("CircleIconButton", true) {
        CircleIconButton(
            icon = app.mealsy.android.design.icons.MealsyIcons.Gear,
            contentDescription = "Settings",
            onClick = {},
        )
    }

    // --- StatusPill: ~0.6 eaten (bite notch visible) + StatusPillAwareness --

    @Test
    fun statusPill_60percentEaten_light() = captureMealsy("StatusPill_60pctEaten", false) {
        StatusPill(
            eatenLabel = "1,200 kcal",
            stateLabel = "on track",
            eatenFraction = 0.6f,
            animate = false,
            modifier = Modifier.fillMaxWidth(),
        )
    }

    @Test
    fun statusPill_60percentEaten_dark() = captureMealsy("StatusPill_60pctEaten", true) {
        StatusPill(
            eatenLabel = "1,200 kcal",
            stateLabel = "on track",
            eatenFraction = 0.6f,
            animate = false,
            modifier = Modifier.fillMaxWidth(),
        )
    }

    @Test
    fun statusPillAwareness_light() = captureMealsy("StatusPillAwareness", false) {
        StatusPillAwareness(eatenLabel = "1,340 kcal logged today", modifier = Modifier.fillMaxWidth())
    }

    @Test
    fun statusPillAwareness_dark() = captureMealsy("StatusPillAwareness", true) {
        StatusPillAwareness(eatenLabel = "1,340 kcal logged today", modifier = Modifier.fillMaxWidth())
    }

    // --- ProgressRing ------------------------------------------------------

    @Test
    fun progressRing_light() = captureMealsy("ProgressRing", false) {
        ProgressRing(progress = 0.7f, animate = false)
    }

    @Test
    fun progressRing_dark() = captureMealsy("ProgressRing", true) {
        ProgressRing(progress = 0.7f, animate = false)
    }

    // --- ChatBubble: coach, user, tags + timestamp --------------------------

    @Test
    fun chatBubble_coach_light() = captureMealsy("ChatBubble_coach", false) {
        ChatBubble(text = "Nice work today!", author = ChatBubbleAuthor.Coach)
    }

    @Test
    fun chatBubble_coach_dark() = captureMealsy("ChatBubble_coach", true) {
        ChatBubble(text = "Nice work today!", author = ChatBubbleAuthor.Coach)
    }

    @Test
    fun chatBubble_user_light() = captureMealsy("ChatBubble_user", false) {
        ChatBubble(text = "I had a chicken salad for lunch", author = ChatBubbleAuthor.User)
    }

    @Test
    fun chatBubble_user_dark() = captureMealsy("ChatBubble_user", true) {
        ChatBubble(text = "I had a chicken salad for lunch", author = ChatBubbleAuthor.User)
    }

    @Test
    fun chatBubble_tagsAndTimestamp_light() = captureMealsy("ChatBubble_tagsAndTimestamp", false) {
        ChatBubble(
            text = "Logged: grilled chicken and rice",
            author = ChatBubbleAuthor.Coach,
            timestamp = "9:41 AM",
            tags = {
                TagChip(text = "412 kcal", tone = TagTone.Butter)
                TagChip(text = "USDA verified", tone = TagTone.Powder)
            },
        )
    }

    @Test
    fun chatBubble_tagsAndTimestamp_dark() = captureMealsy("ChatBubble_tagsAndTimestamp", true) {
        ChatBubble(
            text = "Logged: grilled chicken and rice",
            author = ChatBubbleAuthor.Coach,
            timestamp = "9:41 AM",
            tags = {
                TagChip(text = "412 kcal", tone = TagTone.Butter)
                TagChip(text = "USDA verified", tone = TagTone.Powder)
            },
        )
    }

    // --- TypingIndicator -----------------------------------------------------

    @Test
    fun typingIndicator_light() = captureMealsy("TypingIndicator", false) { TypingIndicator() }

    @Test
    fun typingIndicator_dark() = captureMealsy("TypingIndicator", true) { TypingIndicator() }

    // --- BottomNavPill with OliveFab -----------------------------------------

    @Composable
    private fun NavPill() {
        val items = listOf(
            MealsyNavItem(app.mealsy.android.design.icons.MealsyIcons.Home, "Home", "home"),
            MealsyNavItem(app.mealsy.android.design.icons.MealsyIcons.BowlBars, "Meals", "meals"),
            MealsyNavItem(app.mealsy.android.design.icons.MealsyIcons.LineChart, "Trends", "trends"),
            MealsyNavItem(app.mealsy.android.design.icons.MealsyIcons.Chat, "Chat", "chat"),
        )
        BottomNavPill(
            items = items,
            selectedRoute = "home",
            onSelect = {},
            modifier = Modifier.fillMaxWidth(),
            fab = { OliveFab(onClick = {}, contentDescription = "Log a meal") },
        )
    }

    @Test
    fun bottomNavPill_light() = captureMealsy("BottomNavPill_withFab", false) { NavPill() }

    @Test
    fun bottomNavPill_dark() = captureMealsy("BottomNavPill_withFab", true) { NavPill() }
}
