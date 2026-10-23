package com.locationjoystick.app

import com.locationjoystick.core.common.constants.AppConstants.AdbCommandConstants
import com.locationjoystick.core.model.LatLng
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AdbCommandTest {
    private fun teleport(vararg extras: Pair<String, Any?>) = parseAdbCommand(AdbCommandConstants.ACTION_TELEPORT, extras.toMap()::get)

    @Test
    fun teleport_reads_double_extras() {
        val result = teleport("lat" to 25.033, "lon" to 121.5654)
        assertEquals(AdbCommand.Teleport(LatLng(25.033, 121.5654)), result.getOrThrow())
    }

    @Test
    fun teleport_accepts_string_and_float_extras() {
        val result = teleport("lat" to " 25.5 ", "lon" to 121)
        assertEquals(AdbCommand.Teleport(LatLng(25.5, 121.0)), result.getOrThrow())
    }

    @Test
    fun teleport_ignores_unknown_extras() {
        val result = teleport("lat" to 1.0, "lon" to 2.0, "future" to "x")
        assertTrue(result.isSuccess)
    }

    @Test
    fun teleport_rejects_missing_coordinate() {
        assertEquals("missing or invalid lon", teleport("lat" to 1.0).exceptionOrNull()?.message)
        assertEquals("missing or invalid lat", teleport("lon" to 1.0).exceptionOrNull()?.message)
    }

    @Test
    fun teleport_rejects_unparseable_string() {
        assertTrue(teleport("lat" to "abc", "lon" to 1.0).isFailure)
    }

    @Test
    fun teleport_rejects_out_of_range() {
        assertEquals("lat out of range", teleport("lat" to 90.1, "lon" to 0.0).exceptionOrNull()?.message)
        assertEquals("lon out of range", teleport("lat" to 0.0, "lon" to -180.5).exceptionOrNull()?.message)
        assertTrue(teleport("lat" to Double.NaN, "lon" to 0.0).isFailure)
    }

    @Test
    fun teleport_accepts_boundary_values() {
        assertTrue(teleport("lat" to -90.0, "lon" to 180.0).isSuccess)
    }

    @Test
    fun unknown_action_fails() {
        assertTrue(parseAdbCommand("com.example.OTHER") { null }.isFailure)
        assertTrue(parseAdbCommand(null) { null }.isFailure)
    }

    private fun overlay(raw: Any?) = parseAdbCommand(AdbCommandConstants.ACTION_OVERLAY, mapOf("visible" to raw)::get)

    @Test
    fun overlay_reads_a_boolean_extra() {
        assertEquals(AdbCommand.SetOverlayVisible(false), overlay(false).getOrThrow())
        assertEquals(AdbCommand.SetOverlayVisible(true), overlay(true).getOrThrow())
    }

    @Test
    fun overlay_accepts_words_and_numbers_as_strings() {
        for (hide in listOf("false", "FALSE", " 0 ", "no", "hide")) {
            assertEquals(hide, AdbCommand.SetOverlayVisible(false), overlay(hide).getOrThrow())
        }
        for (show in listOf("true", "1", "yes", "show")) {
            assertEquals(show, AdbCommand.SetOverlayVisible(true), overlay(show).getOrThrow())
        }
    }

    @Test
    fun overlay_rejects_a_missing_or_unclear_value() {
        assertTrue(overlay(null).isFailure)
        assertTrue(overlay("maybe").isFailure)
        assertTrue(overlay(2).isFailure)
    }
}
