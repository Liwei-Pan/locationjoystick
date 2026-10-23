package com.locationjoystick.app

import com.locationjoystick.core.common.constants.AppConstants.AdbCommandConstants
import com.locationjoystick.core.model.LatLng

/**
 * A command sent from a computer with `adb shell am broadcast` (docs/features/adb-commands.md).
 * New commands are new subtypes plus a branch in [parseAdbCommand]; extras a command does not
 * read are ignored, so a command can gain optional parameters without breaking older callers.
 */
internal sealed interface AdbCommand {
    data class Teleport(
        val position: LatLng,
    ) : AdbCommand

    /** Show or hide the floating joystick and widget (for screenshots: they cover part of the game map). */
    data class SetOverlayVisible(
        val visible: Boolean,
    ) : AdbCommand
}

/**
 * Parses a broadcast [action] and its extras ([extra] looks one up by name). `am broadcast`
 * sends `--ed` as Double, `--ef` as Float, `--ei` as Int and `--es` as String; all four are
 * accepted so a shell-quoting slip does not silently drop a coordinate.
 */
internal fun parseAdbCommand(
    action: String?,
    extra: (String) -> Any?,
): Result<AdbCommand> =
    when (action) {
        AdbCommandConstants.ACTION_TELEPORT -> parseTeleport(extra)
        AdbCommandConstants.ACTION_OVERLAY -> parseOverlay(extra)
        else -> Result.failure(IllegalArgumentException("unknown action: $action"))
    }

private fun parseTeleport(extra: (String) -> Any?): Result<AdbCommand> {
    val lat = coordinate(extra(AdbCommandConstants.EXTRA_LAT), AdbCommandConstants.EXTRA_LAT, 90.0)
    val lon = coordinate(extra(AdbCommandConstants.EXTRA_LON), AdbCommandConstants.EXTRA_LON, 180.0)
    return when {
        lat.isFailure -> Result.failure(lat.exceptionOrNull()!!)
        lon.isFailure -> Result.failure(lon.exceptionOrNull()!!)
        else -> Result.success(AdbCommand.Teleport(LatLng(lat.getOrThrow(), lon.getOrThrow())))
    }
}

/** `--ez visible false` sends a Boolean; a String ("false", "0", "no") is accepted too. */
private fun parseOverlay(extra: (String) -> Any?): Result<AdbCommand> {
    val visible =
        when (val raw = extra(AdbCommandConstants.EXTRA_VISIBLE)) {
            is Boolean -> raw
            is String ->
                when (raw.trim().lowercase()) {
                    "true", "1", "yes", "show" -> true
                    "false", "0", "no", "hide" -> false
                    else -> null
                }
            else -> null
        } ?: return Result.failure(IllegalArgumentException("missing or invalid ${AdbCommandConstants.EXTRA_VISIBLE}"))
    return Result.success(AdbCommand.SetOverlayVisible(visible))
}

private fun coordinate(
    raw: Any?,
    name: String,
    limit: Double,
): Result<Double> {
    val value =
        when (raw) {
            is Number -> raw.toDouble()
            is String -> raw.trim().toDoubleOrNull()
            else -> null
        } ?: return Result.failure(IllegalArgumentException("missing or invalid $name"))
    if (value.isNaN() || value !in -limit..limit) {
        return Result.failure(IllegalArgumentException("$name out of range"))
    }
    return Result.success(value)
}
