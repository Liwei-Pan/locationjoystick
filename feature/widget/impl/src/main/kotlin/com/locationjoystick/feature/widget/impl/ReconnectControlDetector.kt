package com.locationjoystick.feature.widget.impl

import com.locationjoystick.core.common.constants.AppConstants.CompassTrackingConstants

enum class ReconnectState { ON, OFF }

/** [centerX]/[centerY] are screen pixels at the ball's center; [state] is what its colors say. */
data class ReconnectControl(
    val state: ReconnectState,
    val centerX: Int,
    val centerY: Int,
)

/**
 * Finds the companion-device control in a screenshot and reads whether it is connected.
 *
 * Pure over ARGB pixels (no Bitmap) so it tests on the JVM. Color-only, no text, so it holds in
 * every UI language. Returns null when no control is found; null never means "tap".
 *
 * ON: a pure-green center dot with pure red directly above it. OFF: the dimmed ball, a flat
 * light-blue ring and lower half with a flat rose upper half inside it. Both colors were measured
 * on the night map (docs/features/bluetooth-reconnect-tap.md, "Measured on screenshots").
 */
object ReconnectControlDetector {
    // Half-width of the match window per channel. The overlay colors are flat, the map is not.
    private const val TOLERANCE = 14

    private val OFF_BLUE = intArrayOf(86, 156, 212)
    private val OFF_ROSE = intArrayOf(150, 97, 122)

    // Ball diameter ~7.2% of screen width; the green dot is ~2.3% and the OFF ring ~7%.
    private const val MIN_DOT_FRACTION = 0.012f
    private const val MAX_DOT_FRACTION = 0.045f
    private const val MIN_HALF_FRACTION = 0.04f
    private const val MAX_HALF_FRACTION = 0.10f

    // Share of the band above the green dot that must be red (the ball's top half is thin there).
    private const val MIN_ABOVE_SHARE = 0.1f

    fun detect(
        pixels: IntArray,
        width: Int,
        height: Int,
    ): ReconnectControl? {
        val x0 = (width * CompassTrackingConstants.SEARCH_X_MIN_PCT).toInt()
        val y1 = (height * CompassTrackingConstants.SEARCH_Y_MAX_PCT).toInt()
        val region = Region(pixels, width, x0, 0, width, y1)
        return findOn(region) ?: findOff(region)
    }

    private fun findOn(r: Region): ReconnectControl? {
        val dot =
            r
                .components { rgb -> rgb[1] > 200 && rgb[0] < 80 && rgb[2] < 80 }
                .firstOrNull {
                    it.fits(r.screenWidth, MIN_DOT_FRACTION, MAX_DOT_FRACTION) &&
                        r.hasAbove(it) { c -> c[0] > 200 && c[1] < 60 && c[2] < 60 }
                }
                ?: return null
        return ReconnectControl(ReconnectState.ON, dot.centerX, dot.centerY)
    }

    private fun findOff(r: Region): ReconnectControl? {
        for (blue in r.components { rgb -> rgb.near(OFF_BLUE) }) {
            if (!blue.fits(r.screenWidth, MIN_HALF_FRACTION, MAX_HALF_FRACTION)) continue
            // The rose upper half sits inside the blue ring; its lower edge is the ball's split line.
            val rose = r.matchBounds(blue) { it.near(OFF_ROSE) } ?: continue
            return ReconnectControl(ReconnectState.OFF, rose.centerX, rose.bottom)
        }
        return null
    }

    private fun IntArray.near(ref: IntArray) = indices.all { kotlin.math.abs(this[it] - ref[it]) <= TOLERANCE }

    private class Blob(
        val left: Int,
        val top: Int,
        val right: Int,
        val bottom: Int,
    ) {
        val centerX get() = (left + right) / 2
        val centerY get() = (top + bottom) / 2

        fun fits(
            screenWidth: Int,
            minFraction: Float,
            maxFraction: Float,
        ): Boolean {
            val w = right - left + 1
            val h = bottom - top + 1
            return w >= screenWidth * minFraction && w <= screenWidth * maxFraction && h * 3 >= w && h <= w * 2
        }
    }

    private class Region(
        val pixels: IntArray,
        val screenWidth: Int,
        val x0: Int,
        val y0: Int,
        val x1: Int,
        val y1: Int,
    ) {
        private val rgb = IntArray(3)

        private fun load(
            x: Int,
            y: Int,
        ): IntArray {
            val p = pixels[y * screenWidth + x]
            rgb[0] = (p shr 16) and 0xFF
            rgb[1] = (p shr 8) and 0xFF
            rgb[2] = p and 0xFF
            return rgb
        }

        /** 4-connected components of pixels matching [match], as bounding boxes. */
        fun components(match: (IntArray) -> Boolean): List<Blob> {
            val w = x1 - x0
            val seen = BooleanArray(w * (y1 - y0))
            val out = ArrayList<Blob>()
            val stack = ArrayDeque<Int>()
            for (sy in y0 until y1) {
                for (sx in x0 until x1) {
                    val si = (sy - y0) * w + (sx - x0)
                    if (seen[si] || !match(load(sx, sy))) continue
                    var l = sx
                    var t = sy
                    var rt = sx
                    var b = sy
                    seen[si] = true
                    stack.add(si)
                    while (stack.isNotEmpty()) {
                        val i = stack.removeLast()
                        val x = x0 + i % w
                        val y = y0 + i / w
                        l = minOf(l, x)
                        rt = maxOf(rt, x)
                        t = minOf(t, y)
                        b = maxOf(b, y)
                        for ((nx, ny) in arrayOf(x - 1 to y, x + 1 to y, x to y - 1, x to y + 1)) {
                            if (nx < x0 || nx >= x1 || ny < y0 || ny >= y1) continue
                            val ni = (ny - y0) * w + (nx - x0)
                            if (!seen[ni] && match(load(nx, ny))) {
                                seen[ni] = true
                                stack.add(ni)
                            }
                        }
                    }
                    out.add(Blob(l, t, rt, b))
                }
            }
            return out
        }

        /** Bounding box of [match] pixels inside [blob]'s box, or null when they cover too little of it. */
        fun matchBounds(
            blob: Blob,
            match: (IntArray) -> Boolean,
        ): Blob? {
            var l = Int.MAX_VALUE
            var t = Int.MAX_VALUE
            var rt = -1
            var b = -1
            var n = 0
            for (y in blob.top..blob.bottom) {
                for (x in blob.left..blob.right) {
                    if (!match(load(x, y))) continue
                    n++
                    l = minOf(l, x)
                    rt = maxOf(rt, x)
                    t = minOf(t, y)
                    b = maxOf(b, y)
                }
            }
            val area = (blob.right - blob.left + 1) * (blob.bottom - blob.top + 1)
            return if (n * 10 >= area) Blob(l, t, rt, b) else null
        }

        /** True when a band as wide as [blob], up to 2 blob-widths above it, is mostly [match]. */
        fun hasAbove(
            blob: Blob,
            match: (IntArray) -> Boolean,
        ): Boolean {
            val w = blob.right - blob.left + 1
            val yTop = maxOf(y0, blob.top - 2 * w)
            var hit = 0
            var total = 0
            for (y in yTop until blob.top) {
                for (x in blob.left..blob.right) {
                    total++
                    if (match(load(x, y))) hit++
                }
            }
            return total > 0 && hit >= total * MIN_ABOVE_SHARE
        }
    }
}
