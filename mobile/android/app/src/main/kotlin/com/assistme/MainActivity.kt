package com.assistme

import android.content.ComponentName
import android.content.Intent
import android.os.Build
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
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

    private fun isAccessibilityEnabled(): Boolean {
        val enabled = Settings.Secure.getString(
            contentResolver,
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
        ) ?: return false
        val component = ComponentName(this, AssistMeAccessibilityService::class.java)
            .flattenToString()
        return enabled.split(':').any { it.equals(component, ignoreCase = true) }
    }

    override fun onDestroy() {
        AssistMeNativeBridge.channel = null
        super.onDestroy()
    }
}
