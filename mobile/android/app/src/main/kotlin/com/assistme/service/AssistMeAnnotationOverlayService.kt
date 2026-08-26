package com.assistme.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PixelFormat
import android.os.Build
import android.os.IBinder
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import com.assistme.AssistMeNativeBridge

/** Helpee-owned annotation layer with controls that the helper cannot touch. */
class AssistMeAnnotationOverlayService : Service() {
    companion object {
        private const val CHANNEL_ID = "assistme_annotation_overlay"
        private const val NOTIFICATION_ID = 4002

        var instance: AssistMeAnnotationOverlayService? = null
            private set

        fun start(context: Context) {
            if (!Settings.canDrawOverlays(context)) return
            val intent = Intent(context, AssistMeAnnotationOverlayService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, AssistMeAnnotationOverlayService::class.java))
        }
    }

    private lateinit var windowManager: WindowManager
    private var canvasView: AnnotationCanvasView? = null
    private var controlsView: LinearLayout? = null
    private val strokes = mutableListOf<Map<*, *>>()

    override fun onCreate() {
        super.onCreate()
        instance = this
        windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, notification())
        addOverlayViews()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    private fun addOverlayViews() {
        canvasView = AnnotationCanvasView(this)
        windowManager.addView(canvasView, canvasLayout())

        controlsView = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(8, 8, 8, 8)
            setBackgroundColor(Color.argb(210, 20, 25, 35))
            addView(Button(context).apply {
                text = "Clear"
                setOnClickListener {
                    clearStrokes()
                    AssistMeNativeBridge.channel?.invokeMethod("clear", null)
                }
            })
            addView(Button(context).apply {
                text = "STOP"
                setTextColor(Color.WHITE)
                setBackgroundColor(Color.rgb(210, 45, 75))
                setOnClickListener {
                    AssistMeNativeBridge.channel?.invokeMethod("panic", null)
                    stopSelf()
                }
            })
        }
        windowManager.addView(controlsView, controlsLayout())
    }

    fun updateStrokes(value: Any?) {
        val incoming = value as? List<*> ?: return
        strokes.clear()
        strokes.addAll(incoming.filterIsInstance<Map<*, *>>())
        canvasView?.invalidate()
    }

    fun clearStrokes() {
        strokes.clear()
        canvasView?.invalidate()
    }

    private fun canvasLayout() = WindowManager.LayoutParams(
        WindowManager.LayoutParams.MATCH_PARENT,
        WindowManager.LayoutParams.MATCH_PARENT,
        overlayType(),
        WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
            WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
        PixelFormat.TRANSLUCENT
    ).apply { gravity = Gravity.TOP or Gravity.START }

    private fun controlsLayout() = WindowManager.LayoutParams(
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.WRAP_CONTENT,
        overlayType(),
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
            // Keep helpee-only controls out of the helper's MediaProjection
            // view.  They remain visible and touchable on the helpee phone.
            WindowManager.LayoutParams.FLAG_SECURE,
        PixelFormat.TRANSLUCENT
    ).apply {
        gravity = Gravity.TOP or Gravity.END
        y = 24
    }

    private fun overlayType(): Int = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
    } else {
        @Suppress("DEPRECATION")
        WindowManager.LayoutParams.TYPE_PHONE
    }

    override fun onDestroy() {
        try { canvasView?.let(windowManager::removeView) } catch (_: Exception) {}
        try { controlsView?.let(windowManager::removeView) } catch (_: Exception) {}
        canvasView = null
        controlsView = null
        instance = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            getSystemService(NotificationManager::class.java).createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "AssistMe safety overlay",
                    NotificationManager.IMPORTANCE_LOW
                )
            )
        }
    }

    private fun notification(): Notification {
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        return builder
            .setContentTitle("AssistMe is active")
            .setContentText("Annotations are visible. STOP ends help immediately.")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setOngoing(true)
            .build()
    }

    private inner class AnnotationCanvasView(context: Context) : View(context) {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeCap = Paint.Cap.ROUND
            strokeJoin = Paint.Join.ROUND
        }

        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            strokes.forEach { stroke ->
                val points = stroke["points"] as? List<*> ?: return@forEach
                if (points.size < 2) return@forEach
                val first = points[0] as? Map<*, *> ?: return@forEach
                val path = Path()
                path.moveTo(number(first["x"]) * width, number(first["y"]) * height)
                points.drop(1).forEach { raw ->
                    val point = raw as? Map<*, *> ?: return@forEach
                    path.lineTo(number(point["x"]) * width, number(point["y"]) * height)
                }
                paint.color = (stroke["color"] as? Number)?.toInt() ?: Color.RED
                paint.strokeWidth = maxOf(3f, number(stroke["width"]))
                canvas.drawPath(path, paint)
            }
        }

        private fun number(value: Any?): Float = (value as? Number)?.toFloat() ?: 0f
    }
}
