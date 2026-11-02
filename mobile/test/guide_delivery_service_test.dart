import 'dart:convert';
import 'dart:typed_data';

import 'package:assistme/core/guides/guide_delivery_service.dart';
import 'package:assistme/core/guides/session_keyframe_manager.dart';
import 'package:assistme/core/security/secure_storage_service.dart';
import 'package:flutter_test/flutter_test.dart';

class _MemoryStore implements SecureValueStore {
  final Map<String, String> values = {};

  @override
  Future<String?> read({required String key}) async => values[key];

  @override
  Future<void> write({required String key, required String value}) async {
    values[key] = value;
  }
}

CapturedKeyframe _step(String id, {List<int> image = const []}) =>
    CapturedKeyframe(
      id: id,
      timestamp: DateTime.utc(2026, 10, 30),
      imageBytes: Uint8List.fromList(image),
      title: 'Step $id',
      instruction: 'Tap "Settings".',
      perceptualHash: null,
      colorSignature: null,
      privacyReviewed: true,
    );

void main() {
  test('sealed guide opens only with the same key', () async {
    final key = GuideDeliveryService.newKey();
    final plaintext = utf8.encode('private guide');
    final sealed = await GuideDeliveryService.seal(key, plaintext);

    expect(
      latin1.decode(sealed, allowInvalid: true),
      isNot(contains('private guide')),
    );
    expect(await GuideDeliveryService.open(key, sealed), plaintext);
    await expectLater(
      GuideDeliveryService.open(GuideDeliveryService.newKey(), sealed),
      throwsA(anything),
    );
  });

  test('guide encoding keeps screenshot and text-only steps', () {
    final encoded = GuideDeliveryService.encodeGuide(
      title: 'Bluetooth help',
      summary: 'Turn on Bluetooth',
      transcript: 'We opened Settings.',
      frames: [_step('a', image: [1, 2, 3]), _step('b')],
    );
    final decoded = GuideDeliveryService.decodeGuide(encoded);

    expect(decoded.title, 'Bluetooth help');
    expect(decoded.transcript, 'We opened Settings.');
    expect(decoded.frames, hasLength(2));
    expect(decoded.frames[0].imageBytes, [1, 2, 3]);
    expect(decoded.frames[1].imageBytes, isEmpty);
    expect(decoded.frames[1].instruction, 'Tap "Settings".');
  });

  test('keys are remembered per session and old ones are pruned', () async {
    final store = _MemoryStore();
    final first = GuideDeliveryService.newKey();
    await GuideDeliveryService.rememberKey(store, 'session-0', first);
    for (var i = 1; i <= 40; i++) {
      await GuideDeliveryService.rememberKey(
        store,
        'session-$i',
        GuideDeliveryService.newKey(),
      );
    }

    expect(await GuideDeliveryService.keyFor(store, 'session-0'), isNull);
    expect(await GuideDeliveryService.keyFor(store, 'session-40'), hasLength(32));
    expect(await GuideDeliveryService.keyFor(store, 'missing'), isNull);
  });
}
