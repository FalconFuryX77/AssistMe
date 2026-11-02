package com.assistme.clicky

import android.accessibilityservice.AccessibilityService
import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.ValueAnimator
import android.content.Context
import android.content.Intent
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.drawable.GradientDrawable
import android.media.AudioAttributes
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.text.TextUtils
import android.util.Log
import android.util.TypedValue
import android.view.ContextThemeWrapper
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityManager
import android.view.accessibility.AccessibilityNodeInfo
import android.view.animation.AccelerateDecelerateInterpolator
import android.widget.LinearLayout
import android.widget.TextView
import java.util.Locale

/** One saved guide step as received from Flutter. */
data class ClickyGuideStepInput(val title: String, val instruction: String)

/**
 * Clicky for Android: walks the user through a saved AssistMe guide on top of
 * any app. A floating card shows and speaks the current step, and a blue
 * pointer flies to the control the step refers to.
 *
 * Design rules:
 *  - Guidance only. Clicky never taps for the user.
 *  - On-device only. It reads the accessibility tree (labels and bounds); no
 *    screenshots are taken and nothing is sent off the phone.
 *  - Uses TYPE_ACCESSIBILITY_OVERLAY windows owned by the accessibility
 *    service, so no extra overlay permission is needed and Android 12+
 *    "untrusted touch" blocking never stops the user's taps passing through.
 *  - Never reads password fields and hides itself on sensitive screens.
 *
 * All methods must be called on the main thread.
 */
