package app.mealsy.data.auth

import android.app.Activity
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.credentials.exceptions.GetCredentialUnknownException
import androidx.credentials.exceptions.NoCredentialException
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import java.io.IOException

private class FakeCredentialSource(
    private val result: Result<String> = Result.success("id-token"),
) : GoogleCredentialSource {
    var lastServerClientId: String? = null
    var lastHashedNonce: String? = null
    var calls = 0

    override suspend fun requestIdToken(
        activity: Activity,
        serverClientId: String,
        hashedNonce: String,
    ): String {
        calls++
        lastServerClientId = serverClientId
        lastHashedNonce = hashedNonce
        return result.getOrThrow()
    }
}

private class RecordingIdTokenSignIn(private val failure: Exception? = null) : IdTokenSignIn {
    var idToken: String? = null
    var rawNonce: String? = null

    override suspend fun signIn(
        idToken: String,
        rawNonce: String,
    ) {
        failure?.let { throw it }
        this.idToken = idToken
        this.rawNonce = rawNonce
    }
}

@RunWith(RobolectricTestRunner::class)
class GoogleSignInTest {
    private val activity: Activity = Robolectric.buildActivity(Activity::class.java).get()

    private fun flow(
        source: GoogleCredentialSource,
        signIn: IdTokenSignIn,
        clientId: String = "web-client.apps.googleusercontent.com",
    ) = GoogleSignIn(source, signIn, clientId, nonceFactory = { "raw-nonce" })

    private suspend fun errorOf(block: suspend () -> Unit): GoogleSignInError? =
        try {
            block()
            null
        } catch (exc: GoogleSignInException) {
            exc.error
        }

    @Test
    fun `success sends the raw nonce to Supabase and its hash to Google`() =
        runTest {
            val source = FakeCredentialSource()
            val signIn = RecordingIdTokenSignIn()

            flow(source, signIn).signIn(activity)

            assertEquals("id-token", signIn.idToken)
            assertEquals("raw-nonce", signIn.rawNonce)
            assertEquals(sha256Hex("raw-nonce"), source.lastHashedNonce)
            assertEquals("web-client.apps.googleusercontent.com", source.lastServerClientId)
        }

    @Test
    fun `sha256Hex matches the known digest`() {
        assertEquals("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824", sha256Hex("hello"))
    }

    @Test
    fun `blank client id fails before touching Credential Manager`() =
        runTest {
            val source = FakeCredentialSource()
            val signIn = RecordingIdTokenSignIn()

            val error = errorOf { flow(source, signIn, clientId = " ").signIn(activity) }

            assertEquals(GoogleSignInError.NotConfigured, error)
            assertEquals(0, source.calls)
            assertNull(signIn.idToken)
        }

    @Test
    fun `cancel from the credential source propagates as Cancelled and never signs in`() =
        runTest {
            val source = FakeCredentialSource(Result.failure(GoogleSignInException(GoogleSignInError.Cancelled)))
            val signIn = RecordingIdTokenSignIn()

            assertEquals(GoogleSignInError.Cancelled, errorOf { flow(source, signIn).signIn(activity) })
            assertNull(signIn.idToken)
        }

    @Test
    fun `IOException from Supabase maps to Network`() =
        runTest {
            val error = errorOf { flow(FakeCredentialSource(), RecordingIdTokenSignIn(IOException("offline"))).signIn(activity) }
            assertEquals(GoogleSignInError.Network, error)
        }

    @Test
    fun `unexpected Supabase failure maps to Failed`() =
        runTest {
            val error = errorOf { flow(FakeCredentialSource(), RecordingIdTokenSignIn(IllegalStateException("x"))).signIn(activity) }
            assertEquals(GoogleSignInError.Failed, error)
        }

    @Test
    fun `credential manager exceptions map to friendly errors`() {
        assertEquals(GoogleSignInError.Cancelled, mapCredentialFailure(GetCredentialCancellationException()).error)
        assertEquals(GoogleSignInError.NoAccount, mapCredentialFailure(NoCredentialException()).error)
        assertEquals(GoogleSignInError.Failed, mapCredentialFailure(GetCredentialUnknownException()).error)
    }

    @Test
    fun `raw nonces are unique and hex`() {
        val a = generateRawNonce()
        val b = generateRawNonce()
        assertTrue(a != b)
        assertTrue(a.matches(Regex("[0-9a-f]{64}")))
    }
}
