package app.mealsy.data.api

import app.mealsy.android.data.BuildConfig
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import javax.inject.Singleton

/**
 * Provides the Retrofit-backed [MealsyApi] singleton.
 *
 * The base URL comes from `:core:data`'s own `BuildConfig.API_BASE_URL`
 * (see this module's build.gradle.kts for why it isn't sourced from `:app`)
 * rather than being passed in — Task 4 only needs to bind [TokenProvider]
 * (to `SessionManager::currentToken`) for auth to be fully wired.
 */
@Module
@InstallIn(SingletonComponent::class)
object ApiModule {

    @Provides
    @Singleton
    fun provideJson(): Json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    @Provides
    @Singleton
    fun provideOkHttpClient(tokenProvider: TokenProvider): OkHttpClient =
        OkHttpClient.Builder()
            .addInterceptor(AuthInterceptor(tokenProvider))
            .addInterceptor(
                HttpLoggingInterceptor().apply { level = HttpLoggingInterceptor.Level.BASIC },
            )
            .build()

    @Provides
    @Singleton
    fun provideRetrofit(client: OkHttpClient, json: Json): Retrofit {
        val contentType = "application/json".toMediaType()
        return Retrofit.Builder()
            .baseUrl(normalizeBaseUrl(BuildConfig.API_BASE_URL))
            .client(client)
            .addConverterFactory(json.asConverterFactory(contentType))
            .build()
    }

    @Provides
    @Singleton
    fun provideMealsyApi(retrofit: Retrofit): MealsyApi = retrofit.create(MealsyApi::class.java)
}

/**
 * Retrofit's `Retrofit.Builder().baseUrl(...)` throws at build time unless
 * the URL ends in `/`. `BuildConfig.API_BASE_URL` values (e.g.
 * `http://10.0.2.2:8000` from local.properties) commonly omit it, which
 * previously crashed Hilt injection. Also enforces that release builds
 * don't silently fall back to an unset/dev URL (see build.gradle.kts,
 * where the release variant's field defaults to "" instead of the debug
 * default).
 */
internal fun normalizeBaseUrl(baseUrl: String): String {
    check(baseUrl.isNotBlank()) { "API_BASE_URL not configured for release" }
    return if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/"
}
