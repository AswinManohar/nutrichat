package app.mealsy.data.auth

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AuthCallbackErrorsTest {
    @Test
    fun `error in query string is parsed`() {
        val result =
            parseAuthCallbackError(
                "mealsy://auth-callback?error=access_denied&error_code=otp_expired&error_description=Link+expired",
            )

        assertEquals(AuthCallbackErrorKind.LINK_EXPIRED_OR_USED, result?.kind)
        assertEquals("otp_expired", result?.errorCode)
        assertEquals("Link expired", result?.description)
    }

    @Test
    fun `error in fragment is parsed`() {
        val result =
            parseAuthCallbackError(
                "mealsy://auth-callback#error=access_denied&error_code=otp_expired&error_description=Link%20expired",
            )

        assertEquals(AuthCallbackErrorKind.LINK_EXPIRED_OR_USED, result?.kind)
        assertEquals("otp_expired", result?.errorCode)
        assertEquals("Link expired", result?.description)
    }

    @Test
    fun `error present in both query and fragment prefers the fragment`() {
        val result =
            parseAuthCallbackError(
                "mealsy://auth-callback?error_code=over_email_send_rate_limit#error_code=otp_expired&error=access_denied",
            )

        assertEquals(AuthCallbackErrorKind.LINK_EXPIRED_OR_USED, result?.kind)
        assertEquals("otp_expired", result?.errorCode)
    }

    @Test
    fun `no error param returns null (a normal successful callback)`() {
        val result = parseAuthCallbackError("mealsy://auth-callback?code=abc123")

        assertNull(result)
    }

    @Test
    fun `unrecognized error code maps to OTHER`() {
        val result = parseAuthCallbackError("mealsy://auth-callback?error=server_error&error_code=unexpected_failure")

        assertEquals(AuthCallbackErrorKind.OTHER, result?.kind)
        assertEquals("unexpected_failure", result?.errorCode)
    }

    @Test
    fun `rate limit error code is parsed`() {
        val result = parseAuthCallbackError("mealsy://auth-callback?error=server_error&error_code=over_email_send_rate_limit")

        assertEquals(AuthCallbackErrorKind.RATE_LIMITED, result?.kind)
    }

    @Test
    fun `missing error_code falls back to classifying the error field itself`() {
        val result = parseAuthCallbackError("mealsy://auth-callback?error=otp_expired")

        assertEquals(AuthCallbackErrorKind.LINK_EXPIRED_OR_USED, result?.kind)
        assertNull(result?.errorCode)
    }
}
