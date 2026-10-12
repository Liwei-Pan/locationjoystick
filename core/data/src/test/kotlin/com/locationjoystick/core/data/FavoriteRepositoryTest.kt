package com.locationjoystick.core.data

import app.cash.turbine.test
import com.locationjoystick.core.model.FavoriteLocation
import com.locationjoystick.core.model.LatLng
import com.locationjoystick.core.testing.FakeFavoriteDao
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class FavoriteRepositoryTest {
    private lateinit var dao: FakeFavoriteDao
    private lateinit var repository: FavoriteRepository
    private val hot =
        listOf(
            HotLocation("Singapore", 1.288719, 103.848742, "Singapore", "Singapore"),
            HotLocation("Osaka", 34.70246, 135.50024, "Japan", "Osaka"),
            HotLocation("Sydney", -33.86882, 151.209296, "Australia", "Sydney"),
        )
    private val hotIds = hot.map { FavoriteRepository.idForLocation(it.name, it.city) }.toSet()

    @Before
    fun setUp() {
        dao = FakeFavoriteDao()
        repository = FavoriteRepository(dao)
    }

    @Test
    fun `getFavorites emits empty list initially`() =
        runTest {
            repository.getFavorites().test {
                assertTrue(awaitItem().isEmpty())
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `addFavorite then getFavorites emits added item`() =
        runTest {
            repository.getFavorites().test {
                awaitItem() // empty list

                repository.addFavorite(
                    id = "fav-1",
                    name = "Eiffel Tower",
                    position = LatLng(48.8584, 2.2945),
                    createdAt = 1_000L,
                )

                val list = awaitItem()
                assertEquals(1, list.size)
                assertEquals("Eiffel Tower", list.first().name)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `renameCategory renames user group and leaves hot favorites`() =
        runTest {
            repository.addFavorite("u1", "Park", LatLng(1.0, 1.0), category = "Local")
            repository.addFavorite("hot_x", "Spot", LatLng(2.0, 2.0), category = "Local")

            repository.renameCategory("Local", "Home turf")

            repository.getFavorites().test {
                val byId = awaitItem().associateBy { it.id }
                assertEquals("Home turf", byId.getValue("u1").category)
                assertEquals("Local", byId.getValue("hot_x").category)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `renameCategory to null ungroups members`() =
        runTest {
            repository.addFavorite("u1", "Park", LatLng(1.0, 1.0), category = "Local")

            repository.renameCategory("Local", null)

            repository.getFavorites().test {
                assertEquals(null, awaitItem().single().category)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `setCategory ignores hot favorites`() =
        runTest {
            repository.addFavorite("hot_x", "Spot", LatLng(2.0, 2.0), category = "France")

            repository.setCategory("hot_x", "Mine")

            repository.getFavorites().test {
                assertEquals("France", awaitItem().single().category)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `addFavorite persists category`() =
        runTest {
            repository.addFavorite(
                id = "fav-1",
                name = "Eiffel Tower",
                position = LatLng(48.8584, 2.2945),
                createdAt = 1_000L,
                category = "France",
            )

            repository.getFavorites().test {
                val list = awaitItem()
                assertEquals("France", list.first().category)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `deleteFavorite removes item from flow`() =
        runTest {
            repository.addFavorite("fav-1", "Tower", LatLng(48.8584, 2.2945), createdAt = 1_000L)

            repository.getFavorites().test {
                val initial = awaitItem()
                assertEquals(1, initial.size)

                repository.deleteFavorite("fav-1")

                val afterDelete = awaitItem()
                assertTrue(afterDelete.isEmpty())
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `deleteFavorite non-existent id succeeds without error`() =
        runTest {
            val result = repository.deleteFavorite("does-not-exist")
            assertTrue(result.isSuccess)
        }

    @Test
    fun `getFavorites sorts alphabetically ascending`() =
        runTest {
            repository.addFavorite("a", "Zebra", LatLng(0.0, 0.0), createdAt = 100L)
            repository.addFavorite("b", "Apple", LatLng(1.0, 0.0), createdAt = 200L)

            repository.getFavorites().test {
                val list = awaitItem()
                assertEquals(2, list.size)
                assertEquals("Apple", list.first().name)
                assertEquals("Zebra", list.last().name)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `updateFavorite changes name in flow`() =
        runTest {
            repository.addFavorite("fav-1", "Old Name", LatLng(0.0, 0.0), createdAt = 1_000L)

            val updated =
                FavoriteLocation(id = "fav-1", name = "New Name", position = LatLng(0.0, 0.0), createdAt = 1_000L)
            repository.updateFavorite(updated)

            repository.getFavorites().test {
                val list = awaitItem()
                assertEquals("New Name", list.first().name)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `addFavorite preserves exact position`() =
        runTest {
            val position = LatLng(48.8584, 2.2945)
            repository.addFavorite("fav-1", "Tower", position, createdAt = 1_000L)

            repository.getFavorites().test {
                val list = awaitItem()
                assertEquals(position.latitude, list.first().position.latitude, 0.00001)
                assertEquals(position.longitude, list.first().position.longitude, 0.00001)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `updateFavorite preserves position`() =
        runTest {
            val originalPos = LatLng(0.0, 0.0)
            repository.addFavorite("fav-1", "A", originalPos, createdAt = 1_000L)

            val newPos = LatLng(51.5, -0.1)
            val updated = FavoriteLocation(id = "fav-1", name = "B", position = newPos, createdAt = 1_000L)
            repository.updateFavorite(updated)

            repository.getFavorites().test {
                val list = awaitItem()
                assertEquals(newPos.latitude, list.first().position.latitude, 0.00001)
                assertEquals(newPos.longitude, list.first().position.longitude, 0.00001)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `multiple favorites sort alphabetically`() =
        runTest {
            repository.addFavorite("a", "Mango", LatLng(0.0, 0.0), createdAt = 100L)
            repository.addFavorite("b", "Apple", LatLng(1.0, 0.0), createdAt = 200L)
            repository.addFavorite("c", "Zebra", LatLng(2.0, 0.0), createdAt = 300L)

            repository.getFavorites().test {
                val list = awaitItem()
                assertEquals(3, list.size)
                assertEquals("Apple", list[0].name)
                assertEquals("Mango", list[1].name)
                assertEquals("Zebra", list[2].name)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `upsertHotLocations inserts all listed hot locations`() =
        runTest {
            repository.upsertHotLocations(hot, hotIds)

            repository.getFavorites().test {
                val list = awaitItem()
                assertEquals(hot.size, list.size)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `upsertHotLocations uses hot_ id prefix for new entries`() =
        runTest {
            repository.upsertHotLocations(hot, hotIds)

            repository.getFavorites().test {
                val list = awaitItem()
                list.forEach { fav ->
                    assertTrue("Expected hot_ prefix for ${fav.name}", fav.id.startsWith("hot_"))
                }
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `upsertHotLocations does not modify user favorite with same name`() =
        runTest {
            // Pre-existing favorite with same name as a hot location, different coords
            repository.addFavorite("user-id", "Singapore", LatLng(0.0, 0.0), createdAt = 1_000L)

            repository.upsertHotLocations(hot, hotIds)

            repository.getFavorites().test {
                val list = awaitItem()
                assertEquals(hot.size + 1, list.size)

                // Find the hot location entry
                val hotSingapore = list.first { it.id == "hot_singapore_singapore" }
                assertEquals("Singapore", hotSingapore.name)
                assertEquals(1.288719, hotSingapore.position.latitude, 0.000001)
                assertEquals(103.848742, hotSingapore.position.longitude, 0.000001)

                // Find the user favorite entry - should be unchanged
                val userSingapore = list.first { it.id == "user-id" }
                assertEquals("Singapore", userSingapore.name)
                assertEquals(0.0, userSingapore.position.latitude, 0.000001)
                assertEquals(0.0, userSingapore.position.longitude, 0.000001)

                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `upsertHotLocations does not create duplicate when called twice`() =
        runTest {
            repository.upsertHotLocations(hot, hotIds)
            repository.upsertHotLocations(hot, hotIds)

            repository.getFavorites().test {
                val list = awaitItem()
                assertEquals(hot.size, list.size)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `upsertHotLocations updates coordinates on second call via id lookup`() =
        runTest {
            // First upsert inserts all hot locations
            repository.upsertHotLocations(hot, hotIds)

            repository.getFavorites().test {
                val initialList = awaitItem()
                assertEquals(hot.size, initialList.size)
                val initialSingapore = initialList.first { it.id == "hot_singapore_singapore" }
                assertEquals(1.288719, initialSingapore.position.latitude, 0.000001)
                assertEquals(103.848742, initialSingapore.position.longitude, 0.000001)
                cancelAndIgnoreRemainingEvents()
            }

            // Manually update hot_singapore to wrong coordinates
            val wrongEntity = dao.getById("hot_singapore_singapore")!!.copy(latitude = 99.99, longitude = 99.99)
            dao.update(wrongEntity)

            // Second upsert should find and update via ID
            repository.upsertHotLocations(hot, hotIds)

            repository.getFavorites().test {
                val finalList = awaitItem()
                // Should still have exactly hot.size entries (no duplicate created)
                assertEquals(hot.size, finalList.size)
                // hot_singapore should be updated back to correct coordinates
                val finalSingapore = finalList.first { it.id == "hot_singapore_singapore" }
                assertEquals(1.288719, finalSingapore.position.latitude, 0.000001)
                assertEquals(103.848742, finalSingapore.position.longitude, 0.000001)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `removeHotLocations deletes hot_ prefixed entries`() =
        runTest {
            repository.upsertHotLocations(hot, hotIds)
            repository.removeHotLocations()

            repository.getFavorites().test {
                val list = awaitItem()
                assertTrue(list.isEmpty())
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `removeHotLocations preserves user favorites with non-hot_ ids`() =
        runTest {
            repository.addFavorite("user-1", "My Place", LatLng(10.0, 20.0), createdAt = 1_000L)
            repository.upsertHotLocations(hot, hotIds)
            repository.removeHotLocations()

            repository.getFavorites().test {
                val list = awaitItem()
                assertEquals(1, list.size)
                assertEquals("My Place", list.first().name)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `removeHotLocations preserves user favorite that had name collision with hot location`() =
        runTest {
            // User had "Singapore" before hot locations were enabled — upsert does NOT modify it (separate ID)
            repository.addFavorite("user-id", "Singapore", LatLng(0.0, 0.0), createdAt = 1_000L)
            repository.upsertHotLocations(hot, hotIds)
            repository.removeHotLocations()

            // "Singapore" kept because its id is "user-id", not "hot_*"
            // Coords remain unchanged (0.0, 0.0) because upsert only touched the hot_singapore entry
            repository.getFavorites().test {
                val list = awaitItem()
                assertEquals(1, list.size)
                assertEquals("Singapore", list.first().name)
                assertEquals("user-id", list.first().id)
                assertEquals(0.0, list.first().position.latitude, 0.000001)
                assertEquals(0.0, list.first().position.longitude, 0.000001)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `upsertHotLocations inserts only selected ids`() =
        runTest {
            repository.upsertHotLocations(hot, setOf("hot_osaka_osaka"))

            repository.getFavorites().test {
                assertEquals(listOf("hot_osaka_osaka"), awaitItem().map { it.id })
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `upsertHotLocations deletes hot favorites no longer listed and keeps user favorites`() =
        runTest {
            repository.upsertHotLocations(hot, hotIds)
            repository.addFavorite("user-id", "Osaka", LatLng(1.0, 2.0), createdAt = 1_000L)

            // Upstream dropped Osaka and Sydney.
            repository.upsertHotLocations(hot.take(1), hotIds)

            repository.getFavorites().test {
                assertEquals(setOf("hot_singapore_singapore", "user-id"), awaitItem().map { it.id }.toSet())
                cancelAndIgnoreRemainingEvents()
            }
        }
}
