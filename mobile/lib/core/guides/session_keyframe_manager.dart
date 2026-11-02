/// Silent, event-driven keyframe manager for session guide synthesis.
library;

import 'dart:async';
import 'dart:math';
import 'dart:ui';
import 'package:flutter/foundation.dart';

enum KeyframeCaptureResult { saved, duplicate, capacityReached, unavailable }

class CapturedKeyframe {
  final String id;
  final DateTime timestamp;
  final Uint8List imageBytes;
  final String title;
  final String instruction;
  final int? perceptualHash;
  final int? colorSignature;
  final bool privacyReviewed;

  CapturedKeyframe({
    required this.id,
    required this.timestamp,
    required this.imageBytes,
    required this.title,
    required this.instruction,
    required this.perceptualHash,
    required this.colorSignature,
    this.privacyReviewed = false,
  });
}

class SessionKeyframeManager {
  final Future<Uint8List?> Function() captureFrameCallback;
  final List<CapturedKeyframe> _keyframes = [];
  Timer? _settleTimer;
  int _retainedBytes = 0;

  // Bound session memory without silently imposing a small, arbitrary number
  // of guide steps. Older frames are evicted only when this byte budget fills.
  static const int _maxRetainedBytes = 32 * 1024 * 1024;

  SessionKeyframeManager({required this.captureFrameCallback});

  List<CapturedKeyframe> get keyframes => List.unmodifiable(_keyframes);
  int get count => _keyframes.length;

  /// Triggered strictly when a stroke has fully completed (finger lifted),
  /// never on the initial touch or mid-drag.
  void onStrokeCompleted(List<Offset> points) {
    if (points.length < 4) return; // Ignore single accidental taps

    // Calculate total path distance to ignore tiny jitter or doodles
    double totalDist = 0.0;
    for (int i = 1; i < points.length; i++) {
      totalDist += (points[i] - points[i - 1]).distance;
    }
    if (totalDist < 0.04) {
      return; // Path too short to be a meaningful guide step
    }

    // Debounce settling timer: wait 750ms after the last stroke finishes
    // so multi-part drawings (e.g., arrow shaft + arrow head) render fully.
    _settleTimer?.cancel();
    _settleTimer = Timer(const Duration(milliseconds: 750), () async {
      await _captureSettledFrame(
        title: 'Step ${_keyframes.length + 1}',
        instruction:
            'This screenshot marks a step in the call. Use the saved notes for the exact action.',
      );
    });
  }

  /// Explicit manual capture triggered when helper or helpee taps "Bookmark Step".
  Future<KeyframeCaptureResult> manualBookmark({
    String? title,
    String? instruction,
  }) async {
    _settleTimer?.cancel();
    return _captureSettledFrame(
      title: title ?? 'Step ${_keyframes.length + 1}',
      instruction:
          instruction ??
          'This screenshot marks a step in the call. Use the saved notes for the exact action.',
    );
  }

  Future<KeyframeCaptureResult> _captureSettledFrame({
    required String title,
    required String instruction,
  }) async {
    try {
      final bytes = await captureFrameCallback();
      if (bytes == null || bytes.isEmpty) {
        return KeyframeCaptureResult.unavailable;
      }
      return await _storeFrameBytes(
        bytes,
        title: title,
        instruction: instruction,
        privacyReviewed: false,
      );
    } catch (error) {
      debugPrint('SessionKeyframeManager capture error: $error');
      return KeyframeCaptureResult.unavailable;
    }
  }

  /// Stores a step the helper chose and reviewed. It is never rejected as a
  /// "duplicate": two different screens of one app (e.g. two white Settings
  /// lists) can share a 9x8 thumbnail, and the helper picked this one on
  /// purpose. Re-sending the same [id] replaces nothing and reports saved.
  Future<KeyframeCaptureResult> addPreReviewedFrame(
    Uint8List bytes, {
    required String title,
    required String instruction,
    String? id,
  }) async {
    if (id != null && _keyframes.any((frame) => frame.id == id)) {
      return KeyframeCaptureResult.saved;
    }
    return _storeFrameBytes(
      bytes,
      title: title,
      instruction: instruction,
      privacyReviewed: true,
      id: id,
      checkDuplicates: false,
    );
  }

  /// Stores a screenshot the helper took during the call with one tap. It is
  /// not reviewed yet: the helper covers private details after the call, and
  /// it is never sent to anyone before that. The step's words come later
  /// from the transcript (or the helper), so none are asked for now.
  Future<KeyframeCaptureResult> addHelperCapture(
    Uint8List bytes, {
    required String id,
  }) {
    return _storeFrameBytes(
      bytes,
      title: '',
      instruction: '',
      privacyReviewed: false,
      id: id,
      checkDuplicates: false,
    );
  }

