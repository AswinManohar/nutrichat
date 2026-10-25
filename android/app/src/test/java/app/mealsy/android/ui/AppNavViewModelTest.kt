package app.mealsy.android.ui

import app.cash.turbine.test
import app.mealsy.android.push.DeviceTokenStore
import app.mealsy.android.push.FcmTokenProvider
import app.mealsy.android.push.PushRegistrar
import app.mealsy.data.api.AppMetaResponse
import app.mealsy.data.api.CoachingFeedbackRequest
import app.mealsy.data.api.GoalRequest
import app.mealsy.data.api.GoalsResponse
import app.mealsy.data.api.LogItemsRequest
import app.mealsy.data.api.LogItemsResponse
import app.mealsy.data.api.LogMyMealRequest
import app.mealsy.data.api.LogTurnRequest
import app.mealsy.data.api.LogTurnResponse
import app.mealsy.data.api.MealLogDetailDto
import app.mealsy.data.api.MealLogSummaryDto
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.QuotaResponse
import app.mealsy.data.api.RegisterDeviceRequest
import app.mealsy.data.api.SaveMealRequest
import app.mealsy.data.api.TodayResponse
import app.mealsy.data.auth.AuthGateway
import app.mealsy.data.auth.ProfileMetadata
import app.mealsy.data.auth.SessionManager
import app.mealsy.data.auth.SessionState
import app.mealsy.data.error.ErrorReporter
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.data.repo.Profile
import app.mealsy.data.repo.ProfileRefresher
import app.mealsy.data.repo.ProfileStore
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import java.io.IOException

/** Minimal [AuthGateway] fake — [AppNavViewModel] only reads [SessionManager.sessionState]. */
private class FakeAuthGateway : AuthGateway {
    override val sessionState = MutableStateFlow<SessionState>(SessionState.SignedOut)

    override suspend fun signInWithMagicLink(email: String) = Unit

    override suspend fun signInWithGoogle(activity: android.app.Activity) = Unit

    override suspend fun refreshCurrentSession(): String? = null

    override fun currentAccessTokenOrNull(): String? = null

    override suspend fun signOut() = Unit

    override suspend fun updateProfileMetadata(
        firstName: String,
        goalFocus: String,
    ) = Unit

    override suspend fun currentProfileMetadata(): ProfileMetadata? = null
}

/**
 * [MealsyApi] is a plain Retrofit interface, so it's faked directly rather than routed through
 * MockWebServer — no HTTP layer is under test here, only [AppNavViewModel]'s handling of
 * [MealsyApi.appMeta]'s result/timeout/failure.
 */
private class FakeMealsyApi(
    private val appMetaResult: (suspend () -> AppMetaResponse)? = null,
    private val goalsResult: (suspend () -> GoalsResponse)? = null,
) : MealsyApi {
    override suspend fun logTurn(body: LogTurnRequest): LogTurnResponse = error("not used")

    override suspend fun pending(id: String): LogTurnResponse = error("not used")

    override suspend fun logItems(body: LogItemsRequest): LogItemsResponse = error("not used")

    override suspend fun today(): TodayResponse = error("not used")

    override suspend fun goals(): GoalsResponse = goalsResult?.invoke() ?: error("goalsResult not configured for this test")

    override suspend fun createGoals(body: GoalRequest): GoalsResponse = error("not used")

    override suspend fun updateGoals(body: GoalRequest): GoalsResponse = error("not used")

    override suspend fun quota(): QuotaResponse = error("not used")

    override suspend fun registerDevice(body: RegisterDeviceRequest) = error("not used")

    override suspend fun deleteDevice(token: String) = error("not used")

    override suspend fun appMeta(): AppMetaResponse = appMetaResult?.invoke() ?: error("appMetaResult not configured for this test")

    override suspend fun trends(days: Int) = error("not used")

    override suspend fun categories(days: Int) = error("not used")

    override suspend fun myMeals() = error("not used")

    override suspend fun myMeal(id: String) = error("not used")

    override suspend fun saveMeal(body: SaveMealRequest) = error("not used")

    override suspend fun updateMyMeal(
        id: String,
        body: app.mealsy.data.api.UpdateMealRequest,
    ): app.mealsy.data.api.MyMealDetailDto = error("not used")

    override suspend fun logMyMeal(
        id: String,
        body: LogMyMealRequest,
    ) = error("not used")

    override suspend fun deleteMyMeal(id: String) = error("not used")

    override suspend fun listMealLogs(
        date: String?,
        mealType: String?,
    ): List<MealLogSummaryDto> = error("not used")

    override suspend fun mealLog(id: String): MealLogDetailDto = error("not used")

    override suspend fun deleteMealLog(id: String) = error("not used")

    override suspend fun searchFoods(
        q: String,
        qtyG: Double,
        limit: Int,
    ) = error("not used")

    override suspend fun getFood(
        fdcId: Long,
        qtyG: Double,
    ) = error("not used")

    override suspend fun deleteAccount() = error("not used")

    override suspend fun coachingFeedback(
        id: String,
        body: CoachingFeedbackRequest,
    ) = error("not used")
}

