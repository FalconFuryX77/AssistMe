/// Temporary, on-device capture of each WebRTC audio direction for a guide.
///
/// The current flutter_webrtc native audio recorder exposes its INPUT and
/// OUTPUT sample taps on Android. Files are written only to the app cache and
/// must be deleted after local transcription or if the user discards the
/// guide. No audio bytes are sent over AssistMe networking by this class.
library;

import 'dart:io';

import 'package:flutter_webrtc/flutter_webrtc.dart';
import 'package:path_provider/path_provider.dart';

enum GuideAudioCaptureStatus { off, waitingForPeer, recording }

class LocalGuideAudioRecording {
  final String microphonePath;
  final String remoteAudioPath;

  const LocalGuideAudioRecording({
    required this.microphonePath,
    required this.remoteAudioPath,
  });

  Future<void> delete() async {
    Object? deletionError;
    for (final path in [microphonePath, remoteAudioPath]) {
      try {
        final file = File(path);
        if (await file.exists()) await file.delete();
      } catch (error) {
        deletionError ??= error;
      }
    }
    if (deletionError != null) {
      throw StateError('Could not remove temporary guide audio.');
    }
  }
}

class LocalGuideAudioCapture {
  static Future<void>? _staleCleanupOperation;

  MediaRecorder? _microphoneRecorder;
  MediaRecorder? _remoteAudioRecorder;
  String? _microphonePath;
  String? _remoteAudioPath;
  Future<void>? _startOperation;

  bool get isRecording => _microphoneRecorder != null;

  /// Starts local mic and rendered remote-call audio recording on Android.
  /// Call only after both participants have explicitly consented.
  Future<void> start() {
    if (!Platform.isAndroid) {
      return Future<void>.error(
        UnsupportedError(
          'In-call guide audio capture is currently supported on Android only.',
        ),
      );
    }
    if (isRecording) return Future<void>.value();
    final activeStart = _startOperation;
    if (activeStart != null) return activeStart;
    final operation = _startInternal();
    _startOperation = operation;
    return operation.whenComplete(() {
      if (identical(_startOperation, operation)) _startOperation = null;
    });
  }

  Future<void> _startInternal() async {
    var micRecorder = MediaRecorder();
    var remoteRecorder = MediaRecorder();
    var micPath = '';
    var remotePath = '';
    try {
      await clearStaleRecordings();
      final cache = await getTemporaryDirectory();
      final prefix = 'assistme-guide-${DateTime.now().microsecondsSinceEpoch}';
      micPath = '${cache.path}${Platform.pathSeparator}$prefix-mic.mp4';
      remotePath = '${cache.path}${Platform.pathSeparator}$prefix-remote.mp4';
      await micRecorder.start(
        micPath,
        audioChannel: RecorderAudioChannel.INPUT,
      );
      await remoteRecorder.start(
        remotePath,
        audioChannel: RecorderAudioChannel.OUTPUT,
      );
      _microphonePath = micPath;
      _remoteAudioPath = remotePath;
      _microphoneRecorder = micRecorder;
      _remoteAudioRecorder = remoteRecorder;
    } catch (_) {
      try {
        await micRecorder.stop();
      } catch (_) {}
      try {
        await remoteRecorder.stop();
      } catch (_) {}
      if (micPath.isNotEmpty && remotePath.isNotEmpty) {
        await LocalGuideAudioRecording(
          microphonePath: micPath,
          remoteAudioPath: remotePath,
        ).delete();
      }
      rethrow;
    }
  }

  /// Removes only files created by this feature after an interrupted app run.
  static Future<void> clearStaleRecordings() =>
      _staleCleanupOperation ??= _clearStaleRecordings();

  static Future<void> _clearStaleRecordings() async {
    try {
      final cache = await getTemporaryDirectory();
      await for (final entity in cache.list(followLinks: false)) {
        if (entity is File &&
            entity.uri.pathSegments.last.startsWith('assistme-guide-') &&
            entity.path.endsWith('.mp4')) {
          try {
            await entity.delete();
          } catch (_) {}
        }
      }
    } catch (_) {}
  }

  /// Stops the native taps and returns the temporary files to the caller.
  /// The caller owns deletion and must delete them on success, cancellation,
  /// and all error paths.
  Future<LocalGuideAudioRecording?> stop() async {
    final startOperation = _startOperation;
    if (startOperation != null) {
      try {
        await startOperation;
      } catch (_) {
        return null;
      }
    }
    final micRecorder = _microphoneRecorder;
    final remoteRecorder = _remoteAudioRecorder;
    final micPath = _microphonePath;
    final remotePath = _remoteAudioPath;
    _microphoneRecorder = null;
    _remoteAudioRecorder = null;
    _microphonePath = null;
    _remoteAudioPath = null;

    if (micRecorder == null || remoteRecorder == null) return null;

    Object? stopError;
    try {
      await micRecorder.stop();
    } catch (error) {
      stopError = error;
    }
    try {
      await remoteRecorder.stop();
    } catch (error) {
      stopError ??= error;
    }
    if (stopError != null) {
      final recording = LocalGuideAudioRecording(
        microphonePath: micPath!,
        remoteAudioPath: remotePath!,
      );
      await recording.delete();
      throw StateError('Could not safely finalize temporary call audio.');
    }

    return LocalGuideAudioRecording(
      microphonePath: micPath!,
      remoteAudioPath: remotePath!,
    );
  }

  /// Stops any active native recorders and deletes all app-owned temporary
  /// audio. Safe to call repeatedly from teardown paths.
  Future<void> dispose() async {
    try {
      await _startOperation;
      final recording = await stop();
      await recording?.delete();
    } catch (_) {
      final micPath = _microphonePath;
      final remotePath = _remoteAudioPath;
      if (micPath != null && remotePath != null) {
        await LocalGuideAudioRecording(
          microphonePath: micPath,
          remoteAudioPath: remotePath,
        ).delete();
      }
    }
  }
}
