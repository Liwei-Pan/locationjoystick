package com.locationjoystick.app

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import com.locationjoystick.core.location.MapController
import com.locationjoystick.core.overlay.OverlayService
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

private const val TAG = "AdbCommandReceiver"

/**
 * Entry point for `adb shell am broadcast` commands. The manifest guards it with
 * `android.permission.DUMP`, which only the adb shell (and the system) holds, so other apps
 * cannot send these broadcasts. Each command calls the same [MapController] method as the UI,
 * like the Control API, and ignores the Hide Teleport setting (docs/features/adb-commands.md).
 */
@AndroidEntryPoint
class AdbCommandReceiver : BroadcastReceiver() {
    @Inject lateinit var mapController: MapController

    override fun onReceive(
        context: Context,
        intent: Intent,
    ) {
        val extras = intent.extras
        val result = parseAdbCommand(intent.action) { extras?.get(it) }
        val command = result.getOrNull()
        if (command == null) {
            val reason = result.exceptionOrNull()?.message ?: "invalid command"
            Log.w(TAG, "Rejected ${intent.action}: $reason")
            reply(Activity.RESULT_CANCELED, reason)
            return
        }
        when (command) {
            is AdbCommand.Teleport ->
                // Idle service ignores a bare position update, so begin spoofing at the target instead.
                if (mapController.isSpoofing.value) {
                    mapController.teleportTo(command.position)
                } else {
                    mapController.startSpoofingAt(command.position)
                }
            is AdbCommand.SetOverlayVisible ->
                // The overlay services listen for these on a receiver that is not exported (only this app may send
                // to it), so the command is relayed from here.
                context.sendBroadcast(
                    Intent(if (command.visible) OverlayService.ACTION_OVERLAY_SHOW else OverlayService.ACTION_OVERLAY_HIDE)
                        .setPackage(context.packageName),
                )
        }
        reply(Activity.RESULT_OK, "ok")
    }

    // `am broadcast` sends ordered broadcasts and prints the result, so a typo shows up in the terminal.
    private fun reply(
        code: Int,
        message: String,
    ) {
        if (isOrderedBroadcast) setResult(code, message, null)
    }
}
