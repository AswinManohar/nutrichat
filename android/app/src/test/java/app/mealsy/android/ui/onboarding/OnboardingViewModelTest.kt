package app.mealsy.android.ui.onboarding

import androidx.lifecycle.SavedStateHandle
import app.mealsy.android.ui.login.LoginErrorKind
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
import app.mealsy.data.auth.GoogleSignInError
import app.mealsy.data.auth.GoogleSignInException
import app.mealsy.data.auth.ProfileMetadata
import app.mealsy.data.auth.SessionManager
import app.mealsy.data.auth.SessionState
import app.mealsy.data.error.ErrorReporter
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.data.repo.Profile
import app.mealsy.data.repo.ProfileStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response

/** Minimal [AuthGateway] fake — only [updateProfileMetadata] is exercised here. */
private class FakeAuthGateway(
    private val onUpdateProfileMetadata: (suspend (String, String) -> Unit)? = null,
    initialState: SessionState = SessionState.SignedIn("user-1"),
    private val googleFailure: Exception? = null,
) : AuthGateway {
    override val sessionState = MutableStateFlow(initialState)

    var googleCalls = 0

    var lastMetadataCall: Pair<String, String>? = null

    override suspend fun signInWithMagicLink(email: String) = Unit

    override suspend fun signInWithGoogle(activity: android.app.Activity) {
        googleCalls++
        googleFailure?.let { throw it }
        sessionState.value = SessionState.SignedIn("user-1")
    }

    override suspend fun refreshCurrentSession(): String? = null

    override fun currentAccessTokenOrNull(): String? = null

    override suspend fun signOut() = Unit

    override suspend fun updateProfileMetadata(
        firstName: String,
        goalFocus: String,
    ) {
        lastMetadataCall = firstName to goalFocus
        onUpdateProfileMetadata?.invoke(firstName, goalFocus)
    }

    override suspend fun currentProfileMetadata(): ProfileMetadata? = null
}

/**
 * [MealsyApi] is a plain Retrofit interface — faked directly, same as
 * `AppNavViewModelTest`, so these tests exercise [OnboardingViewModel]'s
 * logic through the real [GoalsRepository] without a MockWebServer.
 */
