package app.mealsy.android.ui

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.isImeVisible
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.navigation.NavDestination
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import app.mealsy.android.BuildConfig
import app.mealsy.android.R
import app.mealsy.android.design.components.BottomNavPill
import app.mealsy.android.design.components.MealsyNavItem
import app.mealsy.android.design.components.OliveFab
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.LocalReducedMotion
import app.mealsy.android.di.AppVersionCode
import app.mealsy.android.push.PushRegistrar
import app.mealsy.android.ui.chat.ChatScreen
import app.mealsy.android.ui.gate.UpdateRequiredScreen
import app.mealsy.android.ui.home.HomeScreen
import app.mealsy.android.ui.login.LoginScreen
import app.mealsy.android.ui.mealdetail.MealDetailScreen
import app.mealsy.android.ui.meals.MealTypeListScreen
import app.mealsy.android.ui.mymeals.MyMealsScreen
import app.mealsy.android.ui.onboarding.OnboardingScreen
import app.mealsy.android.ui.settings.SettingsScreen
import app.mealsy.android.ui.trends.TrendsScreen
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.auth.SessionManager
import app.mealsy.data.auth.SessionState
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.data.repo.ProfileRefresher
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import java.io.IOException
import javax.inject.Inject

private const val APP_META_TIMEOUT_MS = 3_000L

/** Push-screen (meal detail, settings, My Meal, onboarding, login) transition duration — #49 item 1. */
private const val PUSH_TRANSITION_MS = 220

/** Bottom-nav tab-switch transition duration — kept short/near-instant so it doesn't read as lag. */
private const val TAB_TRANSITION_MS = 120

private const val ROUTE_LOGIN = "login"
private const val ROUTE_HOME = "home"
private const val ROUTE_CHAT = "chat"
private const val ARG_QUICK_LOG = "quickLog"
private const val ROUTE_CHAT_PATTERN = "$ROUTE_CHAT?$ARG_QUICK_LOG={$ARG_QUICK_LOG}"
private const val ROUTE_ONBOARDING = "onboarding"
private const val ARG_START_STEP = "startStep"
private const val ROUTE_ONBOARDING_PATTERN = "$ROUTE_ONBOARDING?$ARG_START_STEP={$ARG_START_STEP}"
private const val ROUTE_TRENDS = "trends"
private const val ROUTE_MY_MEALS = "my-meals"
private const val ROUTE_SETTINGS = "settings"
private const val ROUTE_MEAL_TYPE = "meals"
private const val ARG_MEAL_TYPE = "mealType"
private const val ROUTE_MEAL_TYPE_PATTERN = "$ROUTE_MEAL_TYPE/{$ARG_MEAL_TYPE}"
private const val ROUTE_MEAL = "meal"
private const val ARG_MEAL_ID = "mealId"
private const val ROUTE_MEAL_PATTERN = "$ROUTE_MEAL/{$ARG_MEAL_ID}"
private const val ROUTE_MY_MEAL = "my-meal"
private const val ARG_ID = "id"
private const val ROUTE_MY_MEAL_PATTERN = "$ROUTE_MY_MEAL/{$ARG_ID}"

/** Builds a navigable route to onboarding starting at [startStep] (0 = welcome). */
private fun onboardingRoute(startStep: Int): String = "$ROUTE_ONBOARDING?$ARG_START_STEP=$startStep"

/** Builds a navigable route to the meal-type list for [mealType] (e.g. "breakfast"). */
private fun mealTypeRoute(mealType: String): String = "$ROUTE_MEAL_TYPE/$mealType"

/** Builds a navigable route to the meal-detail screen (logged mode) for [mealId]. */
private fun mealRoute(mealId: String): String = "$ROUTE_MEAL/$mealId"

/** Builds a navigable route to the meal-detail screen (My-Meal mode) for [id]. */
private fun myMealRoute(id: String): String = "$ROUTE_MY_MEAL/$id"

/** Builds the FAB's quick-log chat route — chat with [ARG_QUICK_LOG] forced true. */
private fun quickLogChatRoute(): String = "$ROUTE_CHAT?$ARG_QUICK_LOG=true"

