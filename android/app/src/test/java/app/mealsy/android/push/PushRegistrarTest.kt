package app.mealsy.android.push

import app.mealsy.data.api.GoalRequest
import app.mealsy.data.api.GoalsResponse
import app.mealsy.data.api.LogItemsRequest
import app.mealsy.data.api.LogItemsResponse
import app.mealsy.data.api.LogTurnRequest
import app.mealsy.data.api.LogTurnResponse
import app.mealsy.data.api.LogMyMealRequest
import app.mealsy.data.api.SaveMealRequest
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.AppMetaResponse
import app.mealsy.data.api.QuotaResponse
import app.mealsy.data.api.RegisterDeviceRequest
import app.mealsy.data.api.TodayResponse
import javax.inject.Provider
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [MealsyApi] fake recording every `registerDevice`/`deleteDevice` call —
 * plain Retrofit interface, so faked directly rather than via MockWebServer
 * (as `AppNavViewModelTest` also does), since no HTTP layer is under test.
 */
private class FakeMealsyApi : MealsyApi {
    val registeredTokens = mutableListOf<String>()
    val deletedTokens = mutableListOf<String>()
    var deleteDeviceShouldThrow: Boolean = false
    var registerDeviceShouldThrow: Boolean = false

    override suspend fun logTurn(body: LogTurnRequest): LogTurnResponse = error("not used")
    override suspend fun pending(id: String): LogTurnResponse = error("not used")
    override suspend fun logItems(body: LogItemsRequest): LogItemsResponse = error("not used")
    override suspend fun today(): TodayResponse = error("not used")
    override suspend fun goals(): GoalsResponse = error("not used")
    override suspend fun createGoals(body: GoalRequest): GoalsResponse = error("not used")
    override suspend fun updateGoals(body: GoalRequest): GoalsResponse = error("not used")
    override suspend fun quota(): QuotaResponse = error("not used")
    override suspend fun appMeta(): AppMetaResponse = error("not used")
    override suspend fun trends(days: Int) = error("not used")
    override suspend fun categories(days: Int) = error("not used")
    override suspend fun myMeals() = error("not used")
    override suspend fun saveMeal(body: SaveMealRequest) = error("not used")
    override suspend fun logMyMeal(id: String, body: LogMyMealRequest) = error("not used")
    override suspend fun deleteMyMeal(id: String) = error("not used")
    override suspend fun deleteAccount() = error("not used")

    override suspend fun registerDevice(body: RegisterDeviceRequest) {
        if (registerDeviceShouldThrow) throw RuntimeException("network down")
        registeredTokens += body.token
    }

    override suspend fun deleteDevice(token: String) {
        if (deleteDeviceShouldThrow) throw RuntimeException("network down")
        deletedTokens += token
    }
}

/** In-memory [DeviceTokenStore] — a real DataStore needs Android/Robolectric. */
private class FakeDeviceTokenStore : DeviceTokenStore {
    private var lastSentToken: String? = null
    private var remindersDisabled: Boolean = false

    override suspend fun getLastSentToken(): String? = lastSentToken
    override suspend fun setLastSentToken(token: String) {
        lastSentToken = token
    }
    override suspend fun clearLastSentToken() {
        lastSentToken = null
    }
    override suspend fun isRemindersDisabled(): Boolean = remindersDisabled
    override suspend fun setRemindersDisabled(disabled: Boolean) {
        remindersDisabled = disabled
    }
}

class PushRegistrarTest {

    @Test
    fun `ensureRegistered posts current token once per token value`() = runTest {
        val api = FakeMealsyApi()
        val tokenStore = FakeDeviceTokenStore()
        var currentToken = "token-a"
        val registrar = PushRegistrar(
            api = api,
            tokenStore = tokenStore,
            fcmTokenProvider = FcmTokenProvider { currentToken },
        )

        registrar.ensureRegistered()
        registrar.ensureRegistered()

        assertEquals(listOf("token-a"), api.registeredTokens)
        assertEquals("token-a", tokenStore.getLastSentToken())

        // A genuinely new token (e.g. after a Firebase-triggered rotation)
        // must be posted again — idempotency is per token value, not global.
        currentToken = "token-b"
        registrar.ensureRegistered()

        assertEquals(listOf("token-a", "token-b"), api.registeredTokens)
        assertEquals("token-b", tokenStore.getLastSentToken())
    }

