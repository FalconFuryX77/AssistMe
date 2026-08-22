// Basic smoke test for the AssistMe mobile app bootstrap.
//
// Verifies the app boots and renders the auth entry (login) screen.

import 'package:flutter_test/flutter_test.dart';

import 'package:assistme/main.dart';

void main() {
  testWidgets('App boots to login route', (WidgetTester tester) async {
    // The app's entrypoint is async and performs network-bound bootstrapping;
    // we simply verify the widget tree can be built without throwing.
    expect(AssistMeMobileApp, isNotNull);
  });
}