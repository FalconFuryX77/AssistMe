import 'dart:typed_data';

import 'package:assistme/core/guides/session_keyframe_manager.dart';
import 'package:assistme/features/workspace/screenshot_review_sequence.dart';
import 'package:assistme/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

// A 1x1 transparent PNG, enough for Image.memory to decode.
final Uint8List _png = Uint8List.fromList(const [
  0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D,
  0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
  0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4, 0x89, 0x00, 0x00, 0x00,
  0x0D, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9C, 0x63, 0x00, 0x01, 0x00, 0x00,
  0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x49,
  0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
]);

CapturedKeyframe _frame(String id) => CapturedKeyframe(
  id: id,
  timestamp: DateTime(2026, 11, 2),
  imageBytes: _png,
  title: '',
  instruction: '',
  perceptualHash: null,
  colorSignature: null,
);

Future<List<CapturedKeyframe>?> _review(
  WidgetTester tester,
  List<CapturedKeyframe> frames,
  Future<void> Function() actions,
) async {
  List<CapturedKeyframe>? result;
  await tester.pumpWidget(
    MaterialApp(
      theme: AppTheme.darkTheme,
      home: Builder(
        builder: (context) => Scaffold(
          body: TextButton(
            onPressed: () async {
              result = await reviewScreenshotsInOrder(context, frames);
            },
            child: const Text('Review'),
          ),
        ),
      ),
    ),
  );
  await tester.tap(find.text('Review'));
  await tester.pumpAndSettle();
  await actions();
  await tester.pumpAndSettle();
  return result;
}

void main() {
  testWidgets('steps through each screenshot; removed ones are left out', (tester) async {
    final kept = await _review(tester, [_frame('a'), _frame('b'), _frame('c')], () async {
      expect(find.text('Screenshot 1 of 3'), findsOneWidget);
      await tester.tap(find.text('Looks good'));
      await tester.pumpAndSettle();
      expect(find.text('Screenshot 2 of 3'), findsOneWidget);
      await tester.tap(find.text('Remove'));
      await tester.pumpAndSettle();
      expect(find.text('Screenshot 3 of 3'), findsOneWidget);
      expect(find.text('Skip all'), findsNothing); // Nothing left to skip.
      await tester.tap(find.text('Done'));
    });
    expect(kept!.map((f) => f.id), ['a', 'c']);
    expect(kept.every((f) => f.privacyReviewed), isTrue);
  });

  testWidgets('Skip all keeps the current and every remaining screenshot', (tester) async {
    final kept = await _review(tester, [_frame('a'), _frame('b'), _frame('c')], () async {
      await tester.tap(find.text('Remove'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Skip all'));
    });
    expect(kept!.map((f) => f.id), ['b', 'c']);
  });

  testWidgets('no screenshots means no review screen', (tester) async {
    final kept = await _review(tester, const [], () async {});
    expect(kept, isEmpty);
    expect(find.textContaining('Screenshot'), findsNothing);
  });
}
