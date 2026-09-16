package app.mealsy.data.repo

import android.content.Context
import app.cash.turbine.test
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * [DataStoreProfileStore] against a real (Robolectric-backed) DataStore —
 * same convention as `ReplayWorkerTest` for the [Context] this needs.
 *
 * Robolectric reuses the same on-disk files dir across test methods in a
 * class run, so the "profile" preferences file written by one test is
 * still there when the next one starts — [setUp] clears it so each test
 * sees an empty store regardless of run order.
 */
@RunWith(RobolectricTestRunner::class)
class DataStoreProfileStoreTest {

    private val context: Context = ApplicationProvider.getApplicationContext()
    private val store = DataStoreProfileStore(context)

    @Before
    fun setUp() = runBlocking {
        store.clear()
    }

    @Test
    fun `get returns empty profile when nothing has been written`() = runTest {
        assertEquals(Profile(firstName = null, goalFocus = null), store.get())
    }

    @Test
    fun `set then get round-trips both fields`() = runTest {
        store.set(firstName = "Sam", goalFocus = "lose_weight")

        assertEquals(Profile(firstName = "Sam", goalFocus = "lose_weight"), store.get())
    }

    @Test
    fun `set with a null firstName preserves the existing goalFocus`() = runTest {
        store.set(firstName = "Sam", goalFocus = "lose_weight")

        store.set(firstName = null, goalFocus = "mindful")

        assertEquals(Profile(firstName = "Sam", goalFocus = "mindful"), store.get())
    }

    @Test
    fun `set with a null goalFocus preserves the existing firstName`() = runTest {
        store.set(firstName = "Sam", goalFocus = "lose_weight")

        store.set(firstName = "Sammy", goalFocus = null)

        assertEquals(Profile(firstName = "Sammy", goalFocus = "lose_weight"), store.get())
    }

    @Test
    fun `clear empties both fields`() = runTest {
        store.set(firstName = "Sam", goalFocus = "lose_weight")

        store.clear()

        assertEquals(Profile(firstName = null, goalFocus = null), store.get())
    }

    @Test
    fun `profile flow emits updates as they are written`() = runTest {
        store.profile.test {
            assertEquals(Profile(firstName = null, goalFocus = null), awaitItem())

            store.set(firstName = "Sam", goalFocus = "lose_weight")
            assertEquals(Profile(firstName = "Sam", goalFocus = "lose_weight"), awaitItem())

            store.clear()
            assertEquals(Profile(firstName = null, goalFocus = null), awaitItem())

            cancelAndIgnoreRemainingEvents()
        }
    }
}