/**
 * The four bottom-nav tab destinations, in display order, per the "Bottom
 * nav + FAB" spec: Home, Meals (My Meals), Trends, Chat. Settings is
 * deliberately not a tab — it's reached from Home's gear button instead.
 */
private fun bottomNavItems(
    homeLabel: String,
    mealsLabel: String,
    trendsLabel: String,
    chatLabel: String,
): List<MealsyNavItem> =
    listOf(
        MealsyNavItem(MealsyIcons.Home, homeLabel, ROUTE_HOME),
        MealsyNavItem(MealsyIcons.BowlBars, mealsLabel, ROUTE_MY_MEALS),
        MealsyNavItem(MealsyIcons.LineChart, trendsLabel, ROUTE_TRENDS),
        MealsyNavItem(MealsyIcons.Chat, chatLabel, ROUTE_CHAT),
    )

/**
 * Maps a live [NavDestination] back to the bottom-nav tab route it belongs
 * to, or `null` if it isn't one of the four tabs (and so the pill should be
 * hidden and nothing should show as selected). [NavDestination.route] on a
 * parameterized destination is the *pattern* string (e.g.
 * `"chat?quickLog={quickLog}"`), not the concrete URI that was navigated to,
 * so the chat tab needs an explicit pattern match rather than an equality
 * check against [ROUTE_CHAT].
 */
internal fun NavDestination?.tabRoute(): String? =
    when (this?.route) {
        ROUTE_HOME -> ROUTE_HOME
        ROUTE_MY_MEALS -> ROUTE_MY_MEALS
        ROUTE_TRENDS -> ROUTE_TRENDS
        ROUTE_CHAT_PATTERN -> ROUTE_CHAT
        else -> null
    }

/** Result of the startup version-gate check. */
sealed interface GateState {
    data object Checking : GateState

    data object Ready : GateState

    data object UpdateRequired : GateState
}

/**
 * Whether a signed-in user still needs to complete goal setup
 * ([GoalsRepository.get] returning `null`, i.e. `GET /goals` 404ing).
 * [Unknown] is the state while that check is in flight (or hasn't started
 * yet) — [AppNav] blocks routing on it, just like [GateState.Checking],
 * so home never flashes underneath onboarding.
 */
sealed interface OnboardingState {
    data object Unknown : OnboardingState

    data object Needed : OnboardingState

    data object NotNeeded : OnboardingState
}

/** Returns true when the installed build is older than the backend's minimum supported version. */
fun isUpdateRequired(
    currentVersionCode: Int,
    minSupportedVersionCode: Int,
): Boolean = currentVersionCode < minSupportedVersionCode

/**
 * `currentVersionCode` is [BuildConfig.VERSION_CODE] in production, bound via [AppVersionCode]
 * in `app.mealsy.android.di.AppModule` since Hilt has no visibility into `BuildConfig`. Being a
 * constructor param (rather than reading BuildConfig directly) lets tests override it and make
 * the gate's fail-open/fail-closed branches plain-JVM-testable without Robolectric.
 */
