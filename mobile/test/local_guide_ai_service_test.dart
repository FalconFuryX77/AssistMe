import 'package:assistme/core/guides/local_guide_ai_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('parseStep', () {
    test('reads TITLE and ACTION lines', () {
      final step = LocalGuideAiService.parseStep(
        'TITLE: Open Wi-Fi settings\nACTION: Tap "Settings", then tap "Wi-Fi".',
        stepNumber: 2,
      );
      expect(step.title, 'Open Wi-Fi settings');
      expect(step.instruction, 'Tap "Settings", then tap "Wi-Fi".');
    });

    test('tolerates markdown bold and lower case labels', () {
      final step = LocalGuideAiService.parseStep(
        '**Title**: Turn on Bluetooth\n**action**: Tap "Bluetooth".',
        stepNumber: 1,
      );
      expect(step.title, 'Turn on Bluetooth');
      expect(step.instruction, 'Tap "Bluetooth".');
    });

    test('falls back to the raw text and a numbered title', () {
      final step = LocalGuideAiService.parseStep(
        'Press the power button.',
        stepNumber: 3,
      );
      expect(step.title, 'Step 3');
      expect(step.instruction, 'Press the power button.');
    });
  });

  group('parseStepList', () {
    test('reads STEP lines with and without numbers', () {
      final steps = LocalGuideAiService.parseStepList('''
STEP: Open Settings | Tap "Settings" on the home screen.
2. STEP: Open Wi-Fi | Tap "Network & internet", then "Internet".
STEP 3: Join the network | Tap "HomeWiFi" and enter the password.
Some chatter the model added.
''');
      expect(steps.map((step) => step.title), [
        'Open Settings',
        'Open Wi-Fi',
        'Join the network',
      ]);
      expect(steps[1].instruction, 'Tap "Network & internet", then "Internet".');
    });

    test('returns nothing for unusable output', () {
      expect(LocalGuideAiService.parseStepList('I cannot help with that.'), isEmpty);
    });

    test('keeps at most eight steps', () {
      final output = List.generate(12, (i) => 'STEP: Step $i | Do thing $i').join('\n');
      expect(LocalGuideAiService.parseStepList(output), hasLength(8));
    });
  });

  group('clipTranscript', () {
    test('marks an empty transcript', () {
      expect(
        LocalGuideAiService.clipTranscript('  ', 100),
        '[No transcript or notes provided]',
      );
    });

    test('keeps the end of a long transcript', () {
      final clipped = LocalGuideAiService.clipTranscript(
        'start ${'x' * 50} the fix was here',
        20,
      );
      expect(clipped, startsWith('…'));
      expect(clipped, endsWith('the fix was here'));
      expect(clipped.length, 21);
    });
  });
}
