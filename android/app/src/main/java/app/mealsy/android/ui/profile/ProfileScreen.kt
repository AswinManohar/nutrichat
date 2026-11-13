package app.mealsy.android.ui.profile

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.R
import app.mealsy.android.design.components.Eyebrow
import app.mealsy.android.design.components.InsetDivider
import app.mealsy.android.design.components.ListContainer
import app.mealsy.android.design.components.ListRow
import app.mealsy.android.design.components.MealsyButton
import app.mealsy.android.design.components.MealsyButtonStyle
import app.mealsy.android.design.components.formatThousands
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.design.theme.mealsyScreenPadding
import app.mealsy.android.ui.onboarding.DietaryPref
import app.mealsy.android.ui.onboarding.PREF_LABELS
import app.mealsy.android.ui.settings.OnResume
import app.mealsy.android.ui.settings.SettingsUiState
import app.mealsy.android.ui.settings.SettingsViewModel

/**
 * The Profile tab: who is signed in, a summary row per settings area (each
 * opens its own sub-screen), and sign out. State comes from
 * [SettingsViewModel], which the sub-screens share by being scoped to this
 * tab's back stack entry (see `AppNav`).
 *
 * @param onOpenGoals Opens Goals and targets.
 * @param onOpenFood Opens Food preferences.
 * @param onOpenReminders Opens Reminders.
 * @param onOpenAccount Opens Account and privacy.
 */
@Composable
fun ProfileScreen(
    onOpenGoals: () -> Unit,
    onOpenFood: () -> Unit,
    onOpenReminders: () -> Unit,
    onOpenAccount: () -> Unit,
    viewModel: SettingsViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    // The reminders summary must follow a notification permission changed in
    // system settings (#44), same as the Reminders sub-screen.
    OnResume(viewModel::onResume)
    ProfileContent(
        uiState = uiState,
        onOpenGoals = onOpenGoals,
        onOpenFood = onOpenFood,
        onOpenReminders = onOpenReminders,
        onOpenAccount = onOpenAccount,
        onSignOut = viewModel::signOut,
        modifier = Modifier.fillMaxSize(),
    )
}

/** Stateless render of [ProfileScreen], driven by hand-built state in goldens. */
@Composable
fun ProfileContent(
    uiState: SettingsUiState,
    onOpenGoals: () -> Unit,
    onOpenFood: () -> Unit,
    onOpenReminders: () -> Unit,
    onOpenAccount: () -> Unit,
    onSignOut: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.verticalScroll(rememberScrollState()).mealsyScreenPadding()) {
        ProfileHeader(name = uiState.firstName, email = uiState.email)

        // The "Care profile" card goes here (between the header and EATING).

        Spacer(modifier = Modifier.height(28.dp))
        Eyebrow(text = stringResource(R.string.profile_section_eating))
        Spacer(modifier = Modifier.height(10.dp))
        ListContainer {
            ListRow(
                label = stringResource(R.string.profile_goals),
                onClick = onOpenGoals,
                trailingText = kcalGoalLabel(uiState),
            )
            InsetDivider()
            ListRow(
                label = stringResource(R.string.profile_food),
                onClick = onOpenFood,
                trailingText = firstPrefLabel(uiState),
            )
        }

        Spacer(modifier = Modifier.height(24.dp))
        Eyebrow(text = stringResource(R.string.profile_section_app))
        Spacer(modifier = Modifier.height(10.dp))
        ListContainer {
            ListRow(
                label = stringResource(R.string.profile_reminders),
                onClick = onOpenReminders,
                trailingText =
                    stringResource(
                        if (uiState.reminderEnabled) R.string.profile_reminders_on else R.string.profile_reminders_off,
                    ),
            )
            InsetDivider()
            ListRow(label = stringResource(R.string.profile_account), onClick = onOpenAccount)
        }

        Spacer(modifier = Modifier.height(28.dp))
        MealsyButton(
            text = stringResource(R.string.settings_sign_out),
            onClick = onSignOut,
            modifier = Modifier.fillMaxWidth(),
            style = MealsyButtonStyle.Secondary,
        )
    }
}

/** Initials avatar, display name and email. */
@Composable
private fun ProfileHeader(
    name: String,
    email: String,
) {
    val colors = MealsyTheme.colors
    val initial = (name.ifBlank { email }).firstOrNull()?.uppercaseChar()
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Surface(
            modifier = Modifier.size(56.dp).clearAndSetSemantics {},
            shape = CircleShape,
            color = colors.surface,
        ) {
            Box(contentAlignment = Alignment.Center) {
                if (initial != null) {
                    Text(text = initial.toString(), style = MealsyType.section, color = colors.ink)
                } else {
                    Icon(imageVector = MealsyIcons.User, contentDescription = null, tint = colors.ink)
                }
            }
        }
        Column {
            if (name.isNotBlank()) {
                Text(text = name, style = MealsyType.section, color = colors.ink)
            }
            if (email.isNotBlank()) {
                Text(text = email, style = MealsyType.body, color = colors.muted)
            }
        }
    }
}

@Composable
private fun kcalGoalLabel(uiState: SettingsUiState): String? =
    if (uiState.trackingMode == "goals") {
        stringResource(R.string.profile_kcal_goal, formatThousands(uiState.kcalGoal.toInt()))
    } else {
        null
    }

@Composable
private fun firstPrefLabel(uiState: SettingsUiState): String? =
    DietaryPref.entries
        .firstOrNull { it.key in uiState.dietaryPrefs }
        ?.let { stringResource(PREF_LABELS.getValue(it)) }
