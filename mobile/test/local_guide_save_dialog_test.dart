import 'package:assistme/features/workspace/local_guide_save_dialog.dart';
import 'package:assistme/theme/app_theme.dart';
import 'package:flutter/material.dart';
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
}