class ClickyGuideController(
    private val service: AccessibilityService,
    private val isSensitiveScreen: () -> Boolean,
) {
    private class Step(
        val title: String,
        val instruction: String,
        val phrases: List<ClickyTargetPhrase>,
        val area: ClickyAreaHint?,
    )

    private class Candidate(
        val label: String,
        val highlight: Rect,
        val clickable: Boolean,
        val weak: Boolean,
    )

    /** Which app screen the user is on, so Back can return to a step's screen. */
    private data class ScreenSignature(val packageName: String, val className: String?, val title: String?)

    companion object {
        private const val TAG = "AssistMeClicky"
        private const val MAX_STEPS = 100
        private const val MAX_TITLE_CHARACTERS = 120
        private const val MAX_INSTRUCTION_CHARACTERS = 600
        private const val MAX_NODES_PER_SCAN = 1500
        private const val HEARTBEAT_MS = 1200L
        private const val AUTO_ADVANCE_DELAY_MS = 900L
        private const val AUTO_CLOSE_DELAY_MS = 8000L
        private const val MAX_HIGHLIGHT_SCREEN_FRACTION = 0.35

        // A new target must be seen on two scans this far apart before the
        // pointer flies to it, so half-drawn screens do not make it jump.
        private const val CONFIRM_TARGET_DELAY_MS = 250L
        // Scans in a row without the target before the pointer is hidden.
        private const val MISSES_BEFORE_CLEAR = 2
        // Scans in a row without the target before Clicky checks whether the
        // user is already on the next step.
        private const val MISSES_BEFORE_LOOKAHEAD = 3
        private const val LOOKAHEAD_MIN_SCORE = 80
        private const val RECENT_CLICK_MS = 6000L
        private const val RETURN_STEP_DELAY_MS = 700L
        private const val RETURN_MAX_BACK_PRESSES = 4
        private const val GOOGLE_TTS_ENGINE = "com.google.android.tts"
        private val CLICKY_BLUE = Color.rgb(61, 139, 255)
        private val CLICKY_BLUE_LIGHT = Color.rgb(147, 197, 253)
    }

    private val handler = Handler(Looper.getMainLooper())
    private val windowManager = service.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val ownPackage: String = service.packageName
    private val themedContext = ContextThemeWrapper(service, android.R.style.Theme_DeviceDefault)

    private var steps: List<Step> = emptyList()
    private var guideTitle = ""
    private var stepIndex = 0
    private var phraseIndex = 0
    private var targetPhraseIndex = -1
    private var targetRect: Rect? = null
    private var targetLabel: String? = null
    private var pendingLabel: String? = null
    private var pendingRect: Rect? = null
    private var missCount = 0
    private var areaShown = false
    private var areaDone = false
    private var finished = false

    // Where the user did each step, so Back can take them there again.
    private val stepScreens = HashMap<Int, ScreenSignature>()
    private var currentScreen: ScreenSignature? = null
    private val recentClicks = ArrayDeque<Pair<Long, String>>()
    private var returnStep = -1
    private var returnAttempts = 0
    private val returnRunnable = Runnable { continueReturn() }

    var isActive = false
        private set

    private var pointerView: PointerView? = null
    private var bubbleView: LinearLayout? = null
    private var bubbleAtTop = false
    private var bubbleWidth = 0
    private var stepCounterText: TextView? = null
    private var titleText: TextView? = null
    private var instructionText: TextView? = null
    private var statusText: TextView? = null
    private var backButton: TextView? = null
    private var nextButton: TextView? = null
    private var muteButton: TextView? = null

    private var tts: TextToSpeech? = null
    private var ttsReady = false
    private var muted = false
    private var pendingSpeech: String? = null
    private var sessionGeneration = 0

    private var refreshPending = false
    private val refreshRunnable = Runnable {
        refreshPending = false
        refresh()
    }
    private val heartbeatRunnable = object : Runnable {
        override fun run() {
            if (!isActive) return
            refresh()
            handler.postDelayed(this, HEARTBEAT_MS)
        }
    }
    private val advanceRunnable = Runnable { goToStep(stepIndex + 1, automatic = true) }
    private val autoCloseRunnable = Runnable { stop() }

    // ------------------------------------------------------------------
    // Lifecycle
    // ------------------------------------------------------------------

    fun start(title: String, rawSteps: List<ClickyGuideStepInput>, startIndex: Int): Boolean {
        stop()
        val parsed = rawSteps.asSequence()
            .map {
                ClickyGuideStepInput(
                    it.title.trim().take(MAX_TITLE_CHARACTERS),
                    it.instruction.trim().take(MAX_INSTRUCTION_CHARACTERS),
                )
            }
            .filter { it.title.isNotEmpty() || it.instruction.isNotEmpty() }
            .take(MAX_STEPS)
            .map {
                Step(
                    it.title,
                    it.instruction,
                    ClickyTargetMatcher.extractPhrases(it.title, it.instruction),
                    ClickyTargetMatcher.extractArea(it.title, it.instruction),
                )
            }
            .toList()
        if (parsed.isEmpty()) return false

        steps = parsed
        stepScreens.clear()
        recentClicks.clear()
        currentScreen = null
        guideTitle = title.trim().take(MAX_TITLE_CHARACTERS)
        sessionGeneration++
        muted = isScreenReaderRunning()
        try {
            addViews()
        } catch (error: RuntimeException) {
            Log.w(TAG, "Could not show the Clicky overlay.", error)
            removeViews()
            steps = emptyList()
            return false
        }
        isActive = true
        initTextToSpeech(sessionGeneration)
        goToStep(startIndex.coerceIn(0, parsed.size - 1))
        handler.postDelayed(heartbeatRunnable, HEARTBEAT_MS)
        return true
    }

    fun stop() {
        isActive = false
        handler.removeCallbacksAndMessages(null)
        refreshPending = false
        pointerView?.cancelAnimations()
        removeViews()
        tts?.let { engine ->
            try {
                engine.stop()
                engine.shutdown()
            } catch (_: Exception) {
            }
        }
        tts = null
        ttsReady = false
        pendingSpeech = null
        steps = emptyList()
        targetRect = null
        targetLabel = null
        pendingLabel = null
        pendingRect = null
        targetPhraseIndex = -1
        missCount = 0
        areaShown = false
        areaDone = false
        finished = false
        stepScreens.clear()
        recentClicks.clear()
        returnStep = -1
    }

    /** Stops partway through and brings the user back to the AssistMe guide they started from. */
    private fun stopAndReturnToApp() {
        val midGuide = !finished
        stop()
        if (!midGuide) return
        try {
            service.packageManager.getLaunchIntentForPackage(ownPackage)?.let { intent ->
                // An existing task comes to the front as it was, on the guide screen.
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                service.startActivity(intent)
            }
        } catch (error: RuntimeException) {
            Log.w(TAG, "Could not return to AssistMe.", error)
        }
    }

    fun onAccessibilityEvent(event: AccessibilityEvent) {
        if (!isActive) return
        // Our own card and pointer also emit events; reacting to them would loop.
        val eventPackage = event.packageName?.toString() ?: return
        if (eventPackage == ownPackage) return
        when (event.eventType) {
            AccessibilityEvent.TYPE_VIEW_CLICKED -> {
                handleClick(event)
                scheduleRefresh(400L)
            }
            AccessibilityEvent.TYPE_VIEW_LONG_CLICKED -> {
                rememberClick(event)
                completeArea()
                scheduleRefresh(400L)
            }
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> {
                val screen = ScreenSignature(
                    eventPackage,
                    event.className?.toString(),
                    event.text?.joinToString(" ")?.trim()?.takeIf { it.isNotEmpty() },
                )
                val changed = screen != currentScreen
                currentScreen = screen
                // A press-and-hold or a swipe usually opens a new screen or menu.
                if (changed && areaShown) completeArea()
                scheduleRefresh(200L)
            }
            AccessibilityEvent.TYPE_VIEW_SCROLLED -> {
                if (areaShown && steps.getOrNull(stepIndex)?.area?.isSwipe == true) completeArea()
                scheduleRefresh(150L)
            }
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED -> scheduleRefresh(300L)
        }
    }

    // ------------------------------------------------------------------
    // Step flow
    // ------------------------------------------------------------------

    /**
     * Shows step [index]. [automatic] is true when Clicky moved on by itself
     * after the user did the previous step.
     */
    private fun goToStep(index: Int, automatic: Boolean = false) {
        if (!isActive) return
        handler.removeCallbacks(advanceRunnable)
        handler.removeCallbacks(autoCloseRunnable)
        if (index >= steps.size) {
            finish()
            return
        }
        stepIndex = index.coerceAtLeast(0)
        phraseIndex = 0
        clearTarget()
        missCount = 0
        areaDone = false
        finished = false

        val step = steps[stepIndex]
        stepCounterText?.text = "Step ${stepIndex + 1} of ${steps.size}"
        titleText?.apply {
            text = step.title.ifEmpty { guideTitle }
            visibility = if (text.isNullOrEmpty()) View.GONE else View.VISIBLE
        }
        instructionText?.apply {
            text = step.instruction
            visibility = if (step.instruction.isEmpty()) View.GONE else View.VISIBLE
        }
        setButtonEnabled(backButton, stepIndex > 0)
        nextButton?.text = if (stepIndex == steps.size - 1) "Finish ✓" else "Next ▶"
        setStatus(
            when {
                step.phrases.isNotEmpty() -> "Looking for “${step.phrases[0].display}”…"
                step.area != null -> step.area.prompt
                else -> "Do this step, then tap Next."
            },
        )
        speak("Step ${stepIndex + 1}. ${step.instruction.ifEmpty { step.title }}")
        // A guide may repeat the button the user just pressed ("tap Done" after
        // a "tap Next" that turned out to be Done). Do not wait for it again.
        if (automatic && step.phrases.isNotEmpty() && step.area == null &&
            step.phrases.all { phrase -> recentClickLabels().any { ClickyTargetMatcher.labelMatches(phrase, it) } }
        ) {
            setStatus("Already done ✓")
            handler.postDelayed(advanceRunnable, AUTO_ADVANCE_DELAY_MS)
            return
        }
        scheduleRefresh(150L)
    }

    private fun finish() {
        finished = true
        clearTarget()
        stepCounterText?.text = "Done"
        titleText?.apply {
            text = "All done! 🎉"
            visibility = View.VISIBLE
        }
        instructionText?.apply {
            text = if (guideTitle.isEmpty()) "You finished the guide." else "You finished “$guideTitle”."
            visibility = View.VISIBLE
        }
        setStatus("Clicky will close by itself in a few seconds.")
        setButtonEnabled(backButton, steps.isNotEmpty())
        nextButton?.text = "Close"
        speak("All done. You finished the guide.")
        handler.postDelayed(autoCloseRunnable, AUTO_CLOSE_DELAY_MS)
    }

    private fun onNextPressed() {
        if (!isActive) return
        if (finished) stop() else goToStep(stepIndex + 1)
    }

    private fun onBackPressed() {
        if (!isActive) return
        val previous = when {
            finished -> steps.size - 1
            stepIndex > 0 -> stepIndex - 1
            else -> return
        }
        goToStep(previous)
        startReturn(previous)
    }

    private fun handleClick(event: AccessibilityEvent) {
        val labels = rememberClick(event)
        if (finished) return
        val step = steps.getOrNull(stepIndex) ?: return
        val phrase = step.phrases.getOrNull(targetPhraseIndex) ?: return
        val target = targetRect ?: return

        val source = event.source
        val clickedBounds = Rect()
        source?.getBoundsInScreen(clickedBounds)
        val screen = screenBounds()
        val maxArea = screen.width().toLong() * screen.height() * MAX_HIGHLIGHT_SCREEN_FRACTION
        val boundsHit = !clickedBounds.isEmpty &&
            area(clickedBounds) <= maxArea &&
            (clickedBounds.contains(target.centerX(), target.centerY()) ||
                target.contains(clickedBounds.centerX(), clickedBounds.centerY()))
        val labelHit = labels.any { ClickyTargetMatcher.labelMatches(phrase, it) }
        if (!boundsHit && !labelHit) return

        phraseIndex = targetPhraseIndex + 1
        clearTarget()
        completePhraseOrStep(step)
    }

    private fun completePhraseOrStep(step: Step) {
        if (phraseIndex >= step.phrases.size) {
            setStatus("Nice! ✓")
            handler.removeCallbacks(advanceRunnable)
            handler.postDelayed(advanceRunnable, AUTO_ADVANCE_DELAY_MS)
        } else {
            setStatus("Nice! Next: “${step.phrases[phraseIndex].display}”")
        }
    }

    /** Records what the user just pressed and returns its labels. */
    private fun rememberClick(event: AccessibilityEvent): List<String> {
        val source = event.source
        val labels = ArrayList<String>()
        event.text?.forEach { text -> text?.toString()?.let(labels::add) }
        event.contentDescription?.toString()?.let(labels::add)
        if (source?.isPassword != true) source?.text?.toString()?.let(labels::add)
        source?.contentDescription?.toString()?.let(labels::add)
        val now = System.currentTimeMillis()
        labels.filter { it.isNotBlank() }.forEach { recentClicks.addLast(now to it) }
        while (recentClicks.size > 20) recentClicks.removeFirst()
        return labels
    }

    private fun recentClickLabels(): List<String> {
        val cutoff = System.currentTimeMillis() - RECENT_CLICK_MS
        return recentClicks.filter { it.first >= cutoff }.map { it.second }
    }

    /** The user did the press-and-hold or swipe this step asked for. */
    private fun completeArea() {
        if (!areaShown || finished) return
        val step = steps.getOrNull(stepIndex) ?: return
        areaDone = true
        clearTarget()
        completePhraseOrStep(step)
        if (phraseIndex < step.phrases.size) scheduleRefresh(300L)
    }

    // ------------------------------------------------------------------
    // Going back to an earlier step's screen
    // ------------------------------------------------------------------

    /**
     * Back on the card means "show me that step again", so Clicky also takes
     * the phone back to the screen where that step is done, pressing the
     * system Back key (or Home) until it gets there.
     */
    private fun startReturn(index: Int) {
        handler.removeCallbacks(returnRunnable)
        returnStep = index
        returnAttempts = 0
        if (stepScreens[index] == null && steps.getOrNull(index)?.phrases.isNullOrEmpty()) {
            returnStep = -1
            return
        }
        handler.postDelayed(returnRunnable, 150L)
    }

    private fun continueReturn() {
        val index = returnStep
        if (!isActive || index < 0 || index != stepIndex) return
        if (isAtStepScreen(index)) {
            returnStep = -1
            scheduleRefresh(100L)
            return
        }
        val wanted = stepScreens[index]
        if (returnAttempts >= RETURN_MAX_BACK_PRESSES) {
            returnStep = -1
            // Back presses did not get there: reopen that app from its start.
            val app = wanted?.packageName
            if (app != null && app != currentScreen?.packageName && app != ownPackage) {
                try {
                    service.packageManager.getLaunchIntentForPackage(app)?.let { intent ->
                        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        service.startActivity(intent)
                    }
                } catch (error: RuntimeException) {
                    Log.w(TAG, "Could not reopen $app.", error)
                }
            }
            scheduleRefresh(RETURN_STEP_DELAY_MS)
            return
        }
        returnAttempts++
        setStatus("Taking you back to this step…")
        val action = if (wanted != null && wanted.packageName == homePackage()) {
            AccessibilityService.GLOBAL_ACTION_HOME
        } else {
            AccessibilityService.GLOBAL_ACTION_BACK
        }
        service.performGlobalAction(action)
        handler.postDelayed(returnRunnable, RETURN_STEP_DELAY_MS)
    }

    /** True when the screen shows that step's control, or is the screen it was done on. */
    private fun isAtStepScreen(index: Int): Boolean {
        val root = activeRoot() ?: return false
        if (root.packageName?.toString() == ownPackage) return false
        val step = steps.getOrNull(index) ?: return true
        if (step.phrases.isNotEmpty()) {
            val elements = collectCandidates(root).map { ClickyScreenElement(it.label, it.clickable, it.weak) }
            if (ClickyTargetMatcher.findBestMatch(step.phrases, 0, elements) != null) return true
        }
        val wanted = stepScreens[index] ?: return step.phrases.isEmpty()
        val here = currentScreen ?: return false
        if (wanted.packageName != here.packageName) return false
        return when {
            wanted.title != null && here.title != null -> wanted.title == here.title
            wanted.className != null && here.className != null -> wanted.className == here.className
            else -> true
        }
    }

    private fun homePackage(): String? = try {
        val home = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
        service.packageManager.resolveActivity(home, 0)?.activityInfo?.packageName
    } catch (_: RuntimeException) {
        null
    }

    private fun activeRoot(): AccessibilityNodeInfo? = try {
        service.rootInActiveWindow
    } catch (_: RuntimeException) {
        null
    }

    // ------------------------------------------------------------------
    // Finding the target on screen
    // ------------------------------------------------------------------

    private fun scheduleRefresh(delayMs: Long) {
        if (!isActive || refreshPending) return
        refreshPending = true
        handler.postDelayed(refreshRunnable, delayMs)
    }

    private fun refresh() {
        if (!isActive) return
        updateBubbleLayout(wantTop = bubbleAtTop) // Keeps the card width right after rotation.
        if (finished) return
        val step = steps.getOrNull(stepIndex) ?: return
        val phrasesLeft = phraseIndex < step.phrases.size
        val areaLeft = step.area != null && !areaDone
        if (!phrasesLeft && !areaLeft) {
            clearTarget()
            return
        }
        if (isSensitiveScreen()) {
            clearTarget()
            setStatus("Clicky looks away on private screens like passwords or banking.")
            return
        }
        val root = activeRoot() ?: run {
            clearTarget()
            return
        }
        val rootPackage = root.packageName?.toString()
        if (rootPackage == ownPackage) {
            clearTarget()
            setStatus("Open the screen this step is about. I'll point when I see it.")
            return
        }

        val candidates = collectCandidates(root)
        val elements = candidates.map { ClickyScreenElement(it.label, it.clickable, it.weak) }
        val match = if (phrasesLeft) {
            ClickyTargetMatcher.findBestMatch(step.phrases, phraseIndex, elements)
        } else {
            null
        }
        if (match == null) {
            missCount++
            if (lookAheadToNextStep(elements)) return
            if (areaLeft && phraseIndex == 0) {
                showArea(step, rootPackage)
                return
            }
            // One empty scan is often a screen mid-animation: keep pointing.
            if (missCount >= MISSES_BEFORE_CLEAR) {
                clearTarget()
                if (phrasesLeft) {
                    setStatus(
                        "Looking for “${step.phrases[phraseIndex].display}”… " +
                            "If you don't see it, try scrolling or going back.",
                    )
                }
            }
            return
        }
        missCount = 0

        // Keep pointing at the same control while it is still there, even if
        // another label scores the same, so the pointer does not hop around.
        var candidate = candidates[match.elementIndex]
        val current = targetRect
        if (current != null && targetPhraseIndex == match.phraseIndex) {
            candidates.firstOrNull { it.label == targetLabel && near(it.highlight, current, dp(64f)) }
                ?.let { candidate = it }
        }
        val sameTarget = current != null && candidate.label == targetLabel
        if (!sameTarget) {
            // A new target must look the same on two scans before the pointer moves.
            val pending = pendingRect
            if (pendingLabel != candidate.label || pending == null || !near(pending, candidate.highlight, dp(24f))) {
                pendingLabel = candidate.label
                pendingRect = Rect(candidate.highlight)
                handler.removeCallbacks(refreshRunnable)
                refreshPending = false
                scheduleRefresh(CONFIRM_TARGET_DELAY_MS)
                return
            }
        }
        pendingLabel = null
        pendingRect = null

        phraseIndex = match.phraseIndex
        targetPhraseIndex = match.phraseIndex
        targetLabel = candidate.label
        targetRect = Rect(candidate.highlight)
        areaShown = false
        if (rootPackage != null && stepScreens[stepIndex] == null) {
            stepScreens[stepIndex] = currentScreen?.takeIf { it.packageName == rootPackage }
                ?: ScreenSignature(rootPackage, null, null)
        }
        setStatus("Tap “${step.phrases[match.phraseIndex].display}” 👆")
        placeBubbleAwayFrom(candidate.highlight)
        pointerView?.pointAt(candidate.highlight, glide = sameTarget)
    }

    /** Highlights the whole screen for a press-and-hold or swipe step. */
    private fun showArea(step: Step, rootPackage: String?) {
        val hint = step.area ?: return
        if (rootPackage != null && stepScreens[stepIndex] == null) {
            stepScreens[stepIndex] = currentScreen?.takeIf { it.packageName == rootPackage }
                ?: ScreenSignature(rootPackage, null, null)
        }
        setStatus("${hint.prompt} 👆")
        if (areaShown) return
        val screen = screenBounds()
        val areaRect = Rect(
            screen.left + dp(20f),
            screen.top + dp(56f),
            screen.right - dp(20f),
            screen.bottom - dp(56f),
        )
        targetRect = null
        targetLabel = null
        targetPhraseIndex = -1
        areaShown = true
        pointerView?.pointAt(areaRect, glide = false)
    }

    /**
     * The user may already be past this step: the guide's wording did not
     * match this phone, or they did it their own way. If the next step's
     * control is clearly on screen, move on instead of waiting.
     */
    private fun lookAheadToNextStep(elements: List<ClickyScreenElement>): Boolean {
        if (missCount < MISSES_BEFORE_LOOKAHEAD || returnStep >= 0) return false
        val next = steps.getOrNull(stepIndex + 1) ?: return false
        if (next.phrases.isEmpty()) return false
        val match = ClickyTargetMatcher.findBestMatch(next.phrases, 0, elements) ?: return false
        if (match.score < LOOKAHEAD_MIN_SCORE) return false
        Log.i(TAG, "Step ${stepIndex + 1} target not found; step ${stepIndex + 2} is on screen, moving on.")
        goToStep(stepIndex + 1, automatic = true)
        setStatus("Looks like you're already here. On to the next step.")
        return true
    }

    private fun near(a: Rect, b: Rect, distance: Int): Boolean =
        Math.abs(a.centerX() - b.centerX()) <= distance && Math.abs(a.centerY() - b.centerY()) <= distance

    private fun collectCandidates(root: AccessibilityNodeInfo): List<Candidate> {
        val screen = screenBounds()
        val maxHighlightArea = screen.width().toLong() * screen.height() * MAX_HIGHLIGHT_SCREEN_FRACTION
        val result = ArrayList<Candidate>()
        val stack = ArrayDeque<Pair<AccessibilityNodeInfo, Rect?>>()
        stack.addLast(root to null)
        var visited = 0
        while (stack.isNotEmpty() && visited < MAX_NODES_PER_SCAN) {
            val (node, inheritedClickable) = stack.removeLast()
            visited++
            try {
                if (!node.isVisibleToUser) continue
                val bounds = Rect()
                node.getBoundsInScreen(bounds)
                val clickableBounds =
                    if (node.isClickable && !bounds.isEmpty && area(bounds) <= maxHighlightArea) Rect(bounds)
                    else inheritedClickable
                if (!node.isPassword && !bounds.isEmpty && Rect.intersects(bounds, screen)) {
                    val label = (node.text ?: node.contentDescription ?: node.hintText)?.toString()?.trim()
                    if (!label.isNullOrEmpty()) {
                        result += Candidate(label, clickableBounds ?: bounds, clickableBounds != null, weak = false)
                    } else if (node.isClickable && clickableBounds != null) {
                        // Icon buttons often have no text, only an id like "wallpaper_button".
                        viewIdLabel(node.viewIdResourceName)?.let { idLabel ->
                            result += Candidate(idLabel, clickableBounds, clickable = true, weak = true)
                        }
                    }
                }
                // Push children in reverse so they are visited in on-screen order.
                for (childIndex in node.childCount - 1 downTo 0) {
                    node.getChild(childIndex)?.let { child -> stack.addLast(child to clickableBounds) }
                }
            } catch (_: RuntimeException) {
                // The window changed while we were reading it; the next refresh retries.
            }
        }
        return result
    }

    /** "com.app:id/set_wallpaper_button" -> "set wallpaper button". */
    private fun viewIdLabel(id: String?): String? {
        val name = id?.substringAfter(":id/", "")?.takeIf { it.isNotEmpty() } ?: return null
        return name.replace('_', ' ').replace(Regex("([a-z])([A-Z])"), "$1 $2").trim().takeIf { it.length >= 3 }
    }

    private fun clearTarget() {
        targetRect = null
        targetLabel = null
        pendingLabel = null
        pendingRect = null
        targetPhraseIndex = -1
        areaShown = false
        pointerView?.hideTarget()
    }

    // ------------------------------------------------------------------
    // Speech
    // ------------------------------------------------------------------

    private fun isScreenReaderRunning(): Boolean {
        val manager = service.getSystemService(Context.ACCESSIBILITY_SERVICE) as? AccessibilityManager
        return manager?.isTouchExplorationEnabled == true
    }

    /**
     * Starts a speech engine: the phone's default first, then the others. Some
     * phones' default engine refuses third-party apps (Samsung's prints
     * "not allowed to bind to private engine" and fails with status -1),
     * which left Clicky silent although Google's engine was installed.
     */
    private fun initTextToSpeech(generation: Int, enginePackage: String? = null, tried: Set<String> = emptySet()) {
        val attempted = tried + (enginePackage ?: "default")
        try {
            val listener = TextToSpeech.OnInitListener { status ->
                handler.post {
                    if (!isActive || generation != sessionGeneration) return@post
                    if (status == TextToSpeech.SUCCESS) {
                        Log.i(TAG, "Text-to-speech ready (engine ${tts?.defaultEngine.takeIf { enginePackage == null } ?: enginePackage}).")
                        configureVoice()
                        ttsReady = true
                        pendingSpeech?.let(::speakNow)
                        pendingSpeech = null
                        return@post
                    }
                    val failed = tts
                    val defaultEngine = try {
                        failed?.defaultEngine
                    } catch (_: RuntimeException) {
                        null
                    }
                    val installed = try {
                        failed?.engines?.map { it.name }.orEmpty()
                    } catch (_: RuntimeException) {
                        emptyList()
                    }
                    try {
                        failed?.shutdown()
                    } catch (_: RuntimeException) {
                    }
                    tts = null
                    // Google's engine first (it accepts every app), then the rest.
                    val candidates = if (installed.isEmpty()) {
                        listOf(GOOGLE_TTS_ENGINE)
                    } else {
                        installed.sortedBy { if (it == GOOGLE_TTS_ENGINE) 0 else 1 }
                    }
                    val next = candidates.firstOrNull { it !in attempted && it != defaultEngine }
                    if (next != null) {
                        Log.w(TAG, "Text-to-speech engine ${enginePackage ?: defaultEngine} failed (status $status); trying $next.")
                        initTextToSpeech(generation, next, attempted + listOfNotNull(defaultEngine))
                    } else {
                        Log.w(TAG, "No text-to-speech engine would start (status $status); Clicky will stay silent.")
                        pendingSpeech = null
                    }
                }
            }
            tts = if (enginePackage == null) {
                TextToSpeech(service.applicationContext, listener)
            } else {
                TextToSpeech(service.applicationContext, listener, enginePackage)
            }
        } catch (error: RuntimeException) {
            Log.w(TAG, "Text-to-speech is unavailable; Clicky will stay silent.", error)
            tts = null
        }
    }

    private fun speak(text: String) {
        if (muted || !isActive || text.isBlank()) return
        if (ttsReady) speakNow(text) else pendingSpeech = text
    }

    /**
     * Speaks on the accessibility stream, not the media stream: media volume
     * is often turned down, and after a help call the media stream can stay
     * routed to the earpiece, which made Clicky sound silent.
     */
    private fun configureVoice() {
        val engine = tts ?: return
        try {
            engine.setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANCE_ACCESSIBILITY)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build(),
            )
            // A voice missing for the phone's language makes speak() silently
            // do nothing; fall back to English, which every engine ships.
            val language = engine.setLanguage(Locale.getDefault())
            if (language == TextToSpeech.LANG_MISSING_DATA || language == TextToSpeech.LANG_NOT_SUPPORTED) {
                Log.w(TAG, "No ${Locale.getDefault()} voice installed (result $language); using English.")
                engine.setLanguage(Locale.US)
            }
        } catch (error: RuntimeException) {
            Log.w(TAG, "Could not configure the Clicky voice.", error)
        }
    }

    private fun speakNow(text: String) {
        if (muted) return
        try {
            val result = tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "clicky-step")
            if (result != TextToSpeech.SUCCESS) Log.w(TAG, "Text-to-speech refused to speak (result $result).")
        } catch (error: RuntimeException) {
            Log.w(TAG, "Text-to-speech failed.", error)
        }
    }

    private fun toggleMute() {
        muted = !muted
        if (muted) {
            pendingSpeech = null
            try {
                tts?.stop()
            } catch (_: RuntimeException) {
            }
        }
        updateMuteButton()
    }

    private fun updateMuteButton() {
        muteButton?.text = if (muted) "🔇" else "🔊"
        muteButton?.contentDescription = if (muted) "Turn Clicky voice on" else "Mute Clicky voice"
    }

    // ------------------------------------------------------------------
    // Overlay windows
    // ------------------------------------------------------------------

    private fun addViews() {
        val pointer = PointerView(themedContext)
        windowManager.addView(pointer, pointerLayoutParams())
        pointerView = pointer

        val bubble = buildBubble()
        bubbleAtTop = false
        bubbleWidth = computeBubbleWidth()
        windowManager.addView(bubble, bubbleLayoutParams(bubbleAtTop, bubbleWidth))
        bubbleView = bubble
    }

    private fun removeViews() {
        bubbleView?.let { view ->
            try {
                windowManager.removeView(view)
            } catch (_: RuntimeException) {
            }
        }
        pointerView?.let { view ->
            try {
                windowManager.removeView(view)
            } catch (_: RuntimeException) {
            }
        }
        bubbleView = null
        pointerView = null
        stepCounterText = null
        titleText = null
        instructionText = null
        statusText = null
        backButton = null
        nextButton = null
        muteButton = null
    }

    private fun pointerLayoutParams() = WindowManager.LayoutParams(
        WindowManager.LayoutParams.MATCH_PARENT,
        WindowManager.LayoutParams.MATCH_PARENT,
        WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
            WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or
            WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED,
        PixelFormat.TRANSLUCENT,
    ).apply {
        gravity = Gravity.TOP or Gravity.START
        layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
        title = "Clicky pointer"
    }

    private fun bubbleLayoutParams(atTop: Boolean, width: Int) = WindowManager.LayoutParams(
        width,
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
            WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED,
        PixelFormat.TRANSLUCENT,
    ).apply {
        gravity = (if (atTop) Gravity.TOP else Gravity.BOTTOM) or Gravity.CENTER_HORIZONTAL
        y = if (atTop) dp(36f) else dp(56f)
        title = "Clicky guide"
    }

    private fun computeBubbleWidth(): Int =
        minOf(screenBounds().width() - dp(24f), dp(480f)).coerceAtLeast(dp(200f))

    /**
     * Moves the card to the other end of the screen only when it would cover
     * the target. Flipping on every small move made the card jump up and down.
     */
    private fun placeBubbleAwayFrom(target: Rect) {
        val height = bubbleView?.height?.takeIf { it > 0 } ?: dp(220f)
        val screen = screenBounds()
        val covered = if (bubbleAtTop) {
            Rect(screen.left, screen.top + dp(36f), screen.right, screen.top + dp(36f) + height)
        } else {
            Rect(screen.left, screen.bottom - dp(56f) - height, screen.right, screen.bottom - dp(56f))
        }
        if (Rect.intersects(covered, target)) updateBubbleLayout(wantTop = !bubbleAtTop)
    }

    private fun updateBubbleLayout(wantTop: Boolean) {
        val view = bubbleView ?: return
        val width = computeBubbleWidth()
        if (wantTop == bubbleAtTop && width == bubbleWidth) return
        bubbleAtTop = wantTop
        bubbleWidth = width
        try {
            windowManager.updateViewLayout(view, bubbleLayoutParams(wantTop, width))
        } catch (_: RuntimeException) {
        }
    }

    private fun buildBubble(): LinearLayout {
        val card = LinearLayout(themedContext).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16f), dp(14f), dp(16f), dp(14f))
            background = rounded(Color.argb(245, 16, 22, 38), 20f, CLICKY_BLUE, 2f)
            elevation = dp(12f).toFloat()
        }

        val header = LinearLayout(themedContext).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        header.addView(TextView(themedContext).apply {
            text = "● Clicky"
            textSize = 15f
            setTextColor(CLICKY_BLUE)
            typeface = android.graphics.Typeface.DEFAULT_BOLD
        })
        stepCounterText = TextView(themedContext).apply {
            textSize = 14f
            setTextColor(Color.rgb(203, 213, 225))
            setPadding(dp(10f), 0, dp(6f), 0)
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        header.addView(stepCounterText)
        muteButton = pillButton("", filled = false).apply {
            layoutParams = LinearLayout.LayoutParams(dp(44f), dp(44f)).apply { marginEnd = dp(8f) }
            setOnClickListener { toggleMute() }
        }
        updateMuteButton()
        header.addView(muteButton)
        header.addView(pillButton("✕", filled = false).apply {
            contentDescription = "Stop Clicky"
            layoutParams = LinearLayout.LayoutParams(dp(44f), dp(44f))
            setOnClickListener { handler.post { stopAndReturnToApp() } }
        })
        card.addView(header)

        titleText = TextView(themedContext).apply {
            textSize = 19f
            setTextColor(Color.WHITE)
            typeface = android.graphics.Typeface.DEFAULT_BOLD
            maxLines = 2
            ellipsize = TextUtils.TruncateAt.END
            setPadding(0, dp(8f), 0, 0)
        }
        card.addView(titleText)
        instructionText = TextView(themedContext).apply {
            textSize = 17f
            setTextColor(Color.rgb(226, 232, 240))
            maxLines = 4
            ellipsize = TextUtils.TruncateAt.END
            setLineSpacing(0f, 1.15f)
            setPadding(0, dp(4f), 0, 0)
        }
        card.addView(instructionText)
        statusText = TextView(themedContext).apply {
            textSize = 15f
            setTextColor(CLICKY_BLUE_LIGHT)
            typeface = android.graphics.Typeface.DEFAULT_BOLD
            maxLines = 3
            ellipsize = TextUtils.TruncateAt.END
            setPadding(0, dp(8f), 0, dp(10f))
        }
        card.addView(statusText)

        val buttons = LinearLayout(themedContext).apply {
            orientation = LinearLayout.HORIZONTAL
        }
        backButton = pillButton("◀ Back", filled = false).apply {
            layoutParams = LinearLayout.LayoutParams(0, dp(52f), 1f).apply { marginEnd = dp(10f) }
            setOnClickListener { onBackPressed() }
        }
        nextButton = pillButton("Next ▶", filled = true).apply {
            layoutParams = LinearLayout.LayoutParams(0, dp(52f), 1.4f)
            setOnClickListener { onNextPressed() }
        }
        buttons.addView(backButton)
        buttons.addView(nextButton)
        card.addView(buttons)
        return card
    }

    private fun pillButton(label: String, filled: Boolean) = TextView(themedContext).apply {
        text = label
        textSize = 16f
        gravity = Gravity.CENTER
        typeface = android.graphics.Typeface.DEFAULT_BOLD
        setTextColor(Color.WHITE)
        isClickable = true
        isFocusable = true
        background = if (filled) rounded(CLICKY_BLUE, 14f) else rounded(Color.argb(40, 255, 255, 255), 14f)
    }

    private fun setButtonEnabled(button: TextView?, enabled: Boolean) {
        button ?: return
        button.isEnabled = enabled
        button.alpha = if (enabled) 1f else 0.4f
    }

    private fun setStatus(message: String) {
        val view = statusText ?: return
        if (view.text?.toString() != message) view.text = message
    }

    private fun rounded(fill: Int, radiusDp: Float, stroke: Int = Color.TRANSPARENT, strokeDp: Float = 0f) =
        GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = dp(radiusDp).toFloat()
            setColor(fill)
            if (strokeDp > 0f) setStroke(dp(strokeDp), stroke)
        }

    private fun screenBounds(): Rect = Rect(windowManager.currentWindowMetrics.bounds)

    private fun area(rect: Rect): Long = rect.width().toLong() * rect.height().toLong()

    private fun dp(value: Float): Int =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value, service.resources.displayMetrics).toInt()

    // ------------------------------------------------------------------
    // Pointer drawing
    // ------------------------------------------------------------------

    /** Full-screen, untouchable layer that draws the blue Clicky cursor and target ring. */
    private inner class PointerView(context: Context) : View(context) {
        private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = dp(3.5f).toFloat()
            color = CLICKY_BLUE
        }
        private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.FILL
            color = CLICKY_BLUE
        }
        private val cursorFill = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.FILL
            color = CLICKY_BLUE
            setShadowLayer(dp(4f).toFloat(), 0f, dp(2f).toFloat(), Color.argb(110, 0, 0, 0))
        }
        private val cursorStroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = dp(2f).toFloat()
            strokeJoin = Paint.Join.ROUND
            color = Color.WHITE
        }
        private val cursorPath = Path().apply {
            moveTo(0f, 0f)
            lineTo(dp(26f).toFloat(), dp(11f).toFloat())
            lineTo(dp(11f).toFloat(), dp(26f).toFloat())
            close()
        }
        private val ringRect = RectF()
        private val windowLocation = IntArray(2)

        private var target: RectF? = null
        private var cursorX = -1f
        private var cursorY = -1f
        private var arrived = false
        private var pulse = 0f
        private var flight: ValueAnimator? = null
        private var pulseAnimator: ValueAnimator? = null

        /**
         * Points at [rect]. [glide] means it is the same control as before, moved
         * by scrolling or a relayout: follow it in a straight line instead of
         * flying a new arc, which looked like the pointer bouncing up and down.
         */
        fun pointAt(rect: Rect, glide: Boolean) {
            val newTarget = RectF(rect)
            val endX = newTarget.centerX()
            val endY = newTarget.centerY()
            val previous = target
            target = newTarget
            val alreadyThere = previous != null && cursorX >= 0f &&
                Math.hypot((cursorX - endX).toDouble(), (cursorY - endY).toDouble()) < dp(24f)
            if (alreadyThere) {
                // Small moves follow the target without a new flight.
                if (flight == null) {
                    cursorX = endX
                    cursorY = endY
                }
                invalidate()
                return
            }
            val screen = screenBounds()
            val startX = if (cursorX >= 0f) cursorX else screen.exactCenterX()
            val startY = if (cursorY >= 0f) cursorY else screen.exactCenterY()
            flyTo(startX, startY, endX, endY, arc = !(glide && previous != null && arrived))
        }

        fun hideTarget() {
            target = null
            arrived = false
            cursorX = -1f
            cursorY = -1f
            cancelAnimations()
            invalidate()
        }

        fun cancelAnimations() {
            val runningFlight = flight
            flight = null
            runningFlight?.cancel()
            val runningPulse = pulseAnimator
            pulseAnimator = null
            runningPulse?.cancel()
            pulse = 0f
        }

        private fun flyTo(startX: Float, startY: Float, endX: Float, endY: Float, arc: Boolean) {
            val previousFlight = flight
            flight = null
            previousFlight?.cancel()
            // A glide keeps the ring on the control; only a new flight hides it.
            arrived = !arc && arrived
            if (!ValueAnimator.areAnimatorsEnabled()) {
                cursorX = endX
                cursorY = endY
                arrived = true
                invalidate()
                return
            }
            // Clicky-style arc: a quadratic bezier that bows upward. A glide is straight.
            val controlX = (startX + endX) / 2f
            val controlY = if (arc) minOf(startY, endY) - dp(80f) else (startY + endY) / 2f
            val animator = ValueAnimator.ofFloat(0f, 1f).apply {
                duration = if (arc) 650L else 220L
                interpolator = AccelerateDecelerateInterpolator()
                addUpdateListener { animation ->
                    val t = animation.animatedValue as Float
                    val u = 1f - t
                    cursorX = u * u * startX + 2f * u * t * controlX + t * t * endX
                    cursorY = u * u * startY + 2f * u * t * controlY + t * t * endY
                    invalidate()
                }
            }
            animator.addListener(object : AnimatorListenerAdapter() {
                override fun onAnimationEnd(animation: Animator) {
                    // Ignore the end callback of a flight that was cancelled or replaced.
                    if (animation !== flight || target == null) return
                    flight = null
                    target?.let {
                        cursorX = it.centerX()
                        cursorY = it.centerY()
                    }
                    arrived = true
                    startPulse()
                    invalidate()
                }
            })
            flight = animator
            animator.start()
        }

        private fun startPulse() {
            if (pulseAnimator != null || !ValueAnimator.areAnimatorsEnabled()) return
            pulseAnimator = ValueAnimator.ofFloat(0f, 1f).apply {
                duration = 900L
                repeatCount = ValueAnimator.INFINITE
                repeatMode = ValueAnimator.REVERSE
                addUpdateListener { animation ->
                    pulse = animation.animatedValue as Float
                    invalidate()
                }
                start()
            }
        }

        override fun onDetachedFromWindow() {
            cancelAnimations()
            super.onDetachedFromWindow()
        }

        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            val currentTarget = target ?: return
            if (cursorX < 0f || cursorY < 0f) return
            // Targets are in screen coordinates; convert to this window's space.
            getLocationOnScreen(windowLocation)
            canvas.save()
            canvas.translate(-windowLocation[0].toFloat(), -windowLocation[1].toFloat())
            if (arrived) {
                val grow = dp(6f) + dp(4f) * pulse
                ringRect.set(
                    currentTarget.left - grow,
                    currentTarget.top - grow,
                    currentTarget.right + grow,
                    currentTarget.bottom + grow,
                )
                val radius = dp(14f).toFloat()
                fillPaint.alpha = (35 + 30 * pulse).toInt()
                canvas.drawRoundRect(ringRect, radius, radius, fillPaint)
                ringPaint.alpha = (255 - 90 * pulse).toInt()
                canvas.drawRoundRect(ringRect, radius, radius, ringPaint)
            }
            val bob = if (arrived) dp(4f) * pulse else 0f
            canvas.translate(cursorX + bob, cursorY + bob)
            canvas.drawPath(cursorPath, cursorFill)
            canvas.drawPath(cursorPath, cursorStroke)
            canvas.restore()
        }
    }
}
