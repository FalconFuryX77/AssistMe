import 'package:flutter/services.dart';

/// Small, explicit bridge to the Android accessibility service.  The service
/// is never enabled or used implicitly; the helpee must turn it on after the
/// phase-three risk screen.
class AccessibilityBridge {
  static const MethodChannel _channel = MethodChannel(
    'com.assistme/accessibility',
  );

  static Future<bool> isEnabled() async {
    try {
      return await _channel.invokeMethod<bool>('isEnabled') ?? false;
    } on PlatformException {
      return false;
    }
  }

  static Future<void> openSettings() async {
    await _channel.invokeMethod<void>('openSettings');
  }

  static Future<bool> dispatchInput(Map<String, dynamic> event) async {
    try {
      return await _channel.invokeMethod<bool>('dispatchInput', event) ?? false;
    } on PlatformException {
      return false;
    }
  }
}
