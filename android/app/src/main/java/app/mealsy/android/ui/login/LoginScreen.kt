package app.mealsy.android.ui.login

import android.app.Activity
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle

@Composable
fun LoginScreen(viewModel: LoginViewModel = hiltViewModel()) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var email by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text(text = "Mealsy", style = MaterialTheme.typography.headlineMedium)

        when (uiState) {
            LoginUiState.AwaitingEmail -> {
                Text(
                    text = "Check your email for a magic link.",
                    modifier = Modifier.padding(top = 16.dp),
                )
            }

            else -> {
                OutlinedTextField(
                    value = email,
                    onValueChange = { email = it },
                    label = { Text("Email") },
                    singleLine = true,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 16.dp),
                )

                if (uiState is LoginUiState.Error) {
                    Text(
                        text = (uiState as LoginUiState.Error).message,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                }

                Button(
                    onClick = { viewModel.submitEmail(email) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 16.dp),
                ) {
                    Text("Send magic link")
                }

                OutlinedButton(
                    onClick = {
                        (context as? Activity)?.let { viewModel.signInWithGoogle(it) }
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 8.dp),
                ) {
                    Text("Continue with Google")
                }
            }
        }
    }
}
