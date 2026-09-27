package app.mealsy.android

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.push.EXTRA_OPEN_CHAT
import app.mealsy.android.ui.AppNav
import app.mealsy.android.ui.AppNavViewModel
import app.mealsy.data.auth.AuthCallbackErrors
import app.mealsy.data.auth.parseAuthCallbackError
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

    // #34: handleDeeplinks only acts on a `code` param and silently no-ops
    // otherwise, so an error redirect (e.g. an expired/already-used magic
    // link) needs its own parse here and a way to reach LoginViewModel,
    // which owns the login screen's UI state — see AuthCallbackErrors' kdoc.
    @Inject
    lateinit var authCallbackErrors: AuthCallbackErrors

    // Same Hilt-provided `AppNavViewModel` instance `AppNav()`'s `hiltViewModel()`
    // resolves to below (both are scoped to this Activity) — obtained here too
    // so the splash screen's keep-on-screen predicate can poll its startup state
    // before `setContent`/`AppNav()` ever composes.
    private val appNavViewModel: AppNavViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        val splashScreen = installSplashScreen()
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        supabaseClient.handleDeeplinks(intent)
        handleAuthCallbackError(intent)
        logNotificationOpenIfPresent(intent)

        // #49 item 4: one loading visual at startup, not three — hold the
        // branded splash on screen until the version gate AND the
        // session/onboarding check have both resolved, instead of dropping to
        // a spinner (then a second spinner, then a bare "Loading…" screen)
        // while those are still in flight.
        splashScreen.setKeepOnScreenCondition { !appNavViewModel.isStartupReady() }

        setContent {
            MealsyTheme {
                AppNav()
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        supabaseClient.handleDeeplinks(intent)
        handleAuthCallbackError(intent)
        logNotificationOpenIfPresent(intent)
    }

    private fun handleAuthCallbackError(intent: Intent) {
        val uri = intent.data?.toString() ?: return
        parseAuthCallbackError(uri)?.let { authCallbackErrors.publish(it) }
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
