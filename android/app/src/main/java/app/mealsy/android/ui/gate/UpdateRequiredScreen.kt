package app.mealsy.android.ui.gate

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp

/**
 * Blocking screen shown when the installed app is below the backend's
 * minimum supported version. There is no bypass — the only action is to
 * open the Play Store listing to update.
 */
@Composable
fun UpdateRequiredScreen() {
    val context = LocalContext.current
    val packageName = context.packageName

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = "Update required",
            style = MaterialTheme.typography.headlineMedium,
        )
        Text(
            text = "This version of Mealsy is no longer supported. Please update to continue.",
            modifier = Modifier.padding(top = 16.dp),
        )
        Button(
            onClick = {
                val marketIntent = Intent(
                    Intent.ACTION_VIEW,
                    Uri.parse("market://details?id=$packageName"),
                )
                try {
                    context.startActivity(marketIntent)
                } catch (exc: ActivityNotFoundException) {
                    val webIntent = Intent(
                        Intent.ACTION_VIEW,
                        Uri.parse("https://play.google.com/store/apps/details?id=$packageName"),
                    )
                    context.startActivity(webIntent)
                }
            },
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 24.dp),
        ) {
            Text("Update on Play Store")
        }
    }
}
