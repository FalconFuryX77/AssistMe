import 'dart:ui';

import 'package:flutter/services.dart';

/// Controls the helpee's always-on-top annotation layer. The native canvas is
/// non-touchable until the helpee explicitly taps DRAW; Clear and STOP remain
/// helpee-owned controls above the annotation layer.
class AnnotationOverlayService {
  static const MethodChannel _channel = MethodChannel(
    'com.assistme/annotation_overlay',
  );
  static void initialize({
    required Future<void> Function() onPanic,
    required Future<void> Function() onClear,
    void Function(List<Offset> points)? onDrawStroke,
    void Function()? onUndo,
    void Function()? onRedo,
  }) {
    _channel.setMethodCallHandler((call) async {
      switch (call.method) {
        case 'panic':
          await onPanic();
          break;
        case 'clear':
          await onClear();
          break;
        case 'drawStroke':
          final rawPoints = call.arguments is Map
              ? (call.arguments as Map)['points']
              : null;
          if (onDrawStroke != null && rawPoints is List) {
            final points = <Offset>[];
            for (final raw in rawPoints) {
              if (raw is Map && raw['x'] is num && raw['y'] is num) {
                points.add(
                  Offset(
                    (raw['x'] as num).toDouble(),
                    (raw['y'] as num).toDouble(),
                  ),
                );
              }
            }
            if (points.length > 1) onDrawStroke(points);
          }
          break;
        case 'undo':
          onUndo?.call();
          break;
        case 'redo':
          onRedo?.call();
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
