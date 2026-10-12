package com.locationjoystick.core.data

import android.util.Log
import com.locationjoystick.core.database.dao.FavoriteDao
import com.locationjoystick.core.database.entities.FavoriteEntity
import com.locationjoystick.core.database.entities.toDomain
import com.locationjoystick.core.database.entities.toEntity
import com.locationjoystick.core.model.FavoriteLocation
import com.locationjoystick.core.model.LatLng
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

private const val TAG = "FavoriteRepository"

@Singleton
class FavoriteRepository
    @Inject
    constructor(
        private val favoriteDao: FavoriteDao,
        private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
    ) {
        fun getFavorites(): Flow<List<FavoriteLocation>> =
            favoriteDao.getAll().map { list ->
                list.map { it.toDomain() }
            }

        suspend fun addFavorite(
            id: String,
            name: String,
            position: LatLng,
            createdAt: Long = System.currentTimeMillis(),
            category: String? = null,
        ): Result<Unit> =
            withContext(ioDispatcher) {
                runCatching {
                    val favorite =
                        FavoriteLocation(
                            id = id,
                            name = name,
                            position = position,
                            createdAt = createdAt,
                            category = category,
                        )
                    favoriteDao.insert(favorite.toEntity())
                }.onFailure { e ->
                    Log.e(TAG, "Failed to add favorite: $name", e)
                }
            }

        suspend fun updateFavorite(favorite: FavoriteLocation): Result<Unit> =
            withContext(ioDispatcher) {
                runCatching {
                    favoriteDao.update(favorite.toEntity())
                }.onFailure { e ->
                    Log.e(TAG, "Failed to update favorite: ${favorite.id}", e)
                }
            }

        /** Moves [id] into user group [category] (null = ungrouped). Hot favorites keep their country. */
        suspend fun setCategory(
            id: String,
            category: String?,
        ): Result<Unit> =
            withContext(ioDispatcher) {
                runCatching {
                    val entity = favoriteDao.getById(id)
                    if (entity != null && !entity.id.startsWith(HOT_ID_PREFIX)) {
                        favoriteDao.update(entity.copy(category = category))
                    }
                }.onFailure { e -> Log.e(TAG, "Failed to set favorite category: $id", e) }
            }

        /** Renames user group [from] to [to], or ungroups its members when [to] is null. */
        suspend fun renameCategory(
            from: String,
            to: String?,
        ): Result<Unit> =
            withContext(ioDispatcher) {
                runCatching {
                    favoriteDao
                        .getAll()
                        .first()
                        .filter { it.category == from && !it.id.startsWith(HOT_ID_PREFIX) }
                        .forEach { favoriteDao.update(it.copy(category = to)) }
                }.onFailure { e -> Log.e(TAG, "Failed to rename favorite group: $from", e) }
            }

        suspend fun deleteFavorite(id: String): Result<Unit> =
            withContext(ioDispatcher) {
                runCatching {
                    val entity = favoriteDao.getById(id)
                    if (entity != null) {
                        favoriteDao.delete(entity)
                    }
                }.onFailure { e ->
                    Log.e(TAG, "Failed to delete favorite: $id", e)
                }
            }

        suspend fun deleteAllFavorites(): Result<Unit> =
            withContext(ioDispatcher) {
                runCatching {
                    favoriteDao.deleteAll()
                }.onFailure { e ->
                    Log.e(TAG, "Failed to delete all favorites", e)
                }
            }

        /**
         * Reconciles `hot_*` favorites to [locations]: inserts/updates the [selectedIds] entries,
         * removes unselected ones, and deletes any `hot_*` favorite no longer listed. User
         * favorites never carry the `hot_` prefix, so they are untouched.
         */
        suspend fun upsertHotLocations(
            locations: List<HotLocation>,
            selectedIds: Set<String>,
        ): Result<Unit> =
            withContext(ioDispatcher) {
                runCatching {
                    val listedIds = locations.map { idForLocation(it.name, it.city) }.toSet()
                    favoriteDao.getAll().first().filter { it.id.startsWith(HOT_ID_PREFIX) && it.id !in listedIds }.forEach {
                        favoriteDao.delete(it)
                    }
                    locations.forEach { location ->
                        val id = idForLocation(location.name, location.city)
                        if (id in selectedIds) {
                            val existing = favoriteDao.getById(id)
                            if (existing != null) {
                                favoriteDao.update(
                                    existing.copy(
                                        latitude = location.lat,
                                        longitude = location.lon,
                                        category = location.country,
                                    ),
                                )
                            } else {
                                favoriteDao.insert(
                                    FavoriteEntity(
                                        id = id,
                                        name = location.name,
                                        latitude = location.lat,
                                        longitude = location.lon,
                                        createdAt = System.currentTimeMillis(),
                                        category = location.country,
                                    ),
                                )
                            }
                        } else {
                            val existing = favoriteDao.getById(id)
                            if (existing != null) favoriteDao.delete(existing)
                        }
                    }
                }.onFailure { e -> Log.e(TAG, "Failed to upsert hot locations", e) }
            }

        suspend fun removeHotLocations(): Result<Unit> =
            withContext(ioDispatcher) {
                runCatching {
                    favoriteDao.deleteHotLocations()
                }.onFailure { e -> Log.e(TAG, "Failed to remove hot locations", e) }
            }

        companion object {
            private const val HOT_ID_PREFIX = "hot_"

            fun idForLocation(
                name: String,
                city: String,
            ): String = HOT_ID_PREFIX + "$name $city".lowercase().replace(Regex("[^a-z0-9]"), "_")
        }
    }
