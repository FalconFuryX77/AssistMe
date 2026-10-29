package com.assistme.service

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.os.Build
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import androidx.annotation.RequiresApi
import com.assistme.clicky.ClickyGuideController
import com.assistme.clicky.ClickyGuideStepInput

/**
 * Native Android Accessibility Service for AssistMe.
 *
 * Dispatches remote gestures (Tap, Drag, Long Press, Key Events) using Android's
 * AccessibilityService.dispatchGesture API and detects sensitive foreground windows / FLAG_SECURE.
 */
class AssistMeAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "AssistMeAccessibility"
        var instance: AssistMeAccessibilityService? = null
            private set

        private const val CLICK_DURATION_MS = 50L
        private const val LONG_PRESS_DURATION_MS = 600L
    }

    @Volatile
    var isSensitiveWindowFocused: Boolean = false
        private set

    /** Clicky guide walkthrough; created lazily the first time a guide is started. */
    private var clickyGuide: ClickyGuideController? = null

    val isClickyGuideActive: Boolean
        get() = clickyGuide?.isActive == true

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.i(TAG, "AssistMe Accessibility Service connected and ready for gesture dispatch.")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return

        when (event.eventType) {
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED,
            AccessibilityEvent.TYPE_WINDOWS_CHANGED -> {
                val packageName = event.packageName?.toString()?.lowercase() ?: ""
                // Clicky's own card can emit window events. They must not clear a
                // sensitive-screen latch that belongs to the app underneath it.
                if (isClickyGuideActive && packageName == this.packageName.lowercase()) {
                    return
                }
                val className = event.className?.toString()?.lowercase() ?: ""

                // Check for sensitive windows (passwords, banking apps, 2FA, system permission prompts)
                val isSensitive = packageName.contains("password") ||
                                  packageName.contains("bank") ||
                                  packageName.contains("wallet") ||
                                  packageName.contains("pay") ||
                                  packageName.contains("authenticator") ||
                                  packageName.contains("bitwarden") ||
                                  packageName.contains("keepass") ||
                                  packageName.contains("1password") ||
                                  packageName.contains("permissioncontroller") ||
                                  packageName.contains("packageinstaller") ||
                                  className.contains("credentials") ||
                                  className.contains("password") ||
                                  className.contains("grantpermissions")

                isSensitiveWindowFocused = isSensitive
                if (isSensitive) {
                    Log.w(TAG, "FLAG_SECURE / Sensitive window active ($packageName / $className) - Remote control latched.")
                }
            }
        }

        clickyGuide?.let { guide -> if (guide.isActive) guide.onAccessibilityEvent(event) }
    }

    /** Starts (or restarts) a Clicky walkthrough of a saved guide. Main thread only. */
    fun startClickyGuide(title: String, steps: List<ClickyGuideStepInput>, startIndex: Int): Boolean {
        val guide = clickyGuide ?: ClickyGuideController(this) { isSensitiveWindowFocused }
            .also { clickyGuide = it }
        return guide.start(title, steps, startIndex)
    }

    fun stopClickyGuide() {
        clickyGuide?.stop()
    }

    override fun onUnbind(intent: android.content.Intent?): Boolean {
        clickyGuide?.stop()
        return super.onUnbind(intent)
    }

    override fun onInterrupt() {
        Log.w(TAG, "AssistMe Accessibility Service interrupted.")
    }

    override fun onDestroy() {
        clickyGuide?.stop()
        clickyGuide = null
        super.onDestroy()
        instance = null
        Log.i(TAG, "AssistMe Accessibility Service destroyed.")
    }

    /**
     * Obtains the real physical display dimensions of the screen (in pixels).
     * This matches the coordinate system of MediaProjection screen capture and dispatchGesture.
     */
    private fun getRealScreenSize(): android.graphics.Point {
        val windowManager = getSystemService(android.content.Context.WINDOW_SERVICE) as? android.view.WindowManager
        return if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R && windowManager != null) {
            val bounds = windowManager.currentWindowMetrics.bounds
            android.graphics.Point(bounds.width(), bounds.height())
        } else {
            val point = android.graphics.Point()
            @Suppress("DEPRECATION")
            windowManager?.defaultDisplay?.getRealSize(point)
            if (point.x == 0 || point.y == 0) {
                point.x = resources.displayMetrics.widthPixels
                point.y = resources.displayMetrics.heightPixels
            }
            point
        }
    }

    /**
     * Dispatches a single tap gesture at absolute pixel coordinates (x, y).
     * Uses lineTo for a valid path and 50ms delay.
     */
    @RequiresApi(Build.VERSION_CODES.N)
    fun dispatchTap(x: Float, y: Float, callback: GestureResultCallback? = null): Boolean {
        val path = Path().apply {
            moveTo(x, y)
            lineTo(x, y + 1f)
        }
        val stroke = GestureDescription.StrokeDescription(path, 0, CLICK_DURATION_MS)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()

        return dispatchGesture(gesture, callback, null)
    }

    /**
     * Dispatches a drag/swipe gesture from (startX, startY) to (endX, endY).
     * Automatically handles drag-and-drop (holding down before moving) when durationMs >= 450ms.
     */
    @RequiresApi(Build.VERSION_CODES.N)
    fun dispatchDrag(
        startX: Float,
        startY: Float,
        endX: Float,
        endY: Float,
        durationMs: Long = 180L,
        callback: GestureResultCallback? = null
    ): Boolean {
        val builder = GestureDescription.Builder()
        if (durationMs >= 450L && Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            // Drag and drop: Dwell at start position for 450ms to grab/lift icon or widget before moving
            val holdPath = Path().apply {
                moveTo(startX, startY)
                lineTo(startX, startY + 1f)
            }
            val holdStroke = GestureDescription.StrokeDescription(holdPath, 0, 450L, true)
            val movePath = Path().apply {
                moveTo(startX, startY + 1f)
                lineTo(endX, endY)
            }
            val moveStroke = holdStroke.continueStroke(movePath, 0, (durationMs - 450L).coerceAtLeast(200L), false)
            builder.addStroke(holdStroke)
            builder.addStroke(moveStroke)
        } else {
            val path = Path().apply {
                moveTo(startX, startY)
                lineTo(endX, endY)
            }
            val stroke = GestureDescription.StrokeDescription(path, 0, durationMs.coerceIn(100L, 1000L))
            builder.addStroke(stroke)
        }
        val gesture = builder.build()
        return dispatchGesture(gesture, callback, null)
    }

    /**
     * Dispatches a long-press gesture at (x, y).
     */
    @RequiresApi(Build.VERSION_CODES.N)
    fun dispatchLongPress(x: Float, y: Float, callback: GestureResultCallback? = null): Boolean {
        val path = Path().apply {
            moveTo(x, y)
            lineTo(x, y + 1f)
        }
        val stroke = GestureDescription.StrokeDescription(path, 0, LONG_PRESS_DURATION_MS)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()

        return dispatchGesture(gesture, callback, null)
    }

    /**
     * Dispatches global Android navigation actions (Back, Home, Recents, Notifications).
     */
    fun dispatchGlobalAction(action: String): Boolean {
        return when (action.lowercase()) {
            "back" -> performGlobalAction(GLOBAL_ACTION_BACK)
            "home" -> performGlobalAction(GLOBAL_ACTION_HOME)
            "recents" -> performGlobalAction(GLOBAL_ACTION_RECENTS)
            "notifications" -> performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS)
            else -> false
        }
    }

    /** Dispatches the normalized event received from the helper phone.
     * Accurately scales normalized coordinates to the real physical display dimensions.
     * Enforces native security boundaries: Panic Safe Zone (top 10%) & sensitive app lock.
     */
    @RequiresApi(Build.VERSION_CODES.N)
    fun dispatchInput(event: Map<*, *>): Boolean {
        if (isSensitiveWindowFocused) {
            Log.w(TAG, "BLOCKED input: Sensitive window/credential prompt is active.")
            return false
        }

        val realSize = getRealScreenSize()
        val screenW = realSize.x.toFloat()
        val screenH = realSize.y.toFloat()

        val normalizedX = (event["normalized_x"] as? Number)?.toFloat()
            ?: (((event["x"] as? Number)?.toFloat() ?: 0f).let { if (it > 1f) it / screenW else it })
        val normalizedY = (event["normalized_y"] as? Number)?.toFloat()
            ?: (((event["y"] as? Number)?.toFloat() ?: 0f).let { if (it > 1f) it / screenH else it })

        val x = (normalizedX * screenW).coerceIn(0f, screenW - 1f)
        val y = (normalizedY * screenH).coerceIn(0f, screenH - 1f)

        return when ((event["event_type"] as? String)?.lowercase()) {
            "tap" -> dispatchTap(x, y)
            "long_press" -> dispatchLongPress(x, y)
            "drag" -> {
                val normEndX = (event["normalized_end_x"] as? Number)?.toFloat()
                    ?: (((event["end_x"] as? Number)?.toFloat() ?: normalizedX).let { if (it > 1f) it / screenW else it })
                val normEndY = (event["normalized_end_y"] as? Number)?.toFloat()
                    ?: (((event["end_y"] as? Number)?.toFloat() ?: normalizedY).let { if (it > 1f) it / screenH else it })

                val endX = (normEndX * screenW).coerceIn(0f, screenW - 1f)
                val endY = (normEndY * screenH).coerceIn(0f, screenH - 1f)

                dispatchDrag(
                    x,
                    y,
                    endX,
                    endY,
                    (event["duration_ms"] as? Number)?.toLong() ?: 180L
                )
            }
            "key_event" -> dispatchGlobalAction(event["key_code"] as? String ?: "")
            else -> false
        }
    }
}
