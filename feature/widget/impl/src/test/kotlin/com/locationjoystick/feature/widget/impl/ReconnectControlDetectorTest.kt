package com.locationjoystick.feature.widget.impl

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import javax.imageio.ImageIO
import kotlin.math.abs

/** Real night-map screenshots, 864x1920, control at about (791, 240) in both states. */
class ReconnectControlDetectorTest {
    private class Shot(
        val pixels: IntArray,
        val width: Int,
        val height: Int,
    )

    private fun load(path: String): Shot {
        val img = ImageIO.read(checkNotNull(javaClass.classLoader.getResourceAsStream(path)) { "Missing fixture $path" })
        val px = IntArray(img.width * img.height)
        img.getRGB(0, 0, img.width, img.height, px, 0, img.width)
        return Shot(px, img.width, img.height)
    }

    private fun detect(path: String): ReconnectControl? = load(path).let { ReconnectControlDetector.detect(it.pixels, it.width, it.height) }

    private fun assertNearControl(c: ReconnectControl) {
        assertTrue("x=${c.centerX}", abs(c.centerX - 791) <= 6)
        assertTrue("y=${c.centerY}", abs(c.centerY - 240) <= 6)
    }

    @Test
    fun connected_readsOn() {
        val c = checkNotNull(detect("reconnect/hud_on_night.png"))
        assertEquals(ReconnectState.ON, c.state)
        assertNearControl(c)
    }

    @Test
    fun disconnected_readsOff() {
        val c = checkNotNull(detect("reconnect/hud_off_night.png"))
        assertEquals(ReconnectState.OFF, c.state)
        assertNearControl(c)
    }

    @Test
    fun screenWithoutControl_returnsNull() {
        assertNull(detect("compass/pogo_orientation_a.png"))
    }

    @Test
    fun blank_returnsNull() {
        assertNull(ReconnectControlDetector.detect(IntArray(200 * 400), 200, 400))
    }
}
