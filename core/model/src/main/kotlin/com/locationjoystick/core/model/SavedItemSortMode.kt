package com.locationjoystick.core.model

enum class SavedItemSortMode {
    NAME_ASCENDING,
    NAME_DESCENDING,
    NEWEST_FIRST,
    OLDEST_FIRST,
}

/**
 * [sortedBySavedItemMode] then, when [manualOrder] (drag-set ids) is non-empty, items it lists
 * follow it. Items it does not list (added since) stay first, in the sort mode's order.
 */
fun <T : HasCreatedAt> List<T>.sortedBySavedItemMode(
    mode: SavedItemSortMode,
    manualOrder: List<String>,
    idOf: (T) -> String,
    nameOf: (T) -> String,
): List<T> {
    val base = sortedBySavedItemMode(mode, nameOf)
    if (manualOrder.isEmpty()) return base
    val rank = manualOrder.withIndex().associate { it.value to it.index }
    return base.sortedBy { rank[idOf(it)] ?: -1 }
}

fun <T : HasCreatedAt> List<T>.sortedBySavedItemMode(
    mode: SavedItemSortMode,
    nameOf: (T) -> String,
): List<T> =
    when (mode) {
        SavedItemSortMode.NAME_ASCENDING -> sortedWith(compareBy(String.CASE_INSENSITIVE_ORDER, nameOf))
        SavedItemSortMode.NAME_DESCENDING -> sortedWith(compareByDescending(String.CASE_INSENSITIVE_ORDER, nameOf))
        SavedItemSortMode.NEWEST_FIRST -> sortedByDescending { it.createdAt }
        SavedItemSortMode.OLDEST_FIRST -> sortedBy { it.createdAt }
    }