    @Test
    fun `ensureRegistered is a no-op when no FCM token is available`() = runTest {
        // Simulates a checkout without google-services.json: FirebaseFcmTokenProvider
        // returns null rather than throwing.
        val api = FakeMealsyApi()
        val registrar = PushRegistrar(
            api = api,
            tokenStore = FakeDeviceTokenStore(),
            fcmTokenProvider = FcmTokenProvider { null },
        )

        registrar.ensureRegistered()

        assertTrue(api.registeredTokens.isEmpty())
    }

    @Test
    fun `ensureRegistered no-ops when reminders are disabled`() = runTest {
        val api = FakeMealsyApi()
        val tokenStore = FakeDeviceTokenStore()
        tokenStore.setRemindersDisabled(true)
        val registrar = PushRegistrar(
            api = api,
            tokenStore = tokenStore,
            fcmTokenProvider = FcmTokenProvider { "token-a" },
        )

        registrar.ensureRegistered()

        assertTrue(api.registeredTokens.isEmpty())
        assertNull(tokenStore.getLastSentToken())
    }

    @Test
    fun `toggling reminders off then ensureRegistered does not re-register`() = runTest {
        // Regression: AppNavViewModel calls ensureRegistered() unconditionally
        // after every sign-in — without the disabled check, that would silently
        // undo a Settings toggle-off.
        val api = FakeMealsyApi()
        val tokenStore = FakeDeviceTokenStore()
        val registrar = PushRegistrar(
            api = api,
            tokenStore = tokenStore,
            fcmTokenProvider = FcmTokenProvider { "token-a" },
        )
        registrar.ensureRegistered()
        assertEquals(listOf("token-a"), api.registeredTokens)

        registrar.unregisterCurrentDevice()
        tokenStore.setRemindersDisabled(true)
        registrar.ensureRegistered()

        assertEquals(listOf("token-a"), api.registeredTokens)
        assertNull(tokenStore.getLastSentToken())
    }

    @Test
    fun `unregisterCurrentDevice deletes device token and swallows network failure`() = runTest {
        val api = FakeMealsyApi()
        api.deleteDeviceShouldThrow = true
        val tokenStore = FakeDeviceTokenStore()
        tokenStore.setLastSentToken("token-a")
        val registrar = PushRegistrar(
            api = api,
            tokenStore = tokenStore,
            fcmTokenProvider = FcmTokenProvider { null },
        )

        // Must not throw even though the DELETE call fails.
        registrar.unregisterCurrentDevice()

        assertNull(tokenStore.getLastSentToken())
    }

    @Test
    fun `unregisterCurrentDevice deletes the last-sent token on success`() = runTest {
        val api = FakeMealsyApi()
        val tokenStore = FakeDeviceTokenStore()
        tokenStore.setLastSentToken("token-a")
        val registrar = PushRegistrar(
            api = api,
            tokenStore = tokenStore,
            fcmTokenProvider = FcmTokenProvider { null },
        )

        registrar.unregisterCurrentDevice()

        assertEquals(listOf("token-a"), api.deletedTokens)
        assertNull(tokenStore.getLastSentToken())
    }

    @Test
    fun `signOut hook deletes device token and swallows network failure`() = runTest {
        val api = FakeMealsyApi()
        api.deleteDeviceShouldThrow = true
        val tokenStore = FakeDeviceTokenStore()
        tokenStore.setLastSentToken("token-a")
        val registrar = PushRegistrar(
            api = api,
            tokenStore = tokenStore,
            fcmTokenProvider = FcmTokenProvider { null },
        )
        val signOutHook = PushRegistrarSignOutHook(Provider { registrar })

        // This is the exact seam SessionManager.signOut() invokes — it must
        // complete without throwing even when the backend call fails.
        signOutHook.onDeviceSignOut()

        assertNull(tokenStore.getLastSentToken())
    }

    @Test
    fun `registerToken swallows a registration failure without storing the token`() = runTest {
        val api = FakeMealsyApi()
        api.registerDeviceShouldThrow = true
        val tokenStore = FakeDeviceTokenStore()
        val registrar = PushRegistrar(
            api = api,
            tokenStore = tokenStore,
            fcmTokenProvider = FcmTokenProvider { null },
        )

        registrar.registerToken("token-a")

        assertNull(tokenStore.getLastSentToken())
    }
}