@OptIn(ExperimentalCoroutinesApi::class)
class AppNavViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun sessionManager() = SessionManager(FakeAuthGateway())

    /**
     * [AppNavViewModel] only calls [PushRegistrar.ensureRegistered] as a
     * side effect of `SignedIn` — none of these tests exercise sign-in, so a
     * [PushRegistrar] wired to a token provider that always returns `null`
     * (nothing to register) is enough; no MockWebServer/HTTP needed.
     */
    private fun pushRegistrar() =
        PushRegistrar(
            api = FakeMealsyApi(),
            tokenStore =
                object : DeviceTokenStore {
                    override suspend fun getLastSentToken(): String? = null

                    override suspend fun setLastSentToken(token: String) = Unit

                    override suspend fun clearLastSentToken() = Unit

                    override suspend fun isRemindersDisabled(): Boolean = false

                    override suspend fun setRemindersDisabled(disabled: Boolean) = Unit
                },
            fcmTokenProvider = FcmTokenProvider { null },
        )

    /** Default: [MealsyApi.goals] is never called by these gate-only tests (sessionState stays SignedOut). */
    private fun goalsRepository(api: FakeMealsyApi = FakeMealsyApi()) = GoalsRepository(api)

    /** In-memory [ProfileStore] fake — no DataStore/Android framework dependency. */
    private class FakeProfileStore : ProfileStore {
        private val state = MutableStateFlow(Profile())
        override val profile = state

        override suspend fun get(): Profile = state.value

        override suspend fun set(
            firstName: String?,
            goalFocus: String?,
        ) {
            state.value =
                state.value.copy(
                    firstName = firstName ?: state.value.firstName,
                    goalFocus = goalFocus ?: state.value.goalFocus,
                )
        }

        override suspend fun clear() {
            state.value = Profile()
        }
    }

    private class RecordingErrorReporter : ErrorReporter {
        val recorded = mutableListOf<Throwable>()

        override fun record(t: Throwable) {
            recorded += t
        }
    }

    /**
     * Default [ProfileRefresher]: reuses [FakeAuthGateway] as the [AuthGateway],
     * same pattern `ProfileRefresherTest` (`:core:data`) already uses for the
     * [ProfileStore]/[ErrorReporter] fakes.
     */
    private fun profileRefresher(
        authGateway: AuthGateway = FakeAuthGateway(),
        profileStore: ProfileStore = FakeProfileStore(),
        errorReporter: ErrorReporter = RecordingErrorReporter(),
    ) = ProfileRefresher(authGateway, profileStore, errorReporter)

    @Test
    fun `appMeta throws yields fail-open Ready`() =
        runTest {
            val api = FakeMealsyApi(appMetaResult = { throw RuntimeException("boom") })
            val viewModel =
                AppNavViewModel(
                    api,
                    sessionManager(),
                    currentVersionCode = 5,
                    pushRegistrar(),
                    goalsRepository(),
                    profileRefresher(),
                )

            viewModel.gateState.test {
                assertEquals(GateState.Checking, awaitItem())
                assertEquals(GateState.Ready, awaitItem())
            }
        }

    @Test
    fun `appMeta timeout yields fail-open Ready`() =
        runTest {
            val neverResolves = CompletableDeferred<AppMetaResponse>()
            val api =
                FakeMealsyApi(appMetaResult = {
                    // Longer than AppNavViewModel's 3s withTimeout — never actually completes on its
                    // own; withTimeout cancels this delay once the 3s window elapses.
                    delay(10_000)
                    neverResolves.await()
                })
            val viewModel =
                AppNavViewModel(
                    api,
                    sessionManager(),
                    currentVersionCode = 5,
                    pushRegistrar(),
                    goalsRepository(),
                    profileRefresher(),
                )

            viewModel.gateState.test {
                assertEquals(GateState.Checking, awaitItem())
                advanceTimeBy(3_001)
                assertEquals(GateState.Ready, awaitItem())
            }
        }

    @Test
    fun `min version above current yields UpdateRequired`() =
        runTest {
            val api =
                FakeMealsyApi(appMetaResult = {
                    AppMetaResponse(minSupportedVersionCode = 10, latestVersionCode = 10)
                })
            val viewModel =
                AppNavViewModel(
                    api,
                    sessionManager(),
                    currentVersionCode = 5,
                    pushRegistrar(),
                    goalsRepository(),
                    profileRefresher(),
                )

            viewModel.gateState.test {
                assertEquals(GateState.Checking, awaitItem())
                assertEquals(GateState.UpdateRequired, awaitItem())
            }
        }

    @Test
    fun `current at or above min yields Ready`() =
        runTest {
            val atMin =
                FakeMealsyApi(appMetaResult = {
                    AppMetaResponse(minSupportedVersionCode = 5, latestVersionCode = 5)
                })
            val atMinVm =
                AppNavViewModel(
                    atMin,
                    sessionManager(),
                    currentVersionCode = 5,
                    pushRegistrar(),
                    goalsRepository(),
                    profileRefresher(),
                )
            atMinVm.gateState.test {
                assertEquals(GateState.Checking, awaitItem())
                assertEquals(GateState.Ready, awaitItem())
            }

            val aboveMin =
                FakeMealsyApi(appMetaResult = {
                    AppMetaResponse(minSupportedVersionCode = 5, latestVersionCode = 6)
                })
            val aboveMinVm =
                AppNavViewModel(
                    aboveMin,
                    sessionManager(),
                    currentVersionCode = 6,
                    pushRegistrar(),
                    goalsRepository(),
                    profileRefresher(),
                )
            aboveMinVm.gateState.test {
                assertEquals(GateState.Checking, awaitItem())
                assertEquals(GateState.Ready, awaitItem())
            }
        }

    @Test
    fun `goals 404 yields onboarding Needed`() =
        runTest {
            val goalsApi =
                FakeMealsyApi(goalsResult = {
                    throw retrofit2.HttpException(
                        retrofit2.Response.error<Any>(404, "".toResponseBody(null)),
                    )
                })
            val authGateway = FakeAuthGateway()
            val viewModel =
                AppNavViewModel(
                    FakeMealsyApi(appMetaResult = { AppMetaResponse(1, 1) }),
                    SessionManager(authGateway),
                    currentVersionCode = 5,
                    pushRegistrar(),
                    goalsRepository(goalsApi),
                    profileRefresher(authGateway),
                )

            authGateway.sessionState.value = SessionState.SignedIn("user-1")
            advanceUntilIdle()

            assertEquals(OnboardingState.Needed, viewModel.onboardingState.value)
        }

    @Test
    fun `goals 200 yields onboarding NotNeeded`() =
        runTest {
            val goalsApi =
                FakeMealsyApi(goalsResult = {
                    GoalsResponse(
                        trackingMode = "goals",
                        kcalGoal = 2000.0,
                        proteinGoal = 100.0,
                        fiberGoal = 30.0,
                    )
                })
            val authGateway = FakeAuthGateway()
            val viewModel =
                AppNavViewModel(
                    FakeMealsyApi(appMetaResult = { AppMetaResponse(1, 1) }),
                    SessionManager(authGateway),
                    currentVersionCode = 5,
                    pushRegistrar(),
                    goalsRepository(goalsApi),
                    profileRefresher(authGateway),
                )

            authGateway.sessionState.value = SessionState.SignedIn("user-1")
            advanceUntilIdle()

            assertEquals(OnboardingState.NotNeeded, viewModel.onboardingState.value)
        }

    @Test
    fun `offline goals check defaults to NotNeeded, does not brick startup`() =
        runTest {
            val goalsApi = FakeMealsyApi(goalsResult = { throw IOException("offline") })
            val authGateway = FakeAuthGateway()
            val viewModel =
                AppNavViewModel(
                    FakeMealsyApi(appMetaResult = { AppMetaResponse(1, 1) }),
                    SessionManager(authGateway),
                    currentVersionCode = 5,
                    pushRegistrar(),
                    goalsRepository(goalsApi),
                    profileRefresher(authGateway),
                )

            authGateway.sessionState.value = SessionState.SignedIn("user-1")
            advanceUntilIdle()

            assertEquals(OnboardingState.NotNeeded, viewModel.onboardingState.value)
        }

    @Test
    fun `onOnboardingComplete marks NotNeeded`() =
        runTest {
            val viewModel =
                AppNavViewModel(
                    FakeMealsyApi(appMetaResult = { AppMetaResponse(1, 1) }),
                    sessionManager(),
                    currentVersionCode = 5,
                    pushRegistrar(),
                    goalsRepository(),
                    profileRefresher(),
                )

            viewModel.onOnboardingComplete()

            assertEquals(OnboardingState.NotNeeded, viewModel.onboardingState.value)
        }

    @Test
    fun `sign-in refreshes profile metadata`() =
        runTest {
            val gateway = TrackingAuthGateway()
            val viewModel =
                AppNavViewModel(
                    FakeMealsyApi(appMetaResult = { AppMetaResponse(1, 1) }),
                    SessionManager(gateway),
                    currentVersionCode = 5,
                    pushRegistrar(),
                    goalsRepository(),
                    profileRefresher(gateway),
                )

            gateway.sessionState.value = SessionState.SignedIn("user-1")
            advanceUntilIdle()

            assertEquals(true, gateway.metadataFetched)
        }

    @Test
    fun `a failing ProfileRefresher does not prevent onboarding check or push registration`() =
        runTest {
            val throwingGateway =
                object : AuthGateway {
                    override val sessionState = MutableStateFlow<SessionState>(SessionState.SignedOut)

                    override suspend fun signInWithMagicLink(email: String) = Unit

                    override suspend fun signInWithGoogle(activity: android.app.Activity) = Unit

                    override suspend fun refreshCurrentSession(): String? = null

                    override fun currentAccessTokenOrNull(): String? = null

                    override suspend fun signOut() = Unit

                    override suspend fun updateProfileMetadata(
                        firstName: String,
                        goalFocus: String,
                    ) = Unit

                    override suspend fun currentProfileMetadata(): ProfileMetadata? = throw RuntimeException("metadata fetch failed")
                }
            val errorReporter = RecordingErrorReporter()
            val goalsApi =
                FakeMealsyApi(goalsResult = {
                    GoalsResponse(
                        trackingMode = "goals",
                        kcalGoal = 2000.0,
                        proteinGoal = 100.0,
                        fiberGoal = 30.0,
                    )
                })
            val authGateway = FakeAuthGateway()
            val viewModel =
                AppNavViewModel(
                    FakeMealsyApi(appMetaResult = { AppMetaResponse(1, 1) }),
                    SessionManager(authGateway),
                    currentVersionCode = 5,
                    pushRegistrar(),
                    goalsRepository(goalsApi),
                    profileRefresher(throwingGateway, errorReporter = errorReporter),
                )

            authGateway.sessionState.value = SessionState.SignedIn("user-1")
            advanceUntilIdle()

            // ProfileRefresher swallowed and reported its own failure...
            assertEquals(1, errorReporter.recorded.size)
            // ...and onboardingState still resolved normally, unaffected.
            assertEquals(OnboardingState.NotNeeded, viewModel.onboardingState.value)
        }

    /** [AuthGateway] fake that records whether [currentProfileMetadata] was invoked. */
    private class TrackingAuthGateway : AuthGateway {
        override val sessionState = MutableStateFlow<SessionState>(SessionState.SignedOut)
        var metadataFetched = false

        override suspend fun signInWithMagicLink(email: String) = Unit

        override suspend fun signInWithGoogle(activity: android.app.Activity) = Unit

        override suspend fun refreshCurrentSession(): String? = null

        override fun currentAccessTokenOrNull(): String? = null

        override suspend fun signOut() = Unit

        override suspend fun updateProfileMetadata(
            firstName: String,
            goalFocus: String,
        ) = Unit

        override suspend fun currentProfileMetadata(): ProfileMetadata? {
            metadataFetched = true
            return ProfileMetadata("Sam", "mindful")
        }
    }
}

