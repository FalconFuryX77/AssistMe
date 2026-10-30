/// Burns opaque, normalized redaction regions into screenshot bytes.
///
/// Solid blocks are intentionally used instead of blur: blur can leave text
/// recoverable, while the exported image contains only the covered pixels.
library;

import 'dart:typed_data';
import 'dart:ui' as ui;

class NormalizedRedaction {
  final double left;
  final double top;
  final double right;
  final double bottom;

  const NormalizedRedaction({
    required this.left,
    required this.top,
    required this.right,
    required this.bottom,
  });
}

/// Re-encodes a guide screenshot so its longest side is at most [maxSide]
/// pixels. Full-resolution phone frames saved as PNG can exceed the 2 MB
/// per-step transfer limit; 1280 px keeps on-screen text readable.
/// Images already small enough are returned unchanged.
Future<Uint8List> shrinkGuideScreenshot(
  Uint8List sourceBytes, {
  int maxSide = 1280,
}) async {
  final buffer = await ui.ImmutableBuffer.fromUint8List(sourceBytes);
  final descriptor = await ui.ImageDescriptor.encoded(buffer);
  ui.Codec? codec;
  ui.Image? image;
  try {
    final longSide = descriptor.width > descriptor.height
        ? descriptor.width
        : descriptor.height;
    if (longSide <= maxSide) return sourceBytes;
    final scale = maxSide / longSide;
    codec = await descriptor.instantiateCodec(
      targetWidth: (descriptor.width * scale).round(),
      targetHeight: (descriptor.height * scale).round(),
    );
    image = (await codec.getNextFrame()).image;
    final data = await image.toByteData(format: ui.ImageByteFormat.png);
    if (data == null) throw StateError('Could not encode the screenshot.');
    return data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes);
  } finally {
    image?.dispose();
    codec?.dispose();
    descriptor.dispose();
    buffer.dispose();
  }
}

Future<Uint8List> burnInScreenshotRedactions(
  Uint8List sourceBytes,
  List<NormalizedRedaction> regions,
) async {
  final codec = await ui.instantiateImageCodec(sourceBytes);
  ui.Image? source;
  ui.Image? output;
  ui.Picture? picture;
  try {
    source = (await codec.getNextFrame()).image;
    final recorder = ui.PictureRecorder();
    final canvas = ui.Canvas(recorder);
    final imageRect = ui.Rect.fromLTWH(
      0,
      0,
      source.width.toDouble(),
      source.height.toDouble(),
    );
    canvas.drawImageRect(source, imageRect, imageRect, ui.Paint());
    final redactionPaint = ui.Paint()..color = const ui.Color(0xFF000000);
    for (final region in regions) {
      final left = region.left.clamp(0.0, 1.0) * source.width;
      final top = region.top.clamp(0.0, 1.0) * source.height;
      final right = region.right.clamp(0.0, 1.0) * source.width;
      final bottom = region.bottom.clamp(0.0, 1.0) * source.height;
      if (right <= left || bottom <= top) continue;
      canvas.drawRect(
        ui.Rect.fromLTRB(left, top, right, bottom),
        redactionPaint,
      );
    }
    picture = recorder.endRecording();
    output = await picture.toImage(source.width, source.height);
    final data = await output.toByteData(format: ui.ImageByteFormat.png);
    if (data == null) throw StateError('Could not encode reviewed screenshot.');
    return data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes);
  } finally {
    output?.dispose();
    picture?.dispose();
    source?.dispose();
    codec.dispose();
  }
}
