package app.mealsy.android

import android.app.Application
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import dagger.hilt.android.HiltAndroidApp
import javax.inject.Inject

/**
 * Supplies [HiltWorkerFactory] to WorkManager so `@HiltWorker` workers (e.g.
 * `ReplayWorker`) can be constructed with their Hilt-injected dependencies.
 * The default `WorkManagerInitializer` is removed in the manifest so this
 * configuration is the one actually used.
 */
@HiltAndroidApp
class MealsyApp : Application(), Configuration.Provider {
    @Inject
    lateinit var workerFactory: HiltWorkerFactory

    override val workManagerConfiguration: Configuration
        get() =
            Configuration.Builder()
                .setWorkerFactory(workerFactory)
                .build()
}
