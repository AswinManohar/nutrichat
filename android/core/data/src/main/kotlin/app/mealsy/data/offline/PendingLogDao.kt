package app.mealsy.data.offline

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

/** Room DAO for [PendingLogEntity] — the offline direct-log replay queue. */
@Dao
interface PendingLogDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(entity: PendingLogEntity)

    @Query("SELECT * FROM pending_logs ORDER BY createdAt ASC")
    suspend fun getAll(): List<PendingLogEntity>

    @Query("DELETE FROM pending_logs WHERE clientRequestId = :clientRequestId")
    suspend fun delete(clientRequestId: String)

    @Query(
        "UPDATE pending_logs SET attempts = attempts + 1 WHERE clientRequestId = :clientRequestId",
    )
    suspend fun incrementAttempts(clientRequestId: String)
}