  Future<KeyframeCaptureResult> _storeFrameBytes(
    Uint8List bytes, {
    required String title,
    required String instruction,
    required bool privacyReviewed,
    String? id,
    bool checkDuplicates = true,
  }) async {
    if (bytes.isEmpty || bytes.length > _maxRetainedBytes) {
      return KeyframeCaptureResult.unavailable;
    }
    final fingerprint = await _differenceHash(bytes);
    if (checkDuplicates &&
        fingerprint != null &&
        _keyframes.any(
          (frame) =>
              frame.perceptualHash != null &&
              frame.colorSignature != null &&
              _hammingDistance(frame.perceptualHash!, fingerprint.difference) <=
                  2 &&
              _colorDistance(frame.colorSignature!, fingerprint.color) <= 12,
        )) {
      return KeyframeCaptureResult.duplicate;
    }
    if (_retainedBytes + bytes.length > _maxRetainedBytes) {
      return KeyframeCaptureResult.capacityReached;
    }
    _keyframes.add(
      CapturedKeyframe(
        id:
            id ??
            '${DateTime.now().microsecondsSinceEpoch}_${Random.secure().nextInt(1 << 32)}',
        timestamp: DateTime.now(),
        imageBytes: Uint8List.fromList(bytes),
        title: title,
        instruction: instruction,
        perceptualHash: fingerprint?.difference,
        colorSignature: fingerprint?.color,
        privacyReviewed: privacyReviewed,
      ),
    );
    _retainedBytes += bytes.length;
    return KeyframeCaptureResult.saved;
  }

  /// Computes a 64-bit difference hash from a 9x8 grayscale thumbnail. This
  /// catches visually identical captures even if JPEG byte encodings differ.
  Future<({int difference, int color})?> _differenceHash(
    Uint8List bytes,
  ) async {
    Codec? codec;
    Image? image;
    try {
      codec = await instantiateImageCodec(
        bytes,
        targetWidth: 9,
        targetHeight: 8,
      );
      image = (await codec.getNextFrame()).image;
      final pixels = await image.toByteData(format: ImageByteFormat.rawRgba);
      if (pixels == null) return null;
      final pixelData = pixels;
      var totalRed = 0;
      var totalGreen = 0;
      var totalBlue = 0;
      for (var pixel = 0; pixel < 9 * 8; pixel++) {
        final offset = pixel * 4;
        totalRed += pixelData.getUint8(offset);
        totalGreen += pixelData.getUint8(offset + 1);
        totalBlue += pixelData.getUint8(offset + 2);
      }

      int grayAt(int x, int y) {
        final offset = (y * 9 + x) * 4;
        final red = pixelData.getUint8(offset);
        final green = pixelData.getUint8(offset + 1);
        final blue = pixelData.getUint8(offset + 2);
        return (red * 299 + green * 587 + blue * 114) ~/ 1000;
      }

      var hash = 0;
      var bit = 0;
      for (var y = 0; y < 8; y++) {
        for (var x = 0; x < 8; x++) {
          if (grayAt(x, y) > grayAt(x + 1, y)) hash |= 1 << bit;
          bit++;
        }
      }
      final sampleCount = 9 * 8;
      final colorSignature =
          ((totalRed ~/ sampleCount) << 16) |
          ((totalGreen ~/ sampleCount) << 8) |
          (totalBlue ~/ sampleCount);
      return (difference: hash, color: colorSignature);
    } catch (_) {
      // Keep the capture if this image format cannot be decoded here.
      return null;
    } finally {
      image?.dispose();
      codec?.dispose();
    }
  }

  int _hammingDistance(int left, int right) {
    var differingBits = left ^ right;
    var count = 0;
    while (differingBits != 0) {
      differingBits &= differingBits - 1;
      count++;
    }
    return count;
  }

  int _colorDistance(int left, int right) {
    final redDistance = ((left >> 16) & 0xff) - ((right >> 16) & 0xff);
    final greenDistance = ((left >> 8) & 0xff) - ((right >> 8) & 0xff);
    final blueDistance = (left & 0xff) - (right & 0xff);
    return [
      redDistance.abs(),
      greenDistance.abs(),
      blueDistance.abs(),
    ].reduce((largest, distance) => distance > largest ? distance : largest);
  }

  void dispose() {
    _settleTimer?.cancel();
    _keyframes.clear();
    _retainedBytes = 0;
  }
}
