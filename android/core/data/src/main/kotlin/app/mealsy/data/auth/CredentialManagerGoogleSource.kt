package app.mealsy.data.auth

import android.app.Activity
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.credentials.exceptions.GetCredentialException
import androidx.credentials.exceptions.NoCredentialException
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import com.google.android.libraries.identity.googleid.GoogleIdTokenParsingException
import javax.inject.Inject

/** [GoogleCredentialSource] backed by AndroidX Credential Manager. */
class CredentialManagerGoogleSource
    @Inject
    constructor() : GoogleCredentialSource {
        override suspend fun requestIdToken(
            activity: Activity,
            serverClientId: String,
            hashedNonce: String,
        ): String {
            val option =
                GetGoogleIdOption.Builder()
                    .setServerClientId(serverClientId)
                    .setFilterByAuthorizedAccounts(false)
                    .setNonce(hashedNonce)
                    .setAutoSelectEnabled(true)
                    .build()
            val request = GetCredentialRequest.Builder().addCredentialOption(option).build()
            val credential =
                try {
                    CredentialManager.create(activity).getCredential(activity, request).credential
                } catch (exc: GetCredentialException) {
                    throw mapCredentialFailure(exc)
                }
            if (credential !is CustomCredential ||
                credential.type != GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL
            ) {
                throw GoogleSignInException(GoogleSignInError.Failed)
            }
            return try {
                GoogleIdTokenCredential.createFrom(credential.data).idToken
            } catch (exc: GoogleIdTokenParsingException) {
                throw GoogleSignInException(GoogleSignInError.Failed, exc)
            }
        }
    }

/** Maps a Credential Manager failure to a [GoogleSignInException]. */
internal fun mapCredentialFailure(exc: GetCredentialException): GoogleSignInException =
    GoogleSignInException(
        when (exc) {
            is GetCredentialCancellationException -> GoogleSignInError.Cancelled
            is NoCredentialException -> GoogleSignInError.NoAccount
            else -> GoogleSignInError.Failed
        },
        exc,
    )
