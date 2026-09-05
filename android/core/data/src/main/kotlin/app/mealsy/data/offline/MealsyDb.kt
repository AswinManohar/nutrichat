package app.mealsy.data.offline

import androidx.room.Database
import androidx.room.RoomDatabase

/** The app's local Room database — currently just the offline replay queue. */
@Database(entities = [PendingLogEntity::class], version = 1, exportSchema = false)
abstract class MealsyDb : RoomDatabase() {
    abstract fun pendingLogDao(): PendingLogDao
}
