package com.locationjoystick.app

import com.locationjoystick.core.common.constants.AppConstants.CompassTrackingConstants
import com.locationjoystick.feature.map.api.MAP_ROUTE
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FirstRunCompassDisclosureTest {
    private val unanswered = CompassTrackingConstants.DISCLOSURE_UNANSWERED

    @Test
    fun `unanswered on map at API 30 shows`() {
        assertTrue(shouldShowFirstRunCompassDisclosure(MAP_ROUTE, unanswered, 30))
    }

    @Test
    fun `any stored answer or unloaded choice does not show`() {
        assertFalse(shouldShowFirstRunCompassDisclosure(MAP_ROUTE, null, 30))
        assertFalse(shouldShowFirstRunCompassDisclosure(MAP_ROUTE, CompassTrackingConstants.DISCLOSURE_ACCEPTED, 30))
        assertFalse(shouldShowFirstRunCompassDisclosure(MAP_ROUTE, CompassTrackingConstants.DISCLOSURE_DECLINED, 30))
        assertFalse(shouldShowFirstRunCompassDisclosure(MAP_ROUTE, CompassTrackingConstants.DISCLOSURE_SKIPPED, 30))
    }

    @Test
    fun `other routes and API below 30 do not show`() {
        assertFalse(shouldShowFirstRunCompassDisclosure(IDLE_ROUTE, unanswered, 30))
        assertFalse(shouldShowFirstRunCompassDisclosure(null, unanswered, 30))
        assertFalse(shouldShowFirstRunCompassDisclosure(MAP_ROUTE, unanswered, 29))
    }
}
