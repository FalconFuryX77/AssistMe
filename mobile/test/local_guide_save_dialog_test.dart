import 'package:assistme/features/workspace/local_guide_save_dialog.dart';
import 'package:assistme/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  tearDown(() => AppTheme.setDarkMode(true));

  testWidgets('save action accepts a note-only private guide', (tester) async {
    AppTheme.setDarkMode(false);
    LocalGuideSaveInput? savedGuide;

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.lightTheme,
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () async {
                savedGuide = await showDialog<LocalGuideSaveInput>(
                  context: context,
                  builder: (_) => const LocalGuideSaveDialog(
                    frames: [],
                    suggestedTitle: 'Connection help',
                  ),
                );
              },
              child: const Text('Open guide editor'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Open guide editor'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).at(1), 'Restart the router.');
    await tester.tap(find.text('Save private guide'));
    await tester.pumpAndSettle();

    expect(savedGuide, isNotNull);
    expect(savedGuide!.title, 'Connection help');
    expect(savedGuide!.transcript, 'Restart the router.');
    expect(savedGuide!.includedFrameIds, isEmpty);
  });

  testWidgets('a written step without a screenshot is saved', (tester) async {
    AppTheme.setDarkMode(false);
    // A 32-bit phone: the AI is unavailable, but saving must still work.
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      const MethodChannel('com.assistme/local_ai_device'),
      (call) async => {
        'sdk_int': 31,
        'release': '12',
        'model': 'Old Phone',
        'native_abi': 'armeabi-v7a',
        'has_litert_lm': false,
        'total_ram_bytes': 3 * 1024 * 1024 * 1024,
        'free_storage_bytes': 8 * 1024 * 1024 * 1024,
        'is_emulator': false,
      },
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        const MethodChannel('com.assistme/local_ai_device'),
        null,
      ),
    );
    LocalGuideSaveInput? savedGuide;

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.lightTheme,
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () async {
                savedGuide = await showDialog<LocalGuideSaveInput>(
                  context: context,
                  builder: (_) => const LocalGuideSaveDialog(
                    frames: [],
                    suggestedTitle: 'Bluetooth help',
                    helperCuratedFrames: true,
                    guideOwner: true,
                  ),
                );
              },
              child: const Text('Open guide editor'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Open guide editor'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Add a written step'));
    await tester.tap(find.text('Add a written step'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byType(TextField).at(2),
      'Open Bluetooth',
    );
    await tester.enterText(
      find.byType(TextField).at(3),
      'Tap "Settings", then tap "Bluetooth".',
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('32-bit Android'), findsOneWidget);
    await tester.ensureVisible(find.text('Save private guide'));
    await tester.tap(find.text('Save private guide'));
    await tester.pumpAndSettle();

    expect(savedGuide, isNotNull);
    expect(savedGuide!.textSteps.single.title, 'Open Bluetooth');
    expect(
      savedGuide!.textSteps.single.instruction,
      'Tap "Settings", then tap "Bluetooth".',
    );
  });
}
