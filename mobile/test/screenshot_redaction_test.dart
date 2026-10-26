import 'dart:ui' as ui;

import 'package:assistme/core/guides/screenshot_redaction.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'burns redactions into pixels while preserving uncovered pixels',
    () async {
      final recorder = ui.PictureRecorder();
      final canvas = ui.Canvas(recorder);
      canvas.drawColor(const ui.Color(0xFF1432C8), ui.BlendMode.src);
      final picture = recorder.endRecording();
      final original = await picture.toImage(10, 10);
      final encoded = await original.toByteData(format: ui.ImageByteFormat.png);
      expect(encoded, isNotNull);

      final output = await burnInScreenshotRedactions(
        encoded!.buffer.asUint8List(),
        const [
          NormalizedRedaction(left: 0.2, top: 0.2, right: 0.8, bottom: 0.8),
        ],
      );
      final codec = await ui.instantiateImageCodec(output);
      final redacted = (await codec.getNextFrame()).image;
      final pixels = await redacted.toByteData(
        format: ui.ImageByteFormat.rawRgba,
      );
      expect(pixels, isNotNull);

      List<int> pixelAt(int x, int y) {
        final offset = (y * redacted.width + x) * 4;
        return [
          pixels!.getUint8(offset),
          pixels.getUint8(offset + 1),
          pixels.getUint8(offset + 2),
          pixels.getUint8(offset + 3),
        ];
      }

      expect(pixelAt(5, 5), [0, 0, 0, 255]);
      expect(pixelAt(0, 0), [20, 50, 200, 255]);

      redacted.dispose();
      codec.dispose();
      original.dispose();
      picture.dispose();
    },
  );
}
