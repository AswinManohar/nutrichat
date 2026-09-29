package app.mealsy.android.ui.login

import androidx.activity.compose.BackHandler
import androidx.annotation.StringRes
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.R
import app.mealsy.android.design.components.MealsyButton
import app.mealsy.android.design.components.MealsyButtonStyle
import app.mealsy.android.design.components.PillInput
import app.mealsy.android.design.mascot.Olli
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.ui.common.findActivity

/**
 * Hilt/state entry point for the login screen. Collects
 * [LoginViewModel.uiState] and delegates all rendering to the stateless
 * [LoginContent] so screenshot tests can exercise the UI without a Hilt
 * graph.
 */
@Composable
fun LoginScreen(viewModel: LoginViewModel = hiltViewModel()) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val googleSignInAvailable by viewModel.googleSignInAvailable.collectAsStateWithLifecycle()
    val googleBusy by viewModel.googleBusy.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var email by remember { mutableStateOf("") }

    LoginContent(
        uiState = uiState,
        email = email,
        onEmailChange = { email = it },
        onSubmitEmail = { viewModel.submitEmail(email) },
        googleSignInAvailable = googleSignInAvailable,
        googleBusy = googleBusy,
        onSignInWithGoogle = {
            context.findActivity()?.let { viewModel.signInWithGoogle(it) }
        },
        onBackToEmail = viewModel::backToEmail,
        onResendMagicLink = viewModel::resendMagicLink,
    )
}

/**
 * The stateless login screen content, re-skinned to the Mealsy design
 * system. Behaviour (validation, magic-link, Google sign-in) all lives in
 * [LoginViewModel]; this composable only renders [uiState].
 */
@Composable
fun LoginContent(
    uiState: LoginUiState,
    email: String,
    onEmailChange: (String) -> Unit,
    onSubmitEmail: () -> Unit,
    onSignInWithGoogle: () -> Unit,
    googleSignInAvailable: Boolean = true,
    googleBusy: Boolean = false,
    onBackToEmail: () -> Unit = {},
    onResendMagicLink: () -> Unit = {},
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    val statusBarTop = WindowInsets.statusBars.asPaddingValues().calculateTopPadding()

    // The "check your email" step is a second in-screen step, same shape as
    // onboarding's (#29) — system Back should return to email entry rather
    // than exit the screen.
    BackHandler(enabled = uiState is LoginUiState.AwaitingEmail) {
        onBackToEmail()
    }

    Surface(modifier = modifier.fillMaxSize(), color = colors.canvas) {
        Column(
            modifier =
                Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(top = statusBarTop + 24.dp, start = 24.dp, end = 24.dp, bottom = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Olli(size = 150.dp)

            Text(
                text = stringResource(R.string.login_title),
                style = MealsyType.display,
                color = colors.ink,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 16.dp, bottom = 24.dp),
            )

            when (uiState) {
                is LoginUiState.AwaitingEmail -> {
                    Text(
                        text = stringResource(R.string.login_awaiting_email),
                        style = MealsyType.body,
                        color = colors.muted,
                        textAlign = TextAlign.Center,
                    )

                    val cooldown = uiState.resendCooldownSeconds
                    MealsyButton(
                        text =
                            if (cooldown > 0) {
                                stringResource(R.string.login_resend_link_cooldown, cooldown)
                            } else {
                                stringResource(R.string.login_resend_link)
                            },
                        onClick = onResendMagicLink,
                        enabled = cooldown <= 0,
                        style = MealsyButtonStyle.Secondary,
                        modifier =
                            Modifier
                                .fillMaxWidth()
                                .padding(top = 16.dp),
                    )

                    val useDifferentEmail = stringResource(R.string.login_use_different_email)
                    Text(
                        text = useDifferentEmail,
                        style = MealsyType.body,
                        color = colors.ink,
                        textAlign = TextAlign.Center,
                        modifier =
                            Modifier
                                .padding(top = 16.dp)
                                .clickable(
                                    role = Role.Button,
                                    onClickLabel = useDifferentEmail,
                                    onClick = onBackToEmail,
                                ),
                    )
                }

                else -> {
                    val error = (uiState as? LoginUiState.Error)?.kind

                    // Google is the primary way in (#32). Hidden, rather than
                    // shown-then-erroring, when Supabase reports the provider
                    // is off — see GoogleAuthAvailabilityGateway. Then email
                    // becomes the primary button.
                    if (googleSignInAvailable) {
                        MealsyButton(
                            text = stringResource(R.string.login_continue_with_google),
                            onClick = onSignInWithGoogle,
                            enabled = !googleBusy,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        if (error != null && error.isGoogleError()) {
                            LoginErrorText(error)
                        }
                        Text(
                            text = stringResource(R.string.login_or_use_email),
                            style = MealsyType.label,
                            color = colors.muted,
                            textAlign = TextAlign.Center,
                            modifier = Modifier.padding(top = 20.dp, bottom = 12.dp),
                        )
                    }

                    val emailFieldDescription = stringResource(R.string.login_email_field_description)
                    PillInput(
                        value = email,
                        onValueChange = onEmailChange,
                        placeholder = stringResource(R.string.login_email_placeholder),
                        modifier =
                            Modifier
                                .fillMaxWidth()
                                .semantics { contentDescription = emailFieldDescription },
                        keyboardOptions =
                            KeyboardOptions(
                                keyboardType = KeyboardType.Email,
                                imeAction = ImeAction.Done,
                            ),
                        keyboardActions = KeyboardActions(onDone = { onSubmitEmail() }),
                    )

                    if (error != null && (!googleSignInAvailable || !error.isGoogleError())) {
                        LoginErrorText(error)
                    }

                    MealsyButton(
                        text = stringResource(R.string.login_send_magic_link),
                        onClick = onSubmitEmail,
                        style = if (googleSignInAvailable) MealsyButtonStyle.Secondary else MealsyButtonStyle.Primary,
                        modifier =
                            Modifier
                                .fillMaxWidth()
                                .padding(top = 16.dp),
                    )
                }
            }
        }
    }
}

/** The muted one-line error under whichever control caused [kind]. */
@Composable
private fun LoginErrorText(kind: LoginErrorKind) {
    Text(
        text = stringResource(kind.messageRes()),
        style = MealsyType.body,
        color = MealsyTheme.colors.muted,
        modifier = Modifier.padding(top = 8.dp),
    )
}

/** String resource for [LoginErrorKind]; shared with the onboarding account step. */
@StringRes
internal fun LoginErrorKind.messageRes(): Int =
    when (this) {
        LoginErrorKind.InvalidEmail -> R.string.login_error_invalid_email
        LoginErrorKind.MagicLinkFailed -> R.string.login_error_magic_link_failed
        LoginErrorKind.GoogleSignInFailed -> R.string.login_error_google_sign_in_failed
        LoginErrorKind.GoogleNoAccount -> R.string.login_error_google_no_account
        LoginErrorKind.GoogleNotConfigured -> R.string.login_error_google_not_configured
        LoginErrorKind.GoogleUnavailable -> R.string.login_error_google_unavailable
        LoginErrorKind.Offline -> R.string.error_offline
        LoginErrorKind.LinkExpired -> R.string.login_error_link_expired
        LoginErrorKind.RateLimited -> R.string.login_error_rate_limited
    }
