package app.mealsy.android.ui.login

import android.app.Activity
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
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

/**
 * Hilt/state entry point for the login screen. Collects
 * [LoginViewModel.uiState] and delegates all rendering to the stateless
 * [LoginContent] so screenshot tests can exercise the UI without a Hilt
 * graph.
 */
@Composable
fun LoginScreen(viewModel: LoginViewModel = hiltViewModel()) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var email by remember { mutableStateOf("") }

    LoginContent(
        uiState = uiState,
        email = email,
        onEmailChange = { email = it },
        onSubmitEmail = { viewModel.submitEmail(email) },
        onSignInWithGoogle = {
            (context as? Activity)?.let { viewModel.signInWithGoogle(it) }
        },
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
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    val statusBarTop = WindowInsets.statusBars.asPaddingValues().calculateTopPadding()

    Surface(modifier = modifier.fillMaxSize(), color = colors.canvas) {
        Column(
            modifier =
                Modifier
                    .fillMaxSize()
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
                }

                else -> {
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

                    if (uiState is LoginUiState.Error) {
                        Text(
                            text =
                                stringResource(
                                    when (uiState.kind) {
                                        LoginErrorKind.InvalidEmail -> R.string.login_error_invalid_email
                                        LoginErrorKind.MagicLinkFailed -> R.string.login_error_magic_link_failed
                                        LoginErrorKind.GoogleSignInFailed -> R.string.login_error_google_sign_in_failed
                                    },
                                ),
                            style = MealsyType.body,
                            color = colors.muted,
                            modifier = Modifier.padding(top = 8.dp),
                        )
                    }

                    MealsyButton(
                        text = stringResource(R.string.login_send_magic_link),
                        onClick = onSubmitEmail,
                        modifier =
                            Modifier
                                .fillMaxWidth()
                                .padding(top = 16.dp),
                    )

                    MealsyButton(
                        text = stringResource(R.string.login_continue_with_google),
                        onClick = onSignInWithGoogle,
                        style = MealsyButtonStyle.Secondary,
                        modifier =
                            Modifier
                                .fillMaxWidth()
                                .padding(top = 10.dp),
                    )
                }
            }
        }
    }
}
