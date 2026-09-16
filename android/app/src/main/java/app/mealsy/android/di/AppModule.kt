package app.mealsy.android.di

import app.mealsy.android.BuildConfig
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import java.time.Clock
import javax.inject.Qualifier
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

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

/** The installed app's `versionName`, for [app.mealsy.android.ui.settings.SettingsViewModel]. */
@Qualifier
@Retention(AnnotationRetention.BINARY)
annotation class AppVersionName

/**
 * A [CoroutineScope] that outlives any single `ViewModel`'s `viewModelScope`
 * — for work that must finish even if the screen that started it is popped
 * (e.g. [app.mealsy.android.ui.mymeals.MyMealsViewModel]'s delayed
 * undo-window delete: `viewModelScope` gets cancelled the moment the My
 * Meals back-stack entry is popped, which would silently drop the delete).
 * `SupervisorJob` so one failed launch doesn't cancel the others sharing it.
 */
@Qualifier
@Retention(AnnotationRetention.BINARY)
annotation class ApplicationScope

@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    @Provides
    @AppVersionCode
    fun provideAppVersionCode(): Int = BuildConfig.VERSION_CODE

    @Provides
    @AppVersionName
    fun provideAppVersionName(): String = BuildConfig.VERSION_NAME

    @Provides
    @Singleton
    @ApplicationScope
    fun provideApplicationScope(): CoroutineScope =
        CoroutineScope(SupervisorJob() + Dispatchers.Default)

    /**
     * The system clock in the device's default time zone, injected into
     * [app.mealsy.android.ui.home.HomeViewModel] so its day-part/date-label
     * logic is deterministic under test (a fixed [Clock] there) while using
     * real wall-clock time in production.
     */
    @Provides
    @Singleton
    fun provideClock(): Clock = Clock.systemDefaultZone()
}
