package app.mealsy.data.auth

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GoogleAuthAvailabilityGatewayTest {
    @Test
    fun `google disabled in settings response returns false`() {
        val body = """{"external":{"email":true,"google":false}}"""

        assertFalse(parseGoogleEnabled(body))
    }

    @Test
    fun `google enabled in settings response returns true`() {
        val body = """{"external":{"email":true,"google":true}}"""

        assertTrue(parseGoogleEnabled(body))
    }

    @Test
    fun `missing external object fails open (true)`() {
        assertTrue(parseGoogleEnabled("""{"foo":"bar"}"""))
    }

    @Test
    fun `blank body fails open (true)`() {
        assertTrue(parseGoogleEnabled(""))
    }

    @Test
    fun `malformed json fails open (true)`() {
        assertTrue(parseGoogleEnabled("not json"))
    }
}