@HiltViewModel
class AppNavViewModel
    @Inject
    constructor(
        private val api: MealsyApi,
        sessionManager: SessionManager,
        @AppVersionCode private val currentVersionCode: Int,
        private val pushRegistrar: PushRegistrar,
        private val goalsRepository: GoalsRepository,
        private val profileRefresher: ProfileRefresher,
    ) : ViewModel() {
        val sessionState: StateFlow<SessionState> = sessionManager.sessionState

        private val _gateState = MutableStateFlow<GateState>(GateState.Checking)
        val gateState: StateFlow<GateState> = _gateState.asStateFlow()

        private val _onboardingState = MutableStateFlow<OnboardingState>(OnboardingState.Unknown)
        val onboardingState: StateFlow<OnboardingState> = _onboardingState.asStateFlow()

        /**
         * Guards [checkOnboarding] against re-running for every [SessionState.SignedIn]
         * emission (e.g. a token refresh producing a new, distinct `SignedIn` value)
         * — the onboarding check should run once per sign-in, not once per emission.
         * Reset on sign-out so a different user signing in on the same process gets
         * a fresh check.
         */
        private var onboardingChecked = false

        init {
            checkGate()
            observeSignIn()
        }

        /**
         * FCM registration (Task 9) needs a signed-in user (`POST /devices/register`
         * requires auth), so it's driven from [sessionState] here rather than at
         * app startup — this is the "sensible place" the task brief calls for,
         * chosen because [AppNavViewModel] already observes [sessionState] for
         * routing and outlives any single screen. The onboarding check (Task 10)
         * rides along the same collector for the same reason — it also needs a
         * signed-in user's token (`GET /goals` requires auth).
         */
        private fun observeSignIn() {
            viewModelScope.launch {
                sessionState.collect { state ->
                    when (state) {
                        is SessionState.SignedIn -> {
                            profileRefresher.refreshProfileFromMetadata()
                            pushRegistrar.ensureRegistered()
                            checkOnboarding()
                        }
                        SessionState.SignedOut -> {
                            onboardingChecked = false
                            _onboardingState.value = OnboardingState.Unknown
                        }
                        SessionState.Loading -> Unit
                    }
                }
            }
        }

        private suspend fun checkOnboarding() {
            if (onboardingChecked) return
            onboardingChecked = true
            _onboardingState.value =
                try {
                    if (goalsRepository.get() == null) OnboardingState.Needed else OnboardingState.NotNeeded
                } catch (exc: IOException) {
                    // Offline — don't brick startup waiting on a goals check that can't
                    // complete; treat as "already onboarded" and let the user into chat.
                    // (A user genuinely mid-onboarding will just see the onboarding
                    // screen again once they have connectivity and re-open the app.)
                    OnboardingState.NotNeeded
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: Exception) {
                    OnboardingState.NotNeeded
                }
        }

        /**
         * Called once [app.mealsy.android.ui.onboarding.OnboardingScreen] finishes
         * (save or skip both succeeded). Without this, [onboardingState] would stay
         * [OnboardingState.Needed] for the rest of the process, and a later distinct
         * [SessionState.SignedIn] emission (e.g. a token refresh) would route the
         * user straight back to onboarding.
         */
        fun onOnboardingComplete() {
            _onboardingState.value = OnboardingState.NotNeeded
        }

        private fun checkGate() {
            viewModelScope.launch {
                _gateState.value =
                    try {
                        val meta = withTimeout(APP_META_TIMEOUT_MS) { api.appMeta() }
                        if (isUpdateRequired(currentVersionCode, meta.minSupportedVersionCode)) {
                            GateState.UpdateRequired
                        } else {
                            GateState.Ready
                        }
                    } catch (exc: TimeoutCancellationException) {
                        // 3s timeout — treat as a failed check, per the spec "failure = proceed".
                        GateState.Ready
                    } catch (exc: CancellationException) {
                        throw exc
                    } catch (exc: Exception) {
                        // appMeta() unreachable/erroring — same "failure = proceed" contract.
                        GateState.Ready
                    }
            }
        }
    }

/**
 * Pure routing decision extracted so it's unit-testable from a plain JVM test
 * (composable navigation logic isn't reachable from [AppNavViewModel]'s
 * tests otherwise). Returns `null` while the decision isn't resolvable yet —
 * callers must not navigate on a `null` result.
 */
internal fun startRouteFor(
    sessionState: SessionState,
    onboardingState: OnboardingState,
): String? =
    when (sessionState) {
        SessionState.SignedOut -> onboardingRoute(startStep = 0)
        is SessionState.SignedIn ->
            when (onboardingState) {
                OnboardingState.Needed -> onboardingRoute(startStep = 1)
                OnboardingState.NotNeeded -> ROUTE_HOME
                OnboardingState.Unknown -> null
            }
        SessionState.Loading -> null
    }