class StartRouteForTest {
    @Test
    fun `signed out routes to onboarding welcome`() {
        assertEquals(
            "onboarding?startStep=0",
            startRouteFor(SessionState.SignedOut, OnboardingState.Unknown),
        )
    }

    @Test
    fun `signed in and onboarding needed routes to onboarding step 1`() {
        assertEquals(
            "onboarding?startStep=1",
            startRouteFor(SessionState.SignedIn("user-1"), OnboardingState.Needed),
        )
    }

    @Test
    fun `signed in and onboarding not needed routes to home`() {
        assertEquals(
            "home",
            startRouteFor(SessionState.SignedIn("user-1"), OnboardingState.NotNeeded),
        )
    }

    @Test
    fun `signed in with unresolved onboarding state is undecided`() {
        assertEquals(
            null,
            startRouteFor(SessionState.SignedIn("user-1"), OnboardingState.Unknown),
        )
    }

    @Test
    fun `loading session state is undecided`() {
        assertEquals(null, startRouteFor(SessionState.Loading, OnboardingState.NotNeeded))
    }
}

/**
 * Exercises [tabRoute] with a hand-built [androidx.navigation.NavDestination]
 * — a plain-JVM `navigation-common` class, so no Robolectric/Android runtime
 * is needed here, unlike the Compose-level nav wiring in [AppNav].
 */
