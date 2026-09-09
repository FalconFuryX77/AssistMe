/// Silent, event-driven keyframe manager for session guide synthesis.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:ui';
import 'package:flutter/foundation.dart';

class CapturedKeyframe {
  final String id;
  final DateTime timestamp;
  final Uint8List imageBytes;
  final String title;
  final String instruction;

  CapturedKeyframe({
    required this.id,
    required this.timestamp,
    required this.imageBytes,
    required this.title,
    required this.instruction,
  });

  Map<String, dynamic> toJson() {
    final b64 = base64Encode(imageBytes);
    return {
      'title': title,
      'instruction': instruction,
      'image_url': 'data:image/jpeg;base64,$b64',
    };
  }
}

class SessionKeyframeManager {
  final Future<Uint8List?> Function() captureFrameCallback;
  final List<CapturedKeyframe> _keyframes = [];
  Timer? _settleTimer;
  int? _lastFrameHash;

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
    if (totalDist < 0.04) return; // Path too short to be a meaningful guide step

    // Debounce settling timer: wait 750ms after the last stroke finishes
    // so multi-part drawings (e.g., arrow shaft + arrow head) render fully.
    _settleTimer?.cancel();
    _settleTimer = Timer(const Duration(milliseconds: 750), () async {
      await _captureSettledFrame(
        title: 'Step ${_keyframes.length + 1}',
        instruction: 'Tap the highlighted section indicated by your helper.',
      );
    });
  }

  /// Explicit manual capture triggered when helper or helpee taps "Bookmark Step".
  Future<void> manualBookmark({String? title, String? instruction}) async {
    _settleTimer?.cancel();
    await _captureSettledFrame(
      title: title ?? 'Step ${_keyframes.length + 1}',
      instruction: instruction ?? 'Follow the step shown on screen.',
      isManual: true,
    );
  }

  Future<void> _captureSettledFrame({
    required String title,
    required String instruction,
    bool isManual = false,
  }) async {
    try {
      final bytes = await captureFrameCallback();
      if (bytes == null || bytes.isEmpty) return;

      // Deduplication check: compare simple byte hash with previous keyframe
      final currentHash = bytes.length ^ (bytes[0] << 16) ^ (bytes[bytes.length - 1]);
      if (!isManual && _lastFrameHash != null && currentHash == _lastFrameHash) {
        return; // Content unchanged, skip duplicate
      }
      _lastFrameHash = currentHash;

      final kf = CapturedKeyframe(
        id: DateTime.now().millisecondsSinceEpoch.toString(),
        timestamp: DateTime.now(),
        imageBytes: bytes,
        title: title,
        instruction: instruction,
      );

      // Keep up to 6 highest quality keyframes
      if (_keyframes.length >= 6) {
        _keyframes.removeAt(0);
      }
      _keyframes.add(kf);
    } catch (e) {
      debugPrint('SessionKeyframeManager capture error: $e');
    }
  }

  List<Map<String, dynamic>> toPayloadList() {
    return _keyframes.map((kf) => kf.toJson()).toList();
  }

  void dispose() {
    _settleTimer?.cancel();
    _keyframes.clear();
  }
}