/**
 * The floating bottom nav pill + FAB, extracted so
 * [app.mealsy.android.ui.AppShellGoldenTest]-style goldens can render exactly
 * what [AppNav] composes rather than a hand-copied stand-in.
 *
 * @param selectedRoute The active tab route (one of [ROUTE_HOME],
 *   [ROUTE_MY_MEALS], [ROUTE_TRENDS], [ROUTE_CHAT]).
 * @param onSelect Invoked with a tab route when a nav icon is tapped.
 * @param onFabClick Invoked when the centered FAB is tapped (quick log).
 */
@Composable
internal fun MealsyBottomBar(
    selectedRoute: String,
    onSelect: (String) -> Unit,
    onFabClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val items =
        bottomNavItems(
            homeLabel = stringResource(R.string.nav_home),
            mealsLabel = stringResource(R.string.nav_my_meals),
            trendsLabel = stringResource(R.string.nav_trends),
            chatLabel = stringResource(R.string.nav_chat),
        )
    BottomNavPill(
        items = items,
        selectedRoute = selectedRoute,
        onSelect = onSelect,
        modifier = modifier,
        fab = {
            OliveFab(
                onClick = onFabClick,
                contentDescription = stringResource(R.string.nav_fab_quick_log),
            )
        },
    )
}

