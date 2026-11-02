/// Bridge to Clicky, the on-device guide walkthrough that runs on top of other
/// apps. Only the step titles and instructions are sent to the native side;
/// screenshots and transcripts stay in the encrypted guide store.
library;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../guides/guide_models.dart';

enum ClickyStartStatus {
  started,
  accessibilityDisabled,
  accessibilityStarting,
  helpSessionActive,
  invalidGuide,
  unsupported,
  failed,
}

class ClickyBridge {
  @visibleForTesting
  static const MethodChannel channel = MethodChannel('com.assistme/clicky');

  static const int _maxTitleCharacters = 120;
  static const int _maxInstructionCharacters = 600;
  static const int _maxSteps = 100;

  /// Pointing at controls inside other apps is only possible on Android.
  static bool get isSupported =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

  /// Builds the minimal, text-only payload for the native side. Blank steps
  /// are skipped and [startStepIndex] is remapped so Clicky starts on the
  /// same step the user is currently viewing.
  @visibleForTesting
  static Map<String, Object> buildPayload(
    SessionGuideItem guide, {
    int startStepIndex = 0,
  }) {
    final steps = <Map<String, String>>[];
    var mappedStart = 0;
    if (guide.steps.isEmpty) {
      final summary = _clip(guide.summary, _maxInstructionCharacters);
      if (summary.isNotEmpty) {
        steps.add({
          'title': _clip(guide.title, _maxTitleCharacters),
          'instruction': summary,
        });
      }
    } else {
      for (var i = 0; i < guide.steps.length && steps.length < _maxSteps; i++) {
        final step = guide.steps[i];
        final title = _clip(step.title, _maxTitleCharacters);
        final instruction = _clip(step.instruction, _maxInstructionCharacters);
        if (title.isEmpty && instruction.isEmpty) continue;
        if (i <= startStepIndex) mappedStart = steps.length;
        steps.add({'title': title, 'instruction': instruction});
      }
    }
    return {
      'title': _clip(guide.title, _maxTitleCharacters),
      'steps': steps,
      // Always a valid index into [steps]: it is only ever set to an index
      // of a step that was just added.
      'start_index': mappedStart,
    };
  }

  static String _clip(String value, int maxCharacters) {
    final trimmed = value.trim();
    return trimmed.length <= maxCharacters
        ? trimmed
        : trimmed.substring(0, maxCharacters);
  }

  @visibleForTesting
  static ClickyStartStatus parseStatus(Object? result) {
    final status = result is Map ? result['status'] : null;
    switch (status) {
      case 'started':
        return ClickyStartStatus.started;
      case 'accessibility_disabled':
        return ClickyStartStatus.accessibilityDisabled;
      case 'accessibility_starting':
        return ClickyStartStatus.accessibilityStarting;
      case 'help_session_active':
        return ClickyStartStatus.helpSessionActive;
      case 'invalid_guide':
        return ClickyStartStatus.invalidGuide;
      default:
        return ClickyStartStatus.failed;
    }
  }

  static Future<ClickyStartStatus> start(
    SessionGuideItem guide, {
    int startStepIndex = 0,
  }) async {
    if (!isSupported) return ClickyStartStatus.unsupported;
    final payload = buildPayload(guide, startStepIndex: startStepIndex);
    if ((payload['steps'] as List).isEmpty) {
      return ClickyStartStatus.invalidGuide;
    }
    try {
      return parseStatus(await channel.invokeMethod<Object?>('start', payload));
    } on PlatformException {
      return ClickyStartStatus.failed;
    } on MissingPluginException {
      return ClickyStartStatus.unsupported;
    }
  }

  static Future<void> stop() async {
    if (!isSupported) return;
    try {
      await channel.invokeMethod<void>('stop');
    } on PlatformException {
      // Nothing to clean up on the Flutter side.
    } on MissingPluginException {
      // Older native build without Clicky.
    }
  }
}
