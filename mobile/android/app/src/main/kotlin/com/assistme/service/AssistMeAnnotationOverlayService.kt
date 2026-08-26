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
import android.graphics.PointF
import android.os.Build
import android.os.IBinder
import android.provider.Settings
import android.app.AlertDialog
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.SeekBar
import android.widget.TextView
import com.assistme.AssistMeNativeBridge
import com.assistme.R

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
    private val activePoints = mutableListOf<PointF>()
    private var drawingEnabled = false
    private var drawButton: Button? = null
    private var selectedColor: Int = Color.RED
    private var selectedWidth: Float = 4f
    private var selectedTool: String = "pen" // pen or eraser
    private var penButton: Button? = null
    private var eraserButton: Button? = null
    private var colorButton: Button? = null
    private var initialTouchX = 0f
    private var initialTouchY = 0f
    private var initialLayoutX = 0
    private var initialLayoutY = 0
    private var isDragging = false

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

        // Outer container: handle + scrollable buttons + fixed STOP
        val outer = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(6, 6, 6, 6)
            setBackgroundColor(Color.argb(235, 22, 27, 34))
            // Rounded? use background drawable simulation via padding
        }

        // Drag handle – dedicated, obvious, per VISION §12.7 (large 36dp, ≡ icon)
        val handle = Button(this).apply {
            text = "≡"
            textSize = 18f
            setPadding(4,0,4,0)
            minimumWidth = 0
            minWidth = 0
            layoutParams = LinearLayout.LayoutParams(36, LinearLayout.LayoutParams.MATCH_PARENT).apply { setMargins(0,0,8,0) }
            setBackgroundColor(Color.argb(70, 255, 255, 255))
            setOnTouchListener { _, event ->
                val params = outer.layoutParams as? WindowManager.LayoutParams ?: return@setOnTouchListener false
                when (event.actionMasked) {
                    MotionEvent.ACTION_DOWN -> {
                        initialTouchX = event.rawX
                        initialTouchY = event.rawY
                        initialLayoutX = params.x
                        initialLayoutY = params.y
                        isDragging = false
                    }
                    MotionEvent.ACTION_MOVE -> {
                        val dx = (event.rawX - initialTouchX).toInt()
                        val dy = (event.rawY - initialTouchY).toInt()
                        if (Math.abs(dx) > 4 || Math.abs(dy) > 4) isDragging = true
                        if (isDragging) {
                            params.x = initialLayoutX + dx
                            params.y = initialLayoutY + dy
                            windowManager.updateViewLayout(outer, params)
                            return@setOnTouchListener true
                        }
                    }
                    MotionEvent.ACTION_UP -> {
                        if (isDragging) return@setOnTouchListener true
                    }
                }
                false
            }
        }
        outer.addView(handle)
        // Also allow dragging by touching empty background of outer (not buttons)
        outer.setOnTouchListener { _, event ->
            // Only handle if touch is on outer background, not on a child button – we check if event hit handle area via y
            // For simplicity, allow outer background drag with larger threshold, but let buttons consume clicks
            val params = outer.layoutParams as? WindowManager.LayoutParams ?: return@setOnTouchListener false
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    initialTouchX = event.rawX
                    initialTouchY = event.rawY
                    initialLayoutX = params.x
                    initialLayoutY = params.y
                    isDragging = false
                    // Return false so child buttons still get click, but we monitor move
                    false
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = (event.rawX - initialTouchX).toInt()
                    val dy = (event.rawY - initialTouchY).toInt()
                    if (Math.abs(dx) > 8 || Math.abs(dy) > 8) isDragging = true
                    if (isDragging) {
                        params.x = initialLayoutX + dx
                        params.y = initialLayoutY + dy
                        windowManager.updateViewLayout(outer, params)
                        return@setOnTouchListener true
                    }
                    false
                }
                else -> false
            }
        }

        // Scrollable middle area for pen/eraser/color/etc – ensures STOP always reachable
        val scrollView = HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        val inner = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
        }

        drawButton = Button(this).apply {
            text = "DRAW"
            setOnClickListener { setDrawingEnabled(!drawingEnabled) }
        }
        inner.addView(drawButton)

        penButton = Button(this).apply {
            text = "✏️"
            setOnClickListener { setTool("pen") }
        }
        eraserButton = Button(this).apply {
            text = ""
            // Use the provided eraser PNG (white outline) as drawable – matches helper
            try {
                val d = resources.getDrawable(R.drawable.eraser, null)
                setCompoundDrawablesWithIntrinsicBounds(d, null, null, null)
                compoundDrawablePadding = 0
            } catch (_: Exception) {
                text = "Eraser"
            }
            setOnClickListener { setTool("eraser") }
        }
        inner.addView(penButton)
        inner.addView(eraserButton)
        updateToolUI()

        // Color dropdown – single button opening palette dialog (like helper's tune)
        colorButton = Button(this).apply {
            text = "●"
            setTextColor(selectedColor)
            setBackgroundColor(Color.argb(60, 255,255,255))
            setOnClickListener { showColorPicker() }
        }
        inner.addView(colorButton)

        // Width button
        inner.addView(Button(this).apply {
            text = "W${selectedWidth.toInt()}"
            setOnClickListener { showWidthPicker() }
        })

        inner.addView(Button(this).apply {
            text = "↺"
            setOnClickListener {
                AssistMeNativeBridge.channel?.invokeMethod("undo", null)
            }
        })
        inner.addView(Button(this).apply {
            text = "↻"
            setOnClickListener {
                AssistMeNativeBridge.channel?.invokeMethod("redo", null)
            }
        })
        // Clear – icon ensures text always visible
        inner.addView(Button(this).apply {
            text = "🗑"
            setOnClickListener {
                clearStrokes()
                AssistMeNativeBridge.channel?.invokeMethod("clear", null)
            }
        })

        scrollView.addView(inner)
        outer.addView(scrollView)

        // STOP – fixed outside scroll, always visible, high contrast
        outer.addView(Button(this).apply {
            text = "STOP"
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.rgb(210, 45, 75))
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { setMargins(8,0,0,0) }
            setOnClickListener {
                AssistMeNativeBridge.channel?.invokeMethod("panic", null)
                stopSelf()
            }
        })

        controlsView = outer
        windowManager.addView(outer, controlsLayout())
    }

    private fun setTool(tool: String) {
        selectedTool = tool
        updateToolUI()
        // If eraser selected, drawingEnabled should still be true but we switch behavior
        if (tool == "eraser" && !drawingEnabled) setDrawingEnabled(true)
    }

    private fun updateToolUI() {
        penButton?.alpha = if (selectedTool == "pen") 1f else 0.45f
        eraserButton?.alpha = if (selectedTool == "eraser") 1f else 0.45f
        penButton?.setBackgroundColor(if (selectedTool == "pen") Color.argb(50, 52,199,89) else Color.TRANSPARENT)
        eraserButton?.setBackgroundColor(if (selectedTool == "eraser") Color.argb(50, 255,59,48) else Color.TRANSPARENT)
    }

    private fun showColorPicker() {
        val colors = listOf(Color.RED, Color.YELLOW, Color.GREEN, Color.BLUE, Color.BLACK, Color.argb(255,255,140,0), Color.WHITE, Color.argb(255,128,0,128))
        val names = listOf("Red","Yellow","Green","Blue","Black","Orange","White","Purple")
        AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog)
            .setTitle("Annotation color")
            .setItems(names.toTypedArray()) { _, which ->
                setSelectedColor(colors[which])
            }
            .setNegativeButton("Cancel", null)
            .create().apply {
                window?.setType(controlsLayout().type)
                show()
            }
    }

    private fun showWidthPicker() {
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32,24,32,24)
        }
        val label = TextView(this).apply { text = "Thickness: ${selectedWidth.toInt()}"; textSize = 16f; setTextColor(Color.WHITE) }
        val seek = SeekBar(this).apply {
            max = 16
            progress = selectedWidth.toInt().coerceIn(2,18)
            setOnSeekBarChangeListener(object: SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(s: SeekBar?, p: Int, fromUser: Boolean) {
                    selectedWidth = p.coerceAtLeast(2).toFloat()
                    label.text = "Thickness: ${selectedWidth.toInt()}"
                    colorButton?.text = "●"
                }
                override fun onStartTrackingTouch(s: SeekBar?) {}
                override fun onStopTrackingTouch(s: SeekBar?) {}
            })
        }
        container.addView(label)
        container.addView(seek)
        AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog)
            .setTitle("Thickness")
            .setView(container)
            .setPositiveButton("OK", null)
            .create().apply {
                window?.setType(controlsLayout().type)
                show()
            }
    }

    private fun setSelectedColor(color: Int) {
        selectedColor = color
        colorButton?.setTextColor(color)
        // also update active drawing preview
        canvasView?.invalidate()
    }

    fun updateStrokes(value: Any?) {
        val incoming = value as? List<*> ?: return
        strokes.clear()
        strokes.addAll(incoming.filterIsInstance<Map<*, *>>())
        canvasView?.invalidate()
    }

    fun clearStrokes() {
        activePoints.clear()
        strokes.clear()
        canvasView?.invalidate()
    }

    private fun setDrawingEnabled(enabled: Boolean) {
        drawingEnabled = enabled
        drawButton?.text = if (enabled) "DRAW ON" else "DRAW"
        canvasView?.let { view ->
            val params = view.layoutParams as WindowManager.LayoutParams
            params.flags = canvasFlags()
            windowManager.updateViewLayout(view, params)
        }
    }

    private fun canvasFlags(): Int = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
        WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
        WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or
        WindowManager.LayoutParams.FLAG_SECURE or
        (if (!drawingEnabled) WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE else 0)

    private fun canvasLayout() = WindowManager.LayoutParams(
        WindowManager.LayoutParams.MATCH_PARENT,
        WindowManager.LayoutParams.MATCH_PARENT,
        overlayType(),
        canvasFlags(),
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
        gravity = Gravity.TOP or Gravity.START
        x = 16
        y = 24
    }

    private fun overlayType(): Int = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
    } else {
        @Suppress("DEPRECATION")
        WindowManager.LayoutParams.TYPE_PHONE
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        // User swiped app away – VISION says session should not leave stale overlay/docs on helper's screen.
        // Stop the system overlay so helper doesn't see ghost annotations after helpee closed app.
        stopSelf()
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        try { canvasView?.let(windowManager::removeView) } catch (_: Exception) {}
        try { controlsView?.let(windowManager::removeView) } catch (_: Exception) {}
        canvasView = null
        controlsView = null
        drawButton = null
        penButton = null
        eraserButton = null
        colorButton = null
        activePoints.clear()
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
            .setContentText("Annotations are visible. STOP revokes control immediately.")
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
                drawStroke(canvas, stroke["points"] as? List<*>, stroke)
            }
            if (activePoints.isNotEmpty()) {
                if (activePoints.size == 1) {
                    // Single tap dot – draw circle so first touch is always visible
                    val p = activePoints.first()
                    paint.color = selectedColor
                    paint.style = Paint.Style.FILL
                    canvas.drawCircle(p.x * width, p.y * height, maxOf(4f, selectedWidth/2), paint)
                    paint.style = Paint.Style.STROKE
                } else {
                    val path = Path()
                    path.moveTo(activePoints.first().x * width, activePoints.first().y * height)
                    activePoints.drop(1).forEach { point ->
                        path.lineTo(point.x * width, point.y * height)
                    }
                    paint.color = selectedColor
                    paint.strokeWidth = maxOf(3f, selectedWidth)
                    canvas.drawPath(path, paint)
                }
            }
        }

        private fun drawStroke(canvas: Canvas, points: List<*>?, stroke: Map<*, *>) {
            if (points == null || points.isEmpty()) return
            if (points.size == 1) {
                val p = points[0] as? Map<*, *> ?: return
                paint.color = (stroke["color"] as? Number)?.toInt() ?: Color.RED
                val w = maxOf(3f, number(stroke["width"]))
                paint.style = Paint.Style.FILL
                canvas.drawCircle(number(p["x"]) * width, number(p["y"]) * height, maxOf(4f, w/2), paint)
                paint.style = Paint.Style.STROKE
                return
            }
            val first = points[0] as? Map<*, *> ?: return
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

        private fun isStrokeNear(stroke: Map<*, *>, x: Float, y: Float, radius: Float = 0.035f): Boolean {
            val points = stroke["points"] as? List<*> ?: return false
            for (raw in points) {
                val p = raw as? Map<*, *> ?: continue
                val px = number(p["x"])
                val py = number(p["y"])
                val dx = px - x
                val dy = py - y
                if (dx*dx + dy*dy <= radius*radius) return true
            }
            return false
        }

        private fun eraseNear(x: Float, y: Float) {
            val toRemove = strokes.filter { isStrokeNear(it, x, y) }
            if (toRemove.isNotEmpty()) {
                strokes.removeAll(toRemove)
                invalidate()
                // Notify Dart to broadcast erase to helper
                AssistMeNativeBridge.channel?.invokeMethod("erase", mapOf("x" to x, "y" to y))
            }
        }

        override fun onTouchEvent(event: MotionEvent): Boolean {
            if (!drawingEnabled) return false
            val x = (event.x / width.coerceAtLeast(1)).coerceIn(0f, 1f)
            val y = (event.y / height.coerceAtLeast(1)).coerceIn(0f, 1f)
            // Eraser mode – remove strokes near touch, no drawing preview
            if (selectedTool == "eraser") {
                when (event.actionMasked) {
                    MotionEvent.ACTION_DOWN, MotionEvent.ACTION_MOVE -> {
                        eraseNear(x, y)
                    }
                }
                return true
            }
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    activePoints.clear()
                    activePoints.add(PointF(x, y))
                    invalidate()
                }
                MotionEvent.ACTION_MOVE -> {
                    activePoints.add(PointF(x, y))
                    invalidate()
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    activePoints.add(PointF(x, y))
                    if (activePoints.isNotEmpty()) {
                        // Handle single-tap dot by ensuring at least 2 points if needed
                        val points = if (activePoints.size == 1) {
                            // duplicate point with tiny offset for visibility
                            listOf(activePoints.first(), PointF((x+0.001f).coerceIn(0f,1f), y))
                        } else activePoints.toList()
                        val mapped = points.map { mapOf<String, Any>("x" to it.x, "y" to it.y) }
                        val stroke = mapOf<String, Any>(
                            "points" to mapped,
                            "color" to selectedColor,
                            "width" to selectedWidth,
                        )
                        strokes.add(stroke)
                        AssistMeNativeBridge.channel?.invokeMethod(
                            "drawStroke",
                            mapOf("points" to mapped, "color" to selectedColor, "width" to selectedWidth),
                        )
                    }
                    activePoints.clear()
                    invalidate()
                }
            }
            return true
        }

        private fun number(value: Any?): Float = (value as? Number)?.toFloat() ?: 0f
    }
}
