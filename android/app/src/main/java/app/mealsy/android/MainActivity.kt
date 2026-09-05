package app.mealsy.android

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import app.mealsy.android.push.EXTRA_OPEN_CHAT
import app.mealsy.android.ui.AppNav
import dagger.hilt.android.AndroidEntryPoint
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.gotrue.handleDeeplinks
import javax.inject.Inject

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    // supabase-kt's Auth deep-link handling is exposed as an extension on
    // SupabaseClient (handleDeeplinks), not on Auth itself, so this needs
    // the client rather than SessionManager/AuthGateway.
    @Inject
    lateinit var supabaseClient: SupabaseClient

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        supabaseClient.handleDeeplinks(intent)
        logNotificationOpenIfPresent(intent)

        setContent {
            MaterialTheme {
                AppNav()
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        supabaseClient.handleDeeplinks(intent)
        logNotificationOpenIfPresent(intent)
    }

    /**
     * `MealsyMessagingService` launches this activity directly for a
     * `mealsy://chat` push (see [EXTRA_OPEN_CHAT]'s doc comment for why
     * there's no dedicated intent-filter/route for it): `AppNav` already
     * routes any `SignedIn` session straight to `ChatScreen`, so there's
     * nothing further to navigate here. This only exists as the extension
     * point a future multi-screen deep link would branch on.
     */
    private fun logNotificationOpenIfPresent(intent: Intent) {
        if (intent.getBooleanExtra(EXTRA_OPEN_CHAT, false)) {
            // No-op today — see doc comment above.
        }
    }
}
