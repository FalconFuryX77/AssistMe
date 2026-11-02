package com.assistme

import android.content.ComponentName
import android.content.Intent
import android.os.Build
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import com.assistme.clicky.ClickyGuideStepInput
import com.assistme.service.AssistMeAccessibilityService
import com.assistme.service.AssistMeAnnotationOverlayService
import com.assistme.service.AssistMeMediaProjectionService

object AssistMeNativeBridge {
    var channel: MethodChannel? = null
}

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        val accessibility = MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "com.assistme/accessibility"
        )
        accessibility.setMethodCallHandler { call, result ->
            when (call.method) {
                "isEnabled" -> result.success(isAccessibilityEnabled())
                "openSettings" -> {
                    startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
                    result.success(null)
                }
                "dispatchInput" -> {
                    val event = call.arguments as? Map<*, *>
                    result.success(
                        if (event == null) false
                        else AssistMeAccessibilityService.instance?.dispatchInput(event) ?: false
                    )
                }
                else -> result.notImplemented()
            }
        }

        val overlay = MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "com.assistme/annotation_overlay"
        )
        AssistMeNativeBridge.channel = overlay
        overlay.setMethodCallHandler { call, result ->
            when (call.method) {
                "isPermissionGranted" -> result.success(Settings.canDrawOverlays(this))
                "requestPermission" -> {
                    startActivity(
                        Intent(
                            Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                            android.net.Uri.parse("package:$packageName")
                        )
                    )
                    result.success(null)
                }
                "start" -> {
                    AssistMeAnnotationOverlayService.start(this)
                    result.success(null)
                }
                "updateStrokes" -> {
                    AssistMeAnnotationOverlayService.instance?.updateStrokes(call.arguments)
                    result.success(null)
                }
                "clear" -> {
                    AssistMeAnnotationOverlayService.instance?.clearStrokes()
                    result.success(null)
                }
                "hideControlsFor" -> {
                    val ms = (call.arguments as? Number)?.toLong() ?: 1500L
                    AssistMeAnnotationOverlayService.instance?.hideControlsFor(ms)
                    result.success(null)
                }
                "stop" -> {
                    AssistMeAnnotationOverlayService.stop(this)
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }

        val mediaProjectionChannel = MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "com.assistme/media_projection"
        )
        mediaProjectionChannel.setMethodCallHandler { call, result ->
            when (call.method) {
                "startForeground" -> {
                    try {
                        val intent = Intent(this, AssistMeMediaProjectionService::class.java)
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                            startForegroundService(intent)
                        } else {
                            startService(intent)
                        }
                        result.success(true)
                    } catch (e: Exception) {
                        result.error("START_FAILED", e.message, null)
                    }
                }
                "stopForeground" -> {
                    try {
                        stopService(Intent(this, AssistMeMediaProjectionService::class.java))
                        result.success(true)
                    } catch (e: Exception) {
                        result.error("STOP_FAILED", e.message, null)
                    }
                }
                else -> result.notImplemented()
            }
        }

        val clickyChannel = MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "com.assistme/clicky"
        )
        clickyChannel.setMethodCallHandler { call, result ->
            when (call.method) {
                "start" -> result.success(mapOf("status" to startClickyGuide(call.arguments)))
                "stop" -> {
                    AssistMeAccessibilityService.instance?.stopClickyGuide()
                    result.success(null)
                }
                "isActive" -> result.success(
                    AssistMeAccessibilityService.instance?.isClickyGuideActive == true
                )
                else -> result.notImplemented()
            }
        }

        startNetworkWatch(
            MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "com.assistme/network")
        )

        val localAiChannel = MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "com.assistme/local_ai_device"
        )
        localAiChannel.setMethodCallHandler { call, result ->
            when (call.method) {
                "getDeviceInfo" -> result.success(localAiDeviceInfo())
                else -> result.notImplemented()
            }
        }

        val guideAudioChannel = MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "com.assistme/local_guide_audio"
        )
        guideAudioChannel.setMethodCallHandler { call, result ->
            when (call.method) {
                "decodeToPcm16kMono" -> {
                    val path = call.argument<String>("path")
                    if (path == null) {
                        result.error("INVALID_PATH", "Audio path is required.", null)
                    } else {
                        Thread {
                            try {
                                val pcm = LocalGuideAudioDecoder.decodeToPcm16kMono(
                                    cacheDir,
                                    path
                                )
                                runOnUiThread { result.success(pcm) }
                            } catch (_: Exception) {
                                runOnUiThread {
                                    result.error(
                                        "DECODE_FAILED",
                                        "Could not decode temporary guide audio.",
                                        null
                                    )
                                }
                            }
                        }.start()
                    }
                }
                else -> result.notImplemented()
            }
        }
    }

    /**
     * Facts the on-device AI needs before it downloads gigabytes: LiteRT-LM
     * ships only arm64-v8a libraries, and Gemma 4 E2B needs several GB of RAM.
     * [nativeAbi] is the ABI this process actually loaded its libraries for;
     * a 64-bit CPU running 32-bit Android reports armeabi-v7a here.
     */
    private fun localAiDeviceInfo(): Map<String, Any?> {
        val memory = android.app.ActivityManager.MemoryInfo()
        (getSystemService(ACTIVITY_SERVICE) as android.app.ActivityManager).getMemoryInfo(memory)
        val storage = android.os.StatFs(filesDir.absolutePath)
        val nativeLibDir = applicationInfo.nativeLibraryDir ?: ""
        val nativeAbi = when {
            nativeLibDir.endsWith("arm64") -> "arm64-v8a"
            nativeLibDir.endsWith("/arm") -> "armeabi-v7a"
            nativeLibDir.endsWith("x86_64") -> "x86_64"
            nativeLibDir.endsWith("x86") -> "x86"
            else -> Build.SUPPORTED_ABIS.firstOrNull() ?: ""
        }
        val hasLiteRtLm = hasNativeLibrary("libLiteRtLm.so", nativeAbi)
        return mapOf(
            "sdk_int" to Build.VERSION.SDK_INT,
            "release" to Build.VERSION.RELEASE,
            "model" to "${Build.MANUFACTURER} ${Build.MODEL}",
            "supported_abis" to Build.SUPPORTED_ABIS.toList(),
            "native_abi" to nativeAbi,
            "has_litert_lm" to hasLiteRtLm,
            "total_ram_bytes" to memory.totalMem,
            "available_ram_bytes" to memory.availMem,
            "low_ram_device" to (getSystemService(ACTIVITY_SERVICE) as android.app.ActivityManager).isLowRamDevice,
            "free_storage_bytes" to storage.availableBytes,
            "is_emulator" to (Build.FINGERPRINT.contains("generic") || Build.HARDWARE.contains("ranchu")),
        )
    }

    /**
     * Release builds keep native libraries uncompressed inside the APK
     * (`extractNativeLibs=false`) and load them from there, so the library
     * folder is empty. Look in the folder first, then in the APK files.
     */
    private fun hasNativeLibrary(name: String, abi: String): Boolean {
        val nativeLibDir = applicationInfo.nativeLibraryDir
        if (nativeLibDir != null && java.io.File(nativeLibDir, name).exists()) return true
        val apks = listOfNotNull(applicationInfo.sourceDir) +
            (applicationInfo.splitSourceDirs?.toList() ?: emptyList())
        return apks.any { path ->
            try {
                java.util.zip.ZipFile(path).use { it.getEntry("lib/$abi/$name") != null }
            } catch (_: java.io.IOException) {
                false
            }
        }
    }

    /** Validates the guide sent from Flutter and starts Clicky. Returns a status code. */
    private fun startClickyGuide(arguments: Any?): String {
        val args = arguments as? Map<*, *> ?: return "invalid_guide"
        val title = args["title"] as? String ?: ""
        val steps = (args["steps"] as? List<*>).orEmpty().mapNotNull { raw ->
            val step = raw as? Map<*, *> ?: return@mapNotNull null
            ClickyGuideStepInput(
                title = step["title"] as? String ?: "",
                instruction = step["instruction"] as? String ?: ""
            )
        }
        val startIndex = (args["start_index"] as? Number)?.toInt() ?: 0
        if (steps.none { it.title.isNotBlank() || it.instruction.isNotBlank() }) return "invalid_guide"

        val service = AssistMeAccessibilityService.instance
            ?: return if (isAccessibilityEnabled()) "accessibility_starting" else "accessibility_disabled"
        if (AssistMeAnnotationOverlayService.instance != null) return "help_session_active"
        if (!service.startClickyGuide(title, steps, startIndex)) return "failed"
        // Start from the home screen so the first step ("Open Settings") is visible.
        service.dispatchGlobalAction("home")
        return "started"
    }

    private fun isAccessibilityEnabled(): Boolean {
        val enabled = Settings.Secure.getString(
            contentResolver,
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
        ) ?: return false
        val component = ComponentName(this, AssistMeAccessibilityService::class.java)
            .flattenToString()
        return enabled.split(':').any { it.equals(component, ignoreCase = true) }
    }

    private var networkCallback: android.net.ConnectivityManager.NetworkCallback? = null

    /**
     * Tells Dart when the phone's default network changes (Wi-Fi <-> mobile
     * data). During a call the old signaling socket and media path can stay
     * half-open on the lost network for a long time, so the call reconnects
     * as soon as the new network is up instead of waiting for timeouts.
     */
    private fun startNetworkWatch(channel: MethodChannel) {
        val manager = getSystemService(CONNECTIVITY_SERVICE) as android.net.ConnectivityManager
        val main = android.os.Handler(android.os.Looper.getMainLooper())
        var current: android.net.Network? = null
        val callback = object : android.net.ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: android.net.Network) {
                main.post {
                    val previous = current
                    current = network
                    // The first callback only reports the network we started on.
                    if (previous == null || previous == network) return@post
                    val caps = manager.getNetworkCapabilities(network)
                    val transport = when {
                        caps == null -> "unknown"
                        caps.hasTransport(android.net.NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
                        caps.hasTransport(android.net.NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
                        else -> "other"
                    }
                    channel.invokeMethod("changed", mapOf("available" to true, "transport" to transport))
                }
            }

            override fun onLost(network: android.net.Network) {
                main.post {
                    if (current != network) return@post
                    channel.invokeMethod("changed", mapOf("available" to false, "transport" to "none"))
                }
            }
        }
        try {
            manager.registerDefaultNetworkCallback(callback)
            networkCallback = callback
        } catch (_: RuntimeException) {
            // Without the callback the call still recovers through its watchdog.
        }
    }

    override fun onDestroy() {
        networkCallback?.let { callback ->
            try {
                (getSystemService(CONNECTIVITY_SERVICE) as android.net.ConnectivityManager)
                    .unregisterNetworkCallback(callback)
            } catch (_: RuntimeException) {
            }
        }
        networkCallback = null
        AssistMeNativeBridge.channel = null
        super.onDestroy()
    }
}
