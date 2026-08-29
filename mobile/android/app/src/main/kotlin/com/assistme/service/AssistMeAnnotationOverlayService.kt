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

    private fun dp(value: Float): Int = (value * resources.displayMetrics.density).toInt()

    private fun createPillDrawable(
        bgColor: Int,
        cornerRadiusDp: Float = 16f,
        strokeColor: Int = Color.TRANSPARENT,
        strokeWidthDp: Float = 0f
    ): android.graphics.drawable.GradientDrawable {
        val density = resources.displayMetrics.density
        return android.graphics.drawable.GradientDrawable().apply {
            shape = android.graphics.drawable.GradientDrawable.RECTANGLE
            cornerRadius = cornerRadiusDp * density
            setColor(bgColor)
            if (strokeWidthDp > 0f) {
                setStroke((strokeWidthDp * density).toInt(), strokeColor)
            }
        }
    }

    private fun addOverlayViews() {
        canvasView = AnnotationCanvasView(this)
        windowManager.addView(canvasView, canvasLayout())

        // Modern Material 3 floating pill container
        val outer = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(8f), dp(6f), dp(8f), dp(6f))
            background = createPillDrawable(
                bgColor = Color.argb(240, 19, 23, 32),
                cornerRadiusDp = 22f,
                strokeColor = Color.argb(45, 255, 255, 255),
                strokeWidthDp = 1.2f
            )
            elevation = 16f
        }

        // Drag handle – sleek vertical indicator
        val handle = Button(this).apply {
            text = "⋮⋮"
            textSize = 17f
            setTextColor(Color.argb(170, 255, 255, 255))
            setPadding(0, 0, 0, 0)
            minimumWidth = 0
            minWidth = 0
            background = createPillDrawable(Color.argb(30, 255, 255, 255), cornerRadiusDp = 12f)
            layoutParams = LinearLayout.LayoutParams(dp(26f), dp(38f)).apply { setMargins(0, 0, dp(6f), 0) }
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

        // Scrollable middle area for drawing tools
        val scrollView = HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            overScrollMode = View.OVER_SCROLL_NEVER
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        val inner = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }

        // DRAW Mode Toggle Pill
        drawButton = Button(this).apply {
            text = "✏️ Draw"
            textSize = 13f
            typeface = android.graphics.Typeface.DEFAULT_BOLD
            setTextColor(Color.argb(230, 255, 255, 255))
            background = createPillDrawable(Color.argb(50, 255, 255, 255), cornerRadiusDp = 14f)
            setPadding(dp(12f), 0, dp(12f), 0)
            minimumWidth = 0
            minWidth = 0
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(38f)).apply {
                setMargins(0, 0, dp(5f), 0)
            }
            setOnClickListener { setDrawingEnabled(!drawingEnabled) }
        }
        inner.addView(drawButton)

        // Pen tool button
        penButton = Button(this).apply {
            text = "✏️"
            textSize = 15f
            setTextColor(Color.WHITE)
            background = createPillDrawable(Color.argb(45, 255, 255, 255), cornerRadiusDp = 12f)
            setPadding(0, 0, 0, 0)
            minimumWidth = 0
            minWidth = 0
            layoutParams = LinearLayout.LayoutParams(dp(38f), dp(38f)).apply {
                setMargins(0, 0, dp(4f), 0)
            }
            setOnClickListener { setTool("pen") }
            setOnLongClickListener { showColorPicker(); true }
        }

        // High-contrast Eraser tool button
        eraserButton = Button(this).apply {
            text = "🧹"
            textSize = 15f
            setTextColor(Color.rgb(255, 107, 107))
            background = createPillDrawable(Color.argb(45, 255, 255, 255), cornerRadiusDp = 12f)
            setPadding(0, 0, 0, 0)
            minimumWidth = 0
            minWidth = 0
            layoutParams = LinearLayout.LayoutParams(dp(38f), dp(38f)).apply {
                setMargins(0, 0, dp(4f), 0)
            }
            setOnClickListener { setTool("eraser") }
            setOnLongClickListener { showWidthPicker(); true }
        }
        inner.addView(penButton)
        inner.addView(eraserButton)
        updateToolUI()

        // Color badge button
        colorButton = Button(this).apply {
            text = "●"
            textSize = 20f
            setTextColor(selectedColor)
            background = createPillDrawable(
                bgColor = Color.argb(55, 255, 255, 255),
                cornerRadiusDp = 12f,
                strokeColor = Color.argb(120, 255, 255, 255),
                strokeWidthDp = 1.5f
            )
            setPadding(0, 0, 0, 0)
            minimumWidth = 0
            minWidth = 0
            layoutParams = LinearLayout.LayoutParams(dp(38f), dp(38f)).apply {
                setMargins(0, 0, dp(4f), 0)
            }
            setOnClickListener { showColorPicker() }
        }
        inner.addView(colorButton)

        // Undo button
        inner.addView(Button(this).apply {
            text = "↩"
            textSize = 15f
            setTextColor(Color.WHITE)
            background = createPillDrawable(Color.argb(45, 255, 255, 255), cornerRadiusDp = 12f)
            setPadding(0, 0, 0, 0)
            minimumWidth = 0
            minWidth = 0
            layoutParams = LinearLayout.LayoutParams(dp(38f), dp(38f)).apply {
                setMargins(0, 0, dp(4f), 0)
            }
            setOnClickListener {
                AssistMeNativeBridge.channel?.invokeMethod("undo", null)
            }
        })

        // Redo button
        inner.addView(Button(this).apply {
            text = "↪"
            textSize = 15f
            setTextColor(Color.WHITE)
            background = createPillDrawable(Color.argb(45, 255, 255, 255), cornerRadiusDp = 12f)
            setPadding(0, 0, 0, 0)
            minimumWidth = 0
            minWidth = 0
            layoutParams = LinearLayout.LayoutParams(dp(38f), dp(38f)).apply {
                setMargins(0, 0, dp(4f), 0)
            }
            setOnClickListener {
                AssistMeNativeBridge.channel?.invokeMethod("redo", null)
            }
        })

        // Clear button
        inner.addView(Button(this).apply {
            text = "🗑"
            textSize = 15f
            setTextColor(Color.WHITE)
            background = createPillDrawable(Color.argb(45, 255, 255, 255), cornerRadiusDp = 12f)
            setPadding(0, 0, 0, 0)
            minimumWidth = 0
            minWidth = 0
            layoutParams = LinearLayout.LayoutParams(dp(38f), dp(38f)).apply {
                setMargins(0, 0, dp(4f), 0)
            }
            setOnClickListener {
                clearStrokes()
                AssistMeNativeBridge.channel?.invokeMethod("clear", null)
            }
        })

        scrollView.addView(inner)
        outer.addView(scrollView)

        // STOP – prominent high-contrast crimson red pill
        outer.addView(Button(this).apply {
            text = "STOP"
            textSize = 13f
            typeface = android.graphics.Typeface.DEFAULT_BOLD
            setTextColor(Color.WHITE)
            background = createPillDrawable(Color.rgb(255, 59, 48), cornerRadiusDp = 14f)
            setPadding(dp(14f), 0, dp(14f), 0)
            minimumWidth = 0
            minWidth = 0
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(38f)).apply {
                setMargins(dp(6f), 0, 0, 0)
            }
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
        val isPen = selectedTool == "pen"
        val isEraser = selectedTool == "eraser"

        penButton?.alpha = if (isPen) 1f else 0.75f
        eraserButton?.alpha = if (isEraser) 1f else 0.75f

        penButton?.background = if (isPen) {
            createPillDrawable(
                bgColor = Color.argb(80, 52, 199, 89),
                cornerRadiusDp = 12f,
                strokeColor = Color.rgb(52, 199, 89),
                strokeWidthDp = 1.5f
            )
        } else {
            createPillDrawable(Color.argb(45, 255, 255, 255), cornerRadiusDp = 12f)
        }

        eraserButton?.background = if (isEraser) {
            createPillDrawable(
                bgColor = Color.argb(90, 255, 59, 48),
                cornerRadiusDp = 12f,
                strokeColor = Color.rgb(255, 107, 107),
                strokeWidthDp = 1.5f
            )
        } else {
            createPillDrawable(Color.argb(45, 255, 255, 255), cornerRadiusDp = 12f)
        }
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
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
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

        private fun isStrokeNear(stroke: Map<*, *>, x: Float, y: Float, radius: Float = 0.055f): Boolean {
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