private class FakeMealsyApi(
    private val onCreateGoals: (suspend (GoalRequest) -> GoalsResponse)? = null,
) : MealsyApi {
    var lastCreateRequest: GoalRequest? = null

    override suspend fun logTurn(body: LogTurnRequest): LogTurnResponse = error("not used")

    override suspend fun pending(id: String): LogTurnResponse = error("not used")

    override suspend fun logItems(body: LogItemsRequest): LogItemsResponse = error("not used")

    override suspend fun today(): TodayResponse = error("not used")

    override suspend fun goals(): GoalsResponse = error("not used")

    override suspend fun createGoals(body: GoalRequest): GoalsResponse {
        lastCreateRequest = body
        return onCreateGoals?.invoke(body) ?: error("onCreateGoals not configured for this test")
    }

    override suspend fun updateGoals(body: GoalRequest): GoalsResponse = error("not used")

    override suspend fun quota(): QuotaResponse = error("not used")

    override suspend fun registerDevice(body: RegisterDeviceRequest) = error("not used")

    override suspend fun deleteDevice(token: String) = error("not used")

    override suspend fun appMeta(): AppMetaResponse = error("not used")

    override suspend fun trends(days: Int) = error("not used")

    override suspend fun categories(days: Int) = error("not used")

    override suspend fun myMeals() = error("not used")

    override suspend fun myMeal(id: String) = error("not used")

    override suspend fun saveMeal(body: SaveMealRequest) = error("not used")

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

/** In-memory [ProfileStore] fake that records call order alongside [CallOrderLog]. */
private class FakeProfileStore(
    private val callOrder: MutableList<String>? = null,
    private val onSet: (suspend (String?, String?) -> Unit)? = null,
) : ProfileStore {
    override val profile = MutableStateFlow(Profile())
    var lastSet: Pair<String?, String?>? = null

    override suspend fun get(): Profile = profile.value

    override suspend fun set(
        firstName: String?,
        goalFocus: String?,
    ) {
        callOrder?.add("profileStore.set")
        lastSet = firstName to goalFocus
        onSet?.invoke(firstName, goalFocus)
    }

    override suspend fun clear() = Unit
}

private class RecordingErrorReporter : ErrorReporter {
    val recorded = mutableListOf<Throwable>()

    override fun record(t: Throwable) {
        recorded.add(t)
    }
}

private fun echoResponse(body: GoalRequest) =
    GoalsResponse(
        trackingMode = body.trackingMode,
        kcalGoal = body.kcalGoal,
        proteinGoal = body.proteinGoal,
        fiberGoal = body.fiberGoal,
        dietaryPrefs = body.dietaryPrefs,
        firstMealTime = body.firstMealTime,
        streakDays = 0,
    )

@OptIn(ExperimentalCoroutinesApi::class)
class OnboardingViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun viewModel(
        savedStateHandle: SavedStateHandle = SavedStateHandle(),
        authGateway: FakeAuthGateway = FakeAuthGateway(),
        profileStore: FakeProfileStore = FakeProfileStore(),
        api: FakeMealsyApi = FakeMealsyApi(onCreateGoals = ::echoResponse),
        errorReporter: ErrorReporter = ErrorReporter {},
    ): OnboardingViewModel =
        OnboardingViewModel(
            savedStateHandle = savedStateHandle,
            sessionManager = SessionManager(authGateway),
            profileStore = profileStore,
            goalsRepository = GoalsRepository(api),
            errorReporter = errorReporter,
        )

    // ---- Step gating ----

    @Test
    fun `step 1 continue disabled on blank or whitespace name, enabled once typed`() =
        runTest {
            val vm = viewModel()
            vm.next() // 0 -> 1

            assertFalse(vm.uiState.value.continueEnabled)

            vm.setName("   ")
            assertFalse(vm.uiState.value.continueEnabled)

            vm.setName("Ada")
            assertTrue(vm.uiState.value.continueEnabled)
        }

    @Test
    fun `setName truncates to MAX_NAME_LENGTH characters`() =
        runTest {
            val vm = viewModel()
            vm.next() // 0 -> 1

            val long = "Bartholomew-Maximilian-Alexandrovich-Windermere" // 48 chars
            vm.setName(long)

            assertEquals(MAX_NAME_LENGTH, vm.uiState.value.name.length)
            assertEquals(long.take(MAX_NAME_LENGTH), vm.uiState.value.name)
        }

    @Test
    fun `step 2 continue disabled until a goal is picked`() =
        runTest {
            val vm = viewModel()
            vm.next() // 0 -> 1
            vm.setName("Ada")
            vm.next() // 1 -> 2

            assertFalse(vm.uiState.value.continueEnabled)

            vm.selectGoal(OnboardingGoal.Maintain)
            assertTrue(vm.uiState.value.continueEnabled)
        }

    // ---- Continue label ----

    @Test
    fun `continue label reflects step and selected prefs`() =
        runTest {
            val vm = viewModel()
            vm.next()
            vm.setName("Ada")
            vm.next() // -> step 2
            vm.selectGoal(OnboardingGoal.Maintain)
            vm.next() // -> step 3

            assertEquals(ContinueLabel.NothingToAvoid, vm.uiState.value.continueLabel)

            vm.togglePref(DietaryPref.Vegan)
            assertEquals(ContinueLabel.Continue, vm.uiState.value.continueLabel)

            vm.next() // -> step 4
            assertEquals(ContinueLabel.Finish, vm.uiState.value.continueLabel)
        }

    // ---- Default kcal per goal ----

    @Test
    fun `leaving step 2 applies the goal's default kcal, re-applied after changing goal`() =
        runTest {
            val vm = viewModel()
            vm.next()
            vm.setName("Ada")
            vm.next() // -> step 2

            vm.selectGoal(OnboardingGoal.Lose)
            vm.next() // -> step 3
            assertEquals(1800, vm.uiState.value.kcalTarget)

            vm.back() // -> step 2
            vm.selectGoal(OnboardingGoal.Build)
            vm.next() // -> step 3
            assertEquals(2600, vm.uiState.value.kcalTarget)

            vm.back()
            vm.selectGoal(OnboardingGoal.Maintain)
            vm.next()
            assertEquals(2200, vm.uiState.value.kcalTarget)
        }

    // ---- Derived protein/fiber ----

    @Test
    fun `409 from create is treated as success`() =
        runTest {
            val api =
                FakeMealsyApi(onCreateGoals = {
                    throw HttpException(Response.error<Any>(409, "".toResponseBody(null)))
                })
            val vm = viewModel(api = api)
            driveToFinish(vm, OnboardingGoal.Maintain)
            dispatcher.scheduler.advanceUntilIdle()

            assertTrue(vm.uiState.value.done)
            assertFalse(vm.uiState.value.error)
        }

    @Test
    fun `derived protein and fiber for Lose Maintain Build`() =
        runTest {
            val cases =
                listOf(
                    Triple(OnboardingGoal.Lose, 113.0, 25.0),
                    Triple(OnboardingGoal.Maintain, 110.0, 31.0),
                    Triple(OnboardingGoal.Build, 195.0, 36.0),
                )
            for ((goal, expectedProtein, expectedFiber) in cases) {
                val api = FakeMealsyApi(onCreateGoals = ::echoResponse)
                val vm = viewModel(api = api)
                driveToFinish(vm, goal)
                dispatcher.scheduler.advanceUntilIdle()

                assertEquals(goal.defaultKcal.toDouble(), api.lastCreateRequest?.kcalGoal)
                assertEquals(expectedProtein, api.lastCreateRequest?.proteinGoal)
                assertEquals(expectedFiber, api.lastCreateRequest?.fiberGoal)
            }
        }

    @Test
    fun `mindful Learn goal posts nulls and marks tracking mode mindful`() =
        runTest {
            val api = FakeMealsyApi(onCreateGoals = ::echoResponse)
            val vm = viewModel(api = api)
            vm.next()
            vm.setName("Ada")
            vm.next() // -> step 2
            vm.selectGoal(OnboardingGoal.Learn)

            assertTrue(vm.uiState.value.isMindful)

            vm.next() // -> step 3
            vm.next() // -> step 4
            vm.next() // -> step 5, starts finish
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals("mindful", api.lastCreateRequest?.trackingMode)
            assertEquals(null, api.lastCreateRequest?.kcalGoal)
            assertEquals(null, api.lastCreateRequest?.proteinGoal)
            assertEquals(null, api.lastCreateRequest?.fiberGoal)
            assertTrue(vm.uiState.value.done)
        }

    @Test
    fun `dietaryPrefs map contains exactly the selected wire keys`() =
        runTest {
            val api = FakeMealsyApi(onCreateGoals = ::echoResponse)
            val vm = viewModel(api = api)
            vm.next()
            vm.setName("Ada")
            vm.next()
            vm.selectGoal(OnboardingGoal.Maintain)
            vm.next() // -> step 3
            vm.togglePref(DietaryPref.NoDairy)
            vm.togglePref(DietaryPref.NoGluten)
            vm.togglePref(DietaryPref.LowSodium)
            vm.togglePref(DietaryPref.LowSugar)
            vm.togglePref(DietaryPref.NoNuts)
            vm.next() // -> step 4
            vm.next() // -> step 5, finish
            dispatcher.scheduler.advanceUntilIdle()

            val prefs = api.lastCreateRequest?.dietaryPrefs ?: JsonObject(emptyMap())
            assertEquals(
                setOf("dairy_free", "gluten_free", "low_sodium", "low_sugar", "no_nuts"),
                prefs.keys,
            )
            assertTrue(prefs.values.all { it.jsonPrimitive.booleanOrNull == true })
        }

    // ---- Finish ordering ----

    @Test
    fun `metadata write happens before the goals POST`() =
        runTest {
            val callOrder = mutableListOf<String>()
            val authGateway = FakeAuthGateway(onUpdateProfileMetadata = { _, _ -> callOrder.add("metadata") })
            val api =
                FakeMealsyApi(onCreateGoals = {
                    callOrder.add("goals")
                    echoResponse(it)
                })
            val vm = viewModel(authGateway = authGateway, api = api)
            driveToFinish(vm, OnboardingGoal.Maintain)
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(listOf("metadata", "goals"), callOrder)
        }

    @Test
    fun `metadata write throwing still lets the goals POST happen and reports the error`() =
        runTest {
            val authGateway = FakeAuthGateway(onUpdateProfileMetadata = { _, _ -> throw RuntimeException("boom") })
            val api = FakeMealsyApi(onCreateGoals = ::echoResponse)
            val errorReporter = RecordingErrorReporter()
            val vm = viewModel(authGateway = authGateway, api = api, errorReporter = errorReporter)
            driveToFinish(vm, OnboardingGoal.Maintain)
            dispatcher.scheduler.advanceUntilIdle()

            assertTrue(vm.uiState.value.done)
            assertEquals(1, errorReporter.recorded.size)
            assertTrue(errorReporter.recorded.single() is RuntimeException)
            assertTrue("goals POST must still have gone out", api.lastCreateRequest != null)
        }

    @Test
    fun `non-409 failure sets error, retry then succeeding sets done`() =
        runTest {
            var shouldFail = true
            val api =
                FakeMealsyApi(onCreateGoals = {
                    if (shouldFail) error("boom") else echoResponse(it)
                })
            val vm = viewModel(api = api)
            driveToFinish(vm, OnboardingGoal.Maintain)
            dispatcher.scheduler.advanceUntilIdle()

            assertTrue(vm.uiState.value.error)
            assertFalse(vm.uiState.value.done)

            shouldFail = false
            vm.retry()
            dispatcher.scheduler.advanceUntilIdle()

            assertTrue(vm.uiState.value.done)
            assertFalse(vm.uiState.value.error)
        }

    // ---- SavedStateHandle ----

    @Test
    fun `restores step name goal prefs and kcalTarget from a pre-populated SavedStateHandle`() =
        runTest {
            val handle =
                SavedStateHandle(
                    mapOf(
                        "onboarding_step" to 3,
                        "onboarding_name" to "Grace Hopper",
                        "onboarding_goal" to "build",
                        "onboarding_prefs" to arrayListOf("vegan", "no_nuts"),
                        "onboarding_kcal" to 2600,
                    ),
                )
            val vm = viewModel(savedStateHandle = handle)

            val state = vm.uiState.value
            assertEquals(3, state.step)
            assertEquals("Grace Hopper", state.name)
            assertEquals("Grace", state.firstName)
            assertEquals(OnboardingGoal.Build, state.goal)
            assertEquals(setOf(DietaryPref.Vegan, DietaryPref.NoNuts), state.prefs)
            assertEquals(2600, state.kcalTarget)
        }

    @Test
    fun `back clamps at startStep when startStep is 1`() =
        runTest {
            val handle = SavedStateHandle(mapOf("startStep" to 1))
            val vm = viewModel(savedStateHandle = handle)

            assertEquals(1, vm.uiState.value.step)

            vm.back()
            assertEquals(1, vm.uiState.value.step)
        }

    // ---- Account step (#31) ----

    private fun signedOutGateway(failure: Exception? = null) =
        FakeAuthGateway(initialState = SessionState.SignedOut, googleFailure = failure)

    @Test
    fun `signed-out Finish shows the account step and posts nothing`() =
        runTest {
            val api = FakeMealsyApi(onCreateGoals = ::echoResponse)
            val vm = viewModel(authGateway = signedOutGateway(), api = api)
            driveToFinish(vm, OnboardingGoal.Maintain)
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(ACCOUNT_STEP, vm.uiState.value.step)
            assertFalse(vm.uiState.value.done)
            assertEquals(null, api.lastCreateRequest)
        }

    @Test
    fun `Google sign-in on the account step runs finish and posts the answers`() =
        runTest {
            val gateway = signedOutGateway()
            val api = FakeMealsyApi(onCreateGoals = ::echoResponse)
            val vm = viewModel(authGateway = gateway, api = api)
            driveToFinish(vm, OnboardingGoal.Maintain)
            dispatcher.scheduler.advanceUntilIdle()

            vm.signInWithGoogle(android.app.Activity())
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(1, gateway.googleCalls)
            assertEquals("Ada" to "maintain", gateway.lastMetadataCall)
            assertEquals(2200.0, api.lastCreateRequest?.kcalGoal)
            assertTrue(vm.uiState.value.done)
            assertEquals(null, vm.uiState.value.accountError)
        }

    @Test
    fun `cancelling Google sign-in stays on the account step with no error`() =
        runTest {
            val gateway = signedOutGateway(GoogleSignInException(GoogleSignInError.Cancelled))
            val vm = viewModel(authGateway = gateway)
            driveToFinish(vm, OnboardingGoal.Maintain)
            vm.signInWithGoogle(android.app.Activity())
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(ACCOUNT_STEP, vm.uiState.value.step)
            assertEquals(null, vm.uiState.value.accountError)
            assertFalse(vm.uiState.value.accountBusy)
        }

    @Test
    fun `no Google account surfaces a message on the account step`() =
        runTest {
            val gateway = signedOutGateway(GoogleSignInException(GoogleSignInError.NoAccount))
            val vm = viewModel(authGateway = gateway)
            driveToFinish(vm, OnboardingGoal.Maintain)
            vm.signInWithGoogle(android.app.Activity())
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(LoginErrorKind.GoogleNoAccount, vm.uiState.value.accountError)
            assertEquals(ACCOUNT_STEP, vm.uiState.value.step)
        }

    @Test
    fun `session appearing elsewhere (magic link) resumes finish from the account step`() =
        runTest {
            val gateway = signedOutGateway()
            val api = FakeMealsyApi(onCreateGoals = ::echoResponse)
            val vm = viewModel(authGateway = gateway, api = api)
            driveToFinish(vm, OnboardingGoal.Build)
            dispatcher.scheduler.advanceUntilIdle()

            gateway.sessionState.value = SessionState.SignedIn("user-2")
            dispatcher.scheduler.advanceUntilIdle()

            assertTrue(vm.uiState.value.done)
            assertEquals(2600.0, api.lastCreateRequest?.kcalGoal)
        }

    @Test
    fun `401 from create routes to the account step instead of the error loop`() =
        runTest {
            val api =
                FakeMealsyApi(onCreateGoals = {
                    throw HttpException(Response.error<Any>(401, "".toResponseBody(null)))
                })
            val vm = viewModel(api = api)
            driveToFinish(vm, OnboardingGoal.Maintain)
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(ACCOUNT_STEP, vm.uiState.value.step)
            assertFalse(vm.uiState.value.error)
            assertFalse(vm.uiState.value.saving)
        }

    @Test
    fun `back from the account step returns to Target, keeping the answers`() =
        runTest {
            val vm = viewModel(authGateway = signedOutGateway())
            driveToFinish(vm, OnboardingGoal.Build)
            vm.back()

            assertEquals(4, vm.uiState.value.step)
            assertEquals("Ada", vm.uiState.value.name)
            assertEquals(OnboardingGoal.Build, vm.uiState.value.goal)
        }

    @Test
    fun `restored on the account step while already signed in resumes finish`() =
        runTest {
            val handle =
                SavedStateHandle(
                    mapOf(
                        "startStep" to 0,
                        "onboarding_step" to ACCOUNT_STEP,
                        "onboarding_name" to "Ada",
                        "onboarding_goal" to "maintain",
                    ),
                )
            val api = FakeMealsyApi(onCreateGoals = ::echoResponse)
            val vm = viewModel(savedStateHandle = handle, api = api)
            dispatcher.scheduler.advanceUntilIdle()

            assertTrue(vm.uiState.value.done)
        }

    /** Drives the flow from step 0 through step 4, choosing [goal], then calls [OnboardingViewModel.next] to finish. */
    private fun driveToFinish(
        vm: OnboardingViewModel,
        goal: OnboardingGoal,
    ) {
        vm.next() // 0 -> 1
        vm.setName("Ada")
        vm.next() // 1 -> 2
        vm.selectGoal(goal)
        vm.next() // 2 -> 3
        vm.next() // 3 -> 4
        vm.next() // 4 -> 5, starts finish
    }
}
