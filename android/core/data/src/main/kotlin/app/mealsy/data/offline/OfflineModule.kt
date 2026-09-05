package app.mealsy.data.offline

import android.content.Context
import androidx.room.Room
import androidx.work.WorkManager
import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

/** Provides the Room database/DAO and binds the offline replay queue. */
@Module
@InstallIn(SingletonComponent::class)
abstract class OfflineModule {

    @Binds
    abstract fun bindPendingLogQueue(impl: RoomPendingLogQueue): PendingLogQueue

    @Binds
    abstract fun bindReplayWorkEnqueuer(impl: WorkManagerReplayEnqueuer): ReplayWorkEnqueuer

    @Binds
    abstract fun bindDroppedLogStore(impl: DataStoreDroppedLogStore): DroppedLogStore

    companion object {
        @Provides
        @Singleton
        fun provideMealsyDb(@ApplicationContext context: Context): MealsyDb =
            Room.databaseBuilder(context, MealsyDb::class.java, "mealsy-offline.db").build()

        @Provides
        fun providePendingLogDao(db: MealsyDb): PendingLogDao = db.pendingLogDao()

        @Provides
        @Singleton
        fun provideWorkManager(@ApplicationContext context: Context): WorkManager =
            WorkManager.getInstance(context)
    }
}

class WorkManagerReplayEnqueuer @javax.inject.Inject constructor(
    private val workManager: WorkManager,
) : ReplayWorkEnqueuer {
    override fun enqueueReplay() {
        ReplayWorker.enqueue(workManager)
    }
}
