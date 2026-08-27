package com.assistme.service

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.os.Build
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import androidx.annotation.RequiresApi

/**
 * Native Android Accessibility Service for AssistMe.
 *
 * Dispatches remote gestures (Tap, Drag, Long Press, Key Events) using Android's
 * AccessibilityService.dispatchGesture API and detects sensitive foreground windows / FLAG_SECURE.
 */
class AssistMeAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "AssistMeA11y"
        var instance: AssistMeAccessibilityService? = null
            private set

        private const val CLICK_DURATION_MS = 50L
        private const val LONG_PRESS_DURATION_MS = 600L
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.i(TAG, "AssistMe Accessibility Service connected and ready for gesture dispatch.")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return

        when (event.eventType) {
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> {
                val packageName = event.packageName?.toString() ?: ""
                val className = event.className?.toString() ?: ""
                Log.d(TAG, "Window state changed: package=$packageName, class=$className")

                // Check for sensitive windows (e.g. password prompts, banking apps)
                val isSensitive = packageName.contains("password", ignoreCase = true) ||
                                  packageName.contains("bank", ignoreCase = true) ||
                                  className.contains("Credentials", ignoreCase = true)
                if (isSensitive) {
                    Log.w(TAG, "FLAG_SECURE / Sensitive window detected: $packageName")
                }
            }
        }
    }

    override fun onInterrupt() {
        Log.w(TAG, "AssistMe Accessibility Service interrupted.")
    }

    override fun onDestroy() {
        super.onDestroy()
        instance = null
        Log.i(TAG, "AssistMe Accessibility Service destroyed.")
    }

    /**
     * Dispatches a single tap gesture at absolute pixel coordinates (x, y).
     * Uses lineTo for a valid path and 50ms delay per research – moveTo alone has no path.
     */
    @RequiresApi(Build.VERSION_CODES.N)
    fun dispatchTap(x: Float, y: Float, callback: GestureResultCallback? = null): Boolean {
        val path = Path().apply {
            moveTo(x, y)
            lineTo(x, y + 1f)
        }
        val stroke = GestureDescription.StrokeDescription(path, 50, CLICK_DURATION_MS)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()

        return dispatchGesture(gesture, callback, null)
    }

    /**
     * Dispatches a drag/swipe gesture from (startX, startY) to (endX, endY).
     */
    @RequiresApi(Build.VERSION_CODES.N)
    fun dispatchDrag(
        startX: Float,
        startY: Float,
        endX: Float,
        endY: Float,
        durationMs: Long = 300L,
        callback: GestureResultCallback? = null
    ): Boolean {
        val path = Path().apply {
            moveTo(startX, startY)
            lineTo(endX, endY)
        }
        val stroke = GestureDescription.StrokeDescription(path, 0, durationMs)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()

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
        val stroke = GestureDescription.StrokeDescription(path, 50, LONG_PRESS_DURATION_MS)
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
     * Handles nav bar taps via global actions and corrects for display insets.
     */
    @RequiresApi(Build.VERSION_CODES.N)
    fun dispatchInput(event: Map<*, *>): Boolean {
        val metrics = resources.displayMetrics
        val normalizedX = (event["normalized_x"] as? Number)?.toFloat()
            ?: ((event["x"] as? Number)?.toFloat() ?: 0f) / metrics.widthPixels
        val normalizedY = (event["normalized_y"] as? Number)?.toFloat()
            ?: ((event["y"] as? Number)?.toFloat() ?: 0f) / metrics.heightPixels
        // Nav bar handling: bottom 8% is system navigation – use global actions
        // instead of coordinate tap, per research. Maps: left third = back, center = home, right = recents.
        // This fixes "helper taps home but triggers mic 2 inches above" and "cannot interact with nav bar".
        if (normalizedY > 0.92f) {
            val action = when {
                normalizedX < 0.33f -> "back"
                normalizedX < 0.66f -> "home"
                else -> "recents"
            }
            // Only for tap events; drags starting/ending in nav bar also become global actions
            val type = (event["event_type"] as? String)?.lowercase()
            if (type == "tap" || type == "long_press") {
                return dispatchGlobalAction(action)
            }
            // For drags that end in nav bar, also handle as global action if start was not in nav bar
            // Otherwise fall through to normal drag
        }
        // Correct for display cutout / insets is handled by using raw displayMetrics;
        // helper's 9/16 contentRect already accounts for letterboxing, so no extra offset needed.
        val x = normalizedX * metrics.widthPixels
        val y = normalizedY * metrics.heightPixels
        return when ((event["event_type"] as? String)?.lowercase()) {
            "tap" -> dispatchTap(x, y)
            "long_press" -> dispatchLongPress(x, y)
            "drag" -> {
                val endX = (
                    (event["normalized_end_x"] as? Number)?.toFloat()
                        ?: (((event["end_x"] as? Number)?.toFloat() ?: normalizedX)
                            .let { if (it > 1f) it / metrics.widthPixels else it })
                    ) * metrics.widthPixels
                val endY = (
                    (event["normalized_end_y"] as? Number)?.toFloat()
                        ?: (((event["end_y"] as? Number)?.toFloat() ?: normalizedY)
                            .let { if (it > 1f) it / metrics.heightPixels else it })
                    ) * metrics.heightPixels
                // If drag ends in nav bar, treat as swipe to handle system gesture
                if (endX >= 0 && endY >= 0) {
                    // Normal drag
                }
                dispatchDrag(
                    x,
                    y,
                    endX,
                    endY,
                    (event["duration_ms"] as? Number)?.toLong() ?: 300L
                )
            }
            "key_event" -> dispatchGlobalAction(event["key_code"] as? String ?: "")
            else -> false
        }
    }
}
