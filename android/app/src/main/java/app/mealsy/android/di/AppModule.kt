package app.mealsy.android.di

import app.mealsy.android.BuildConfig
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Qualifier

/**
 * The installed app's `versionCode`, for the startup version gate
 * ([app.mealsy.android.ui.AppNavViewModel]).
 *
 * Qualified rather than an unqualified `Int` binding so a future unrelated
 * `Int` dependency can't collide with it.
 */
@Qualifier
@Retention(AnnotationRetention.BINARY)
annotation class AppVersionCode

@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    @Provides
    @AppVersionCode
    fun provideAppVersionCode(): Int = BuildConfig.VERSION_CODE
}
