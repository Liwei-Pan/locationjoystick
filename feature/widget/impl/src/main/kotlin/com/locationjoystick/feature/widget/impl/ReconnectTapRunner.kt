package com.locationjoystick.feature.widget.impl

import com.locationjoystick.core.common.constants.AppConstants.ReconnectTapConstants
import kotlinx.coroutines.delay
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.ln
import kotlin.math.roundToInt
import kotlin.math.sqrt
import kotlin.random.Random

enum class ReconnectRunResult { NOT_OFF, RECONNECTED, FAILED }

/** Control center plus a Gaussian offset, clamped to stay inside the ball. Screen pixels. */
internal fun jitteredTapPoint(
    control: ReconnectControl,
    screenWidth: Int,
    random: Random,
): Pair<Int, Int> {
    val sigma = ReconnectTapConstants.TAP_SIGMA_WIDTH_FRACTION * screenWidth
    val clamp = ReconnectTapConstants.TAP_CLAMP_WIDTH_FRACTION * screenWidth

    fun offset(): Int {
        // Box-Muller; 1 - nextDouble() keeps ln() away from zero.
        val g = sqrt(-2.0 * ln(1.0 - random.nextDouble())) * cos(2.0 * PI * random.nextDouble())
        return (g * sigma).toFloat().coerceIn(-clamp, clamp).roundToInt()
    }
    return control.centerX + offset() to control.centerY + offset()
}

/**
 * One reconnect run. Taps only on a fresh OFF read: two OFF reads, then up to MAX_TAPS taps, each
 * followed by a poll window; a retap needs every poll read OFF. An absent or unknown control (null) never taps.
 */
internal suspend fun runReconnectTap(
    screenWidth: Int,
    capture: suspend () -> ReconnectControl?,
    tap: suspend (x: Int, y: Int, durationMs: Long) -> Boolean,
    random: Random = Random.Default,
): ReconnectRunResult {
    var control = capture()?.takeIf { it.state == ReconnectState.OFF } ?: return ReconnectRunResult.NOT_OFF
    delay(ReconnectTapConstants.CONFIRM_DELAY_MS)
    control = capture()?.takeIf { it.state == ReconnectState.OFF } ?: return ReconnectRunResult.NOT_OFF

    repeat(ReconnectTapConstants.MAX_TAPS) {
        delay(random.nextLong(ReconnectTapConstants.PRE_TAP_DELAY_MIN_MS, ReconnectTapConstants.PRE_TAP_DELAY_MAX_MS + 1))
        val (x, y) = jitteredTapPoint(control, screenWidth, random)
        tap(x, y, random.nextLong(ReconnectTapConstants.GESTURE_MIN_MS, ReconnectTapConstants.GESTURE_MAX_MS + 1))
        delay(ReconnectTapConstants.SETTLE_DELAY_MS)
        // A slow connect still reads OFF for a few seconds; retap only if every poll read is OFF.
        repeat(ReconnectTapConstants.SETTLE_POLL_READS) { read ->
            val after = capture() ?: return ReconnectRunResult.FAILED
            if (after.state == ReconnectState.ON) return ReconnectRunResult.RECONNECTED
            control = after
            if (read < ReconnectTapConstants.SETTLE_POLL_READS - 1) delay(ReconnectTapConstants.SETTLE_POLL_INTERVAL_MS)
        }
    }
    return ReconnectRunResult.FAILED
}
