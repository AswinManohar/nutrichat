package app.mealsy.android.ui.gate

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import app.mealsy.android.R
import app.mealsy.android.design.components.MealsyButton
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * Blocking screen shown when the installed app is below the backend's
 * minimum supported version. There is no bypass — the only action is to
 * open the Play Store listing to update.
 */
@Composable
fun UpdateRequiredScreen() {
    val context = LocalContext.current
    val packageName = context.packageName

    UpdateRequiredContent(
        onUpdate = {
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
    )
}

/**
 * The stateless update-required content, re-skinned to the Mealsy design
 * system. The version-gate logic that decides whether to show this screen
 * lives in `AppNav.kt` and is untouched by this composable.
 */
@Composable
fun UpdateRequiredContent(onUpdate: () -> Unit, modifier: Modifier = Modifier) {
    val colors = MealsyTheme.colors

    Surface(modifier = modifier.fillMaxSize(), color = colors.canvas) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(24.dp),
            verticalArrangement = androidx.compose.foundation.layout.Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = stringResource(R.string.update_required_title),
                style = MealsyType.display,
                color = colors.ink,
                textAlign = TextAlign.Center,
            )
            Text(
                text = stringResource(R.string.update_required_body),
                style = MealsyType.body,
                color = colors.muted,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 16.dp),
            )
            MealsyButton(
                text = stringResource(R.string.update_required_cta),
                onClick = onUpdate,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 24.dp),
            )
        }
    }
}
