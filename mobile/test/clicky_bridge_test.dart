import 'package:assistme/core/guides/guide_models.dart';
import 'package:assistme/core/platform/clicky_bridge.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

GuideStepItem _step(int number, String title, String instruction) =>
    GuideStepItem(
      id: 'step-$number',
      stepNumber: number,
      title: title,
      instruction: instruction,
      localImagePath: '/private/frame_$number.frame.enc',
      createdAt: DateTime(2026, 10, 29),
    );

SessionGuideItem _guide(List<GuideStepItem> steps, {String summary = ''}) =>
    SessionGuideItem(
      id: 'guide-1',
      title: '  Connect to Wi-Fi  ',
      summary: summary,
      category: 'wifi',
      stepsCount: steps.length,
      createdAt: DateTime(2026, 10, 29),
      steps: steps,
      transcript: 'private transcript text',
      isLocal: true,
    );

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  tearDown(() {
    messenger.setMockMethodCallHandler(ClickyBridge.channel, null);
  });

  group('buildPayload', () {
    test('sends only trimmed step text, never images or transcript', () {
      final payload = ClickyBridge.buildPayload(
        _guide([
          _step(1, ' Open Settings ', 'Tap the Settings app'),
          _step(2, 'Wi-Fi', 'Tap "Wi-Fi"'),
        ]),
      );
      expect(payload['title'], 'Connect to Wi-Fi');
      expect(payload['steps'], [
        {'title': 'Open Settings', 'instruction': 'Tap the Settings app'},
        {'title': 'Wi-Fi', 'instruction': 'Tap "Wi-Fi"'},
      ]);
      expect(payload['start_index'], 0);
      expect(payload.toString(), isNot(contains('frame.enc')));
      expect(payload.toString(), isNot(contains('private transcript')));
    });

    test('skips blank steps and keeps the viewed step as start', () {
      final payload = ClickyBridge.buildPayload(
        _guide([
          _step(1, 'Open Settings', 'Tap Settings'),
          _step(2, '  ', ' '),
          _step(3, 'Wi-Fi', 'Tap Wi-Fi'),
        ]),
        startStepIndex: 2,
      );
      expect((payload['steps'] as List).length, 2);
      expect(payload['start_index'], 1);
    });

    test('falls back to the summary when a guide has no steps', () {
      final payload = ClickyBridge.buildPayload(
        _guide(const [], summary: 'Open Settings then tap Wi-Fi'),
      );
      expect(payload['steps'], [
        {
          'title': 'Connect to Wi-Fi',
          'instruction': 'Open Settings then tap Wi-Fi',
        },
      ]);
    });

    test('clips very long text', () {
      final payload = ClickyBridge.buildPayload(
        _guide([_step(1, 'T' * 500, 'I' * 5000)]),
      );
      final step = (payload['steps'] as List).single as Map;
      expect((step['title'] as String).length, 120);
      expect((step['instruction'] as String).length, 600);
    });
  });

  group('start', () {
    test('passes the payload to Android and maps every status', () async {
      MethodCall? received;
      var nextStatus = 'started';
      messenger.setMockMethodCallHandler(ClickyBridge.channel, (call) async {
        received = call;
        return {'status': nextStatus};
      });
      final guide = _guide([_step(1, 'Open Settings', 'Tap Settings')]);

      const expectations = {
        'started': ClickyStartStatus.started,
        'accessibility_disabled': ClickyStartStatus.accessibilityDisabled,
        'accessibility_starting': ClickyStartStatus.accessibilityStarting,
        'help_session_active': ClickyStartStatus.helpSessionActive,
        'invalid_guide': ClickyStartStatus.invalidGuide,
        'something_new': ClickyStartStatus.failed,
      };
      for (final entry in expectations.entries) {
        nextStatus = entry.key;
        expect(await ClickyBridge.start(guide), entry.value);
      }
      expect(received?.method, 'start');
      expect((received?.arguments as Map)['steps'], isA<List>());
    });

    test('does not call Android for a guide with nothing to follow', () async {
      var called = false;
      messenger.setMockMethodCallHandler(ClickyBridge.channel, (call) async {
        called = true;
        return {'status': 'started'};
      });
      final status = await ClickyBridge.start(_guide(const []));
      expect(status, ClickyStartStatus.invalidGuide);
      expect(called, isFalse);
    });

    test('platform errors become failed instead of throwing', () async {
      messenger.setMockMethodCallHandler(ClickyBridge.channel, (call) async {
        throw PlatformException(code: 'BOOM');
      });
      final status = await ClickyBridge.start(
        _guide([_step(1, 'Open Settings', 'Tap Settings')]),
      );
      expect(status, ClickyStartStatus.failed);
    });

    test('a missing native handler is reported as unsupported', () async {
      final status = await ClickyBridge.start(
        _guide([_step(1, 'Open Settings', 'Tap Settings')]),
      );
      expect(status, ClickyStartStatus.unsupported);
    });
  });
}