/**
 * App-level navigation host.
 *
 * On startup, blocks on the version gate ([AppNavViewModel.gateState]); once
 * clear, routes between the onboarding welcome, `home`, and onboarding's
 * later steps based on [SessionManager]'s [SessionState] and
 * [AppNavViewModel.onboardingState] (see [startRouteFor]) so a sign-in/out
 * anywhere in the tree updates navigation. Signed-out users land on the
 * onboarding welcome (step 0), which is the graph's start destination; the
 * existing `login` route is reached from there via
 * [app.mealsy.android.ui.onboarding.OnboardingScreen]'s `onNavigateToLogin`
 * and is otherwise unchanged.
 *
 * The bottom nav pill + FAB ([MealsyBottomBar]) is composed as a [Box]
 * overlay on top of the [NavHost], not as a `Scaffold` `bottomBar` — the
 * design floats the pill 26dp above the bottom edge, overlapping content
 * rather than pushing it up, and every screen already reserves the matching
 * 120dp of bottom clearance itself via `Modifier.mealsyScreenPadding()`. A
 * `Scaffold`+`bottomBar` would instead hand back an `innerPadding` sized to
 * the bar's actual (non-floating) height and double up that clearance.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun AppNav(navController: NavHostController = rememberNavController()) {
    val viewModel: AppNavViewModel = hiltViewModel()
    val gateState by viewModel.gateState.collectAsStateWithLifecycle()

    when (gateState) {
        GateState.Checking -> {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        }

        GateState.UpdateRequired -> UpdateRequiredScreen()

        GateState.Ready -> {
            val sessionState by viewModel.sessionState.collectAsStateWithLifecycle()
            val onboardingState by viewModel.onboardingState.collectAsStateWithLifecycle()

            // A signed-in user whose onboarding check hasn't resolved yet must not
            // be routed anywhere — wait rather than briefly flashing home then
            // jumping to onboarding (or vice versa).
            val awaitingOnboardingCheck =
                sessionState is SessionState.SignedIn && onboardingState is OnboardingState.Unknown

            if (sessionState == SessionState.Loading || awaitingOnboardingCheck) {
                // Session status isn't known yet — avoid flashing LoginScreen under the
                // NavHost before the first real sessionState value arrives.
                Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
            } else {
                // Login/onboarding/settings/meal-detail render with no bottom nav —
                // only the four tab destinations (home/my-meals/trends/chat) get it.
                // An unrecognized route (including these) maps to `null` here, so
                // the pill defaults to hidden rather than shown.
                val backStackEntry by navController.currentBackStackEntryAsState()
                val activeTab = backStackEntry?.destination?.tabRoute()

                // #49 item 1: Navigation-Compose 2.8's un-set default is a 700ms
                // crossfade on every destination change. Push screens (meal
                // detail, settings, onboarding, login) get a slide+fade at the
                // product register's ~220ms; the four tab destinations override
                // this per-`composable` below with a near-instant fade instead,
                // so switching tabs doesn't feel like navigating "into" a screen.
                // Both durations collapse to 0 (a snap) under ReducedMotion.
                val reducedMotion = LocalReducedMotion.current
                val pushMs = if (reducedMotion) 0 else PUSH_TRANSITION_MS
                val tabMs = if (reducedMotion) 0 else TAB_TRANSITION_MS
                val pushEasing = FastOutSlowInEasing

                Box(modifier = Modifier.fillMaxSize()) {
                    NavHost(
                        navController = navController,
                        startDestination = onboardingRoute(startStep = 0),
                        modifier = Modifier.fillMaxSize(),
                        enterTransition = {
                            slideInHorizontally(tween(pushMs, easing = pushEasing)) { it / 4 } +
                                fadeIn(tween(pushMs, easing = pushEasing))
                        },
                        exitTransition = { fadeOut(tween(pushMs, easing = pushEasing)) },
                        popEnterTransition = { fadeIn(tween(pushMs, easing = pushEasing)) },
                        popExitTransition = {
                            slideOutHorizontally(tween(pushMs, easing = pushEasing)) { it / 4 } +
                                fadeOut(tween(pushMs, easing = pushEasing))
                        },
                    ) {
                        composable(ROUTE_LOGIN) { LoginScreen() }
                        composable(
                            ROUTE_ONBOARDING_PATTERN,
                            arguments =
                                listOf(
                                    navArgument(ARG_START_STEP) {
                                        type = NavType.IntType
                                        defaultValue = 0
                                    },
                                ),
                        ) {
                            OnboardingScreen(
                                onDone = {
                                    viewModel.onOnboardingComplete()
                                    navController.navigate(ROUTE_HOME) {
                                        popUpTo(navController.graph.id) { inclusive = true }
                                        launchSingleTop = true
                                    }
                                },
                                onNavigateToLogin = { navController.navigate(ROUTE_LOGIN) },
                            )
                        }
                        composable(
                            ROUTE_HOME,
                            enterTransition = { fadeIn(tween(tabMs)) },
                            exitTransition = { fadeOut(tween(tabMs)) },
                            popEnterTransition = { fadeIn(tween(tabMs)) },
                            popExitTransition = { fadeOut(tween(tabMs)) },
                        ) {
                            HomeScreen(
                                onOpenSettings = { navController.navigate(ROUTE_SETTINGS) },
                                onOpenMealType = { mealType -> navController.navigate(mealTypeRoute(mealType)) },
                            )
                        }
                        composable(
                            ROUTE_CHAT_PATTERN,
                            arguments =
                                listOf(
                                    navArgument(ARG_QUICK_LOG) {
                                        type = NavType.BoolType
                                        defaultValue = false
                                    },
                                ),
                            enterTransition = { fadeIn(tween(tabMs)) },
                            exitTransition = { fadeOut(tween(tabMs)) },
                            popEnterTransition = { fadeIn(tween(tabMs)) },
                            popExitTransition = { fadeOut(tween(tabMs)) },
                        ) { chatEntry ->
                            val quickLog = chatEntry.arguments?.getBoolean(ARG_QUICK_LOG) ?: false
                            ChatScreen(quickLog = quickLog)
                        }
                        composable(
                            ROUTE_TRENDS,
                            enterTransition = { fadeIn(tween(tabMs)) },
                            exitTransition = { fadeOut(tween(tabMs)) },
                            popEnterTransition = { fadeIn(tween(tabMs)) },
                            popExitTransition = { fadeOut(tween(tabMs)) },
                        ) { TrendsScreen() }
                        composable(
                            ROUTE_MY_MEALS,
                            enterTransition = { fadeIn(tween(tabMs)) },
                            exitTransition = { fadeOut(tween(tabMs)) },
                            popEnterTransition = { fadeIn(tween(tabMs)) },
                            popExitTransition = { fadeOut(tween(tabMs)) },
                        ) {
                            // Home's TodayRefreshSignal-driven ON_RESUME refresh is what
                            // picks up a quick-log now, not this pop specifically — but
                            // popping back (rather than a plain nav) still avoids leaving
                            // a redundant My Meals entry on the back stack.
                            MyMealsScreen(
                                onLoggedNavigateToChat = { navController.popBackStack() },
                                onOpenMeal = { id -> navController.navigate(myMealRoute(id)) },
                            )
                        }
                        composable(ROUTE_SETTINGS) {
                            SettingsScreen(onBack = { navController.popBackStack() })
                        }
                        composable(
                            ROUTE_MEAL_TYPE_PATTERN,
                            arguments = listOf(navArgument(ARG_MEAL_TYPE) { type = NavType.StringType }),
                        ) {
                            MealTypeListScreen(
                                onBack = { navController.popBackStack() },
                                onOpenMeal = { mealId -> navController.navigate(mealRoute(mealId)) },
                            )
                        }
                        composable(
                            ROUTE_MEAL_PATTERN,
                            arguments = listOf(navArgument(ARG_MEAL_ID) { type = NavType.StringType }),
                        ) {
                            MealDetailScreen(
                                onBack = { navController.popBackStack() },
                                onDeleted = { navController.popBackStack() },
                                onLogged = { navController.popBackStack() },
                            )
                        }
                        composable(
                            ROUTE_MY_MEAL_PATTERN,
                            arguments = listOf(navArgument(ARG_ID) { type = NavType.StringType }),
                        ) {
                            MealDetailScreen(
                                onBack = { navController.popBackStack() },
                                onDeleted = { navController.popBackStack() },
                                onLogged = { navController.popBackStack() },
                            )
                        }
                    }

                    // #37 (blocker): hide the floating pill/FAB while the IME is
                    // open — with it drawn as an overlay `Box`, the composer on
                    // Chat (and any future screen with a text field) would
                    // otherwise sit directly underneath it once both are lifted
                    // above the keyboard.
                    val imeVisible = WindowInsets.isImeVisible
                    if (activeTab != null && !imeVisible) {
                        MealsyBottomBar(
                            selectedRoute = activeTab,
                            onSelect = { route ->
                                // popUpTo ROUTE_HOME (not the graph's start destination,
                                // which is the onboarding welcome route — removed from the
                                // stack on sign-in/onboarding-complete via `inclusive =
                                // true`, making a start-destination popUpTo a no-op here)
                                // so ROUTE_HOME is the tab-root: switching tabs saves/
                                // restores each tab's state instead of stacking
                                // indefinitely, and back from any tab returns to home.
                                navController.navigate(route) {
                                    popUpTo(ROUTE_HOME) {
                                        saveState = true
                                        inclusive = false
                                    }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            },
                            onFabClick = {
                                // popUpTo(ROUTE_HOME) (inclusive = false) removes any existing
                                // chat entry — including one from a prior FAB tap or the chat
                                // tab — before the new one is pushed, so repeated taps can't
                                // grow the back stack past `home -> chat`. restoreState is
                                // deliberately false (unlike the tab nav below): a saved chat
                                // entry would be restored as-is, and the freshly-popped chat
                                // destination needs a brand-new backstack entry (a new
                                // rememberSaveable scope) so ChatScreen's LaunchedEffect(quickLog)
                                // re-fires the one-shot quick-log focus + toast even when the
                                // user is already on chat.
                                navController.navigate(quickLogChatRoute()) {
                                    popUpTo(ROUTE_HOME) {
                                        saveState = true
                                        inclusive = false
                                    }
                                    launchSingleTop = true
                                    restoreState = false
                                }
                            },
                            modifier = Modifier.align(Alignment.BottomCenter),
                        )
                    }
                }

                LaunchedEffect(sessionState, onboardingState) {
                    val destination = startRouteFor(sessionState, onboardingState) ?: return@LaunchedEffect
                    navController.navigate(destination) {
                        popUpTo(navController.graph.id) { inclusive = true }
                        launchSingleTop = true
                    }
                }
            }
        }
    }
}
