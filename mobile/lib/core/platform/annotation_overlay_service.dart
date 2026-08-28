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
    void Function(List<Offset> points, int color, double width)? onDrawStroke,
    void Function(Offset point)? onErase,
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
          final args = call.arguments is Map ? call.arguments as Map : null;
          final rawPoints = args?['points'];
          final rawColor = args?['color'];
          final rawWidth = args?['width'];
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
            final color = rawColor is int ? rawColor : 0xFFFF3B30;
            final width = rawWidth is num ? rawWidth.toDouble() : 4.0;
            if (points.isNotEmpty) onDrawStroke(points, color, width);
          }
          break;
        case 'erase':
          final args = call.arguments is Map ? call.arguments as Map : null;
          final rx = args?['x'];
          final ry = args?['y'];
          if (onErase != null && rx is num && ry is num) {
            onErase(Offset(rx.toDouble(), ry.toDouble()));
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
