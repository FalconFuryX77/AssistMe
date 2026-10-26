import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:assistme/core/guides/session_keyframe_manager.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'deduplicates visual repeats without imposing a six-frame limit',
    () async {
      final distinctFrames = [
        for (var stripe = 1; stripe <= 7; stripe++)
          await _screenWithStripe(stripe),
      ];
      var nextFrame = 0;
      final manager = SessionKeyframeManager(
        captureFrameCallback: () async => distinctFrames[nextFrame++],
      );

      for (var i = 0; i < distinctFrames.length; i++) {
        await manager.manualBookmark();
      }
      expect(manager.count, 7);

      nextFrame = distinctFrames.length - 1;
      final duplicateResult = await manager.manualBookmark();
      expect(duplicateResult, KeyframeCaptureResult.duplicate);
      expect(manager.count, 7);

      manager.dispose();
    },
  );
}

Future<Uint8List> _screenWithStripe(int stripeX) async {
  final recorder = ui.PictureRecorder();
  final canvas = ui.Canvas(recorder);
  canvas.drawRect(
    const ui.Rect.fromLTWH(0, 0, 9, 8),
    ui.Paint()..color = const ui.Color(0xff000000),
  );
  canvas.drawRect(
    ui.Rect.fromLTWH(stripeX.toDouble(), 0, 1, 8),
    ui.Paint()..color = const ui.Color(0xffffffff),
  );
  final picture = recorder.endRecording();
  final image = await picture.toImage(9, 8);
  final data = await image.toByteData(format: ui.ImageByteFormat.png);
  image.dispose();
  return data!.buffer.asUint8List();
}
