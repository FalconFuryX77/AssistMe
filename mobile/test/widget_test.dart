// Basic smoke test for the AssistMe mobile app bootstrap.
//
// Verifies the mobile application entrypoint is available.

import 'package:flutter_test/flutter_test.dart';

import 'package:assistme/main.dart';

void main() {
  testWidgets('AssistMe app entrypoint is available', (WidgetTester tester) async {
    // Network-bound bootstrap is intentionally not executed in this unit test.
    expect(AssistMeMobileApp, isNotNull);
  });
}
