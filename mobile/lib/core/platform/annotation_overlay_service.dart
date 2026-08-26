import 'package:flutter/services.dart';

/// Controls the helpee's always-on-top annotation layer.  The drawing canvas
/// is non-touchable; only the helpee-owned Clear and Panic Stop controls are
/// touchable.  This keeps the helper from ever receiving input on the helpee's
/// phone while the helpee is using another app.
class AnnotationOverlayService {
  static const MethodChannel _channel = MethodChannel(
    'com.assistme/annotation_overlay',
  );
  static void initialize({
    required Future<void> Function() onPanic,
    required Future<void> Function() onClear,
  }) {
    _channel.setMethodCallHandler((call) async {
      switch (call.method) {
        case 'panic':
          await onPanic();
          break;
        case 'clear':
          await onClear();
          break;
      }
    });
  }

  static Future<bool> canDrawOverlays() async {
    try {
      return await _channel.invokeMethod<bool>('isPermissionGranted') ?? false;
    } on PlatformException {
      return false;
    }
  }

  static Future<void> requestPermission() async {
    await _channel.invokeMethod<void>('requestPermission');
  }

  static Future<void> start() async {
    await _channel.invokeMethod<void>('start');
  }

  static Future<void> updateStrokes(List<Map<String, dynamic>> strokes) async {
    await _channel.invokeMethod<void>('updateStrokes', strokes);
  }

  static Future<void> clear() async {
    await _channel.invokeMethod<void>('clear');
  }

  static Future<void> stop() async {
    await _channel.invokeMethod<void>('stop');
  }
}
