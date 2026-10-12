package com.locationjoystick.core.model

/** Hot locations carry their country in `category`; user groups never apply to them. */
fun FavoriteLocation.isHot(): Boolean = id.startsWith("hot_")

fun Route.isHot(): Boolean = id.startsWith("hot_route_")
