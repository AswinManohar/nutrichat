package app.mealsy.data.auth

import app.mealsy.android.data.BuildConfig
import app.mealsy.data.api.TokenProvider
import app.mealsy.data.error.ErrorReporter
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.createSupabaseClient
import io.github.jan.supabase.gotrue.Auth
import io.github.jan.supabase.gotrue.FlowType
import io.github.jan.supabase.gotrue.auth
import javax.inject.Singleton

/**
 * Wires the Supabase client, its `Auth` plugin, and [SessionManager].
 *
 * Binds [TokenProvider] (the seam `ApiModule`/`AuthInterceptor` were left
 * expecting from Task 3) directly to `SessionManager::currentToken`.
 */
@Module
@InstallIn(SingletonComponent::class)
object AuthModule {
    @Provides
    @Singleton
    fun provideSupabaseClient(): SupabaseClient {
        check(BuildConfig.SUPABASE_URL.isNotBlank()) { "SUPABASE_URL not configured" }
        check(BuildConfig.SUPABASE_ANON_KEY.isNotBlank()) { "SUPABASE_ANON_KEY not configured" }
        return createSupabaseClient(
            supabaseUrl = BuildConfig.SUPABASE_URL,
            supabaseKey = BuildConfig.SUPABASE_ANON_KEY,
        ) {
            install(Auth) {
                scheme = "mealsy"
                host = "auth-callback"
                flowType = FlowType.PKCE
            }
        }
    }

    @Provides
    @Singleton
    fun provideAuth(client: SupabaseClient): Auth = client.auth

    @Provides
    @Singleton
    fun provideGoogleSignIn(
        auth: Auth,
        source: CredentialManagerGoogleSource,
    ): GoogleSignIn = GoogleSignIn(source, supabaseIdTokenSignIn(auth), BuildConfig.GOOGLE_WEB_CLIENT_ID)

    @Provides
    @Singleton
    fun provideAuthGateway(gateway: SupabaseAuthGateway): AuthGateway = gateway

    @Provides
    @Singleton
    fun provideGoogleAuthAvailabilityGateway(gateway: SupabaseGoogleAuthAvailabilityGateway): GoogleAuthAvailabilityGateway = gateway

    @Provides
    @Singleton
    fun provideSessionManager(
        authGateway: AuthGateway,
        signOutHook: SignOutHook,
        errorReporter: ErrorReporter,
    ): SessionManager = SessionManager(authGateway, onSignOut = signOutHook::onDeviceSignOut, errorReporter = errorReporter)

    @Provides
    @Singleton
    fun provideTokenProvider(sessionManager: SessionManager): TokenProvider =
        TokenProvider { forceRefresh -> sessionManager.currentToken(forceRefresh) }
}