class TabRouteTest {
    /** Minimal [androidx.navigation.Navigator] just to construct a [androidx.navigation.NavDestination]. */
    @androidx.navigation.Navigator.Name("fake")
    private class FakeNavigator : androidx.navigation.Navigator<androidx.navigation.NavDestination>() {
        override fun createDestination(): androidx.navigation.NavDestination = androidx.navigation.NavDestination(this)
    }

    private fun destination(route: String?) = FakeNavigator().createDestination().apply { this.route = route }

    @Test
    fun `home tab route maps to itself`() {
        assertEquals("home", destination("home").tabRoute())
    }

    @Test
    fun `my-meals tab route maps to itself`() {
        assertEquals("my-meals", destination("my-meals").tabRoute())
    }

    @Test
    fun `trends tab route maps to itself`() {
        assertEquals("trends", destination("trends").tabRoute())
    }

    @Test
    fun `chat's parameterized pattern route maps to the plain chat tab`() {
        assertEquals("chat", destination("chat?quickLog={quickLog}").tabRoute())
    }

    @Test
    fun `an unrecognized route maps to null (pill defaults to hidden)`() {
        assertEquals(null, destination("settings").tabRoute())
        assertEquals(null, destination("onboarding?startStep={startStep}").tabRoute())
        assertEquals(null, destination(null).tabRoute())
        assertEquals(null, (null as androidx.navigation.NavDestination?).tabRoute())
    }
}
