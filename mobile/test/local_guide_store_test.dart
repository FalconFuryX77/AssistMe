import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:assistme/core/guides/local_guide_store.dart';
import 'package:assistme/core/guides/session_keyframe_manager.dart';
import 'package:assistme/core/security/secure_storage_service.dart';
import 'package:flutter_test/flutter_test.dart';

class _MemorySecureStore implements SecureValueStore {
  final Map<String, String> values = {};

  @override
  Future<String?> read({required String key}) async => values[key];

  @override
  Future<void> write({required String key, required String value}) async {
    values[key] = value;
  }
}

void main() {
  late Directory tempDirectory;
  late Directory guideDirectory;
  late _MemorySecureStore secureStore;
  late LocalGuideStore store;

  setUp(() async {
    tempDirectory = await Directory.systemTemp.createTemp(
      'assistme-guide-test-',
    );
    guideDirectory = Directory(
      '${tempDirectory.path}${Platform.pathSeparator}local_guides_v1',
    );
    secureStore = _MemorySecureStore();
    store = LocalGuideStore(
      secureStorage: secureStore,
      directoryProvider: () async => tempDirectory,
    );
  });

  tearDown(() async {
    if (await tempDirectory.exists()) {
      await tempDirectory.delete(recursive: true);
    }
  });

  test(
    'encrypts transcript and screenshots, then decrypts them locally',
    () async {
      const transcript = 'PRIVATE_TRANSCRIPT_DO_NOT_WRITE_AS_PLAINTEXT';
      final image = Uint8List.fromList(utf8.encode('PRIVATE_SCREENSHOT_BYTES'));
      final guide = await store.saveSession(
        title: 'Network setup',
        summary: 'A private guide',
        transcript: transcript,
        frames: [
          CapturedKeyframe(
            id: 'frame-1',
            timestamp: DateTime.utc(2026, 10, 26),
            imageBytes: image,
            title: 'Open Wi-Fi settings',
            instruction: 'Select the network menu and choose your Wi-Fi.',
            perceptualHash: 1,
            colorSignature: 1,
          ),
        ],
      );

      final storedFiles = await guideDirectory
          .list()
          .where((e) => e is File)
          .cast<File>()
          .toList();
      expect(storedFiles, hasLength(2));
      final rawBytes = <int>[];
      for (final file in storedFiles) {
        rawBytes.addAll(await file.readAsBytes());
      }
      final rawText = latin1.decode(rawBytes, allowInvalid: true);
      expect(rawText, isNot(contains(transcript)));
      expect(rawText, isNot(contains('PRIVATE_SCREENSHOT_BYTES')));

      final listed = await store.listGuides();
      expect(listed, hasLength(1));
      expect(listed.single.transcript, transcript);
      expect(listed.single.steps.single.title, 'Open Wi-Fi settings');
      expect(
        listed.single.steps.single.instruction,
        'Select the network menu and choose your Wi-Fi.',
      );
      expect(await store.readImage(guide.steps.single.localImagePath), image);
    },
  );

  test('rejects modified encrypted screenshot data', () async {
    final guide = await store.saveSession(
      title: 'Guide',
      summary: '',
      transcript: '',
      frames: [
        CapturedKeyframe(
          id: 'frame-1',
          timestamp: DateTime.now(),
          imageBytes: Uint8List.fromList([1, 2, 3, 4]),
          title: 'Step',
          instruction: 'Do something',
          perceptualHash: null,
          colorSignature: null,
        ),
      ],
    );
    final imageFile = File(guide.steps.single.localImagePath!);
    final encrypted = await imageFile.readAsBytes();
    encrypted[encrypted.length - 1] ^= 0x01;
    await imageFile.writeAsBytes(encrypted, flush: true);

    expect(() => store.readImage(imageFile.path), throwsA(anything));
  });

  test('deleting a guide removes its encrypted metadata and image', () async {
    final guide = await store.saveSession(
      title: 'Guide',
      summary: '',
      transcript: '',
      frames: [
        CapturedKeyframe(
          id: 'frame-1',
          timestamp: DateTime.now(),
          imageBytes: Uint8List.fromList([1, 2, 3]),
          title: 'Step',
          instruction: 'Do something',
          perceptualHash: null,
          colorSignature: null,
        ),
      ],
    );
    await store.deleteGuide(guide);
    expect(await store.listGuides(), isEmpty);
    expect(await guideDirectory.list().toList(), isEmpty);
  });
}
